import { readFile } from "node:fs/promises";
import { timingSafeEqual } from "node:crypto";
import { createServer } from "node:http";
import { pathToFileURL } from "node:url";
import * as db from "@prairielearn/postgres";
import { z } from "zod";
import {
  BridgeError,
  assertProductionRuntime,
  isCanonicalEmail,
} from "./policy.mjs";
const root = process.env.PL_ROOT ?? "/PrairieLearn";
/** @template {keyof import("../types/native-contracts.d.ts").NativeModules} K @param {K} path @returns {Promise<import("../types/native-contracts.d.ts").NativeModules[K]>} */
const native = (path) =>
  import(pathToFileURL(`${root}/apps/prairielearn/dist/${path}.js`).href);
const [
  { config, loadConfig },
  enrollments,
  users,
  instances,
  { dangerousFullSystemAuthz },
] = await Promise.all([
  native("lib/config"),
  native("models/enrollment"),
  native("models/user"),
  native("models/course-instances"),
  native("lib/authz-data-lib"),
]);
const studentAccess = await native("lib/authz-data");
const coursePermissions = await native("models/course-permissions");
const settingsSchema = z.strictObject({
  administratorEmail: z
    .string()
    .refine(isCanonicalEmail)
    .nullable()
    .default(null),
  listenHost: z.string(),
  listenPort: z.number().int().min(1).max(65535),
  tokenFile: z.string(),
  bindings: z
    .array(
      z.strictObject({
        courseKey: z.string().regex(/^[a-z][a-z0-9-]*$/),
        instance: z.string().min(1),
        courseId: z.string().regex(/^[1-9][0-9]*$/),
        courseInstanceId: z.string().regex(/^[1-9][0-9]*$/),
        courseInstanceUuid: z.string().uuid(),
      }),
    )
    .min(1)
    .refine(
      (rows) =>
        new Set(rows.map((b) => JSON.stringify([b.courseKey, b.instance])))
          .size === rows.length,
      "Неоднозначная регистрация native курса и экземпляра",
    ),
});
const settings = settingsSchema.parse(
  /** @type {unknown} */ (
    JSON.parse(
      await readFile(
        /** @type {string} */ (process.env.PL_GATEWAY_CONFIG),
        "utf8",
      ),
    )
  ),
);
const token = (await readFile(settings.tokenFile, "utf8")).trim();
if (token.length < 32)
  throw new Error("Service token needs at least 32 characters");
const bindings = settings.bindings;
await loadConfig([`${root}/config.json`]);
assertProductionRuntime(process.env.NODE_ENV, config);
await db.initAsync(
  {
    user: config.postgresqlUser,
    database: config.postgresqlDatabase,
    host: config.postgresqlHost,
    password: config.postgresqlPassword ?? undefined,
    max: 4,
  },
  () => {
    process.exitCode = 1;
  },
);
await db.setRandomSearchSchemaAsync("gateway-bridge");
await (await native("sprocs/index")).init();
const sql = db.loadSqlEquiv(new URL("./native.mjs", import.meta.url).href);
const system = dangerousFullSystemAuthz();
/** @param {z.infer<typeof enrollmentQuerySchema>} request */
async function context(request) {
  const binding = bindings.find(
    (b) => b.courseKey === request.courseKey && b.instance === request.instance,
  );
  if (!binding)
    throw new BridgeError(403, "Неизвестный native курс или экземпляр");
  const ci = await instances.selectCourseInstanceById(binding.courseInstanceId);
  if (
    ci.deleted_at !== null ||
    ci.id !== binding.courseInstanceId ||
    ci.course_id !== binding.courseId ||
    ci.uuid !== binding.courseInstanceUuid ||
    ci.short_name !== binding.instance
  )
    throw new BridgeError(403, "Native экземпляр не соответствует регистрации");
  const user = await users.selectOptionalUserByUid(request.userUid);
  if (!user) throw new BridgeError(404, "Verified user must exist");
  return { ci, user };
}
const enrollmentQuerySchema = z.strictObject({
  userUid: z.string().min(1).max(512),
  instance: z.string().min(1),
  courseKey: z.string().regex(/^[a-z][a-z0-9-]*$/),
  role: z.enum(["student", "teacher"]),
  email: z.string().refine(isCanonicalEmail).nullable(),
});
/** @param {z.infer<typeof enrollmentQuerySchema>} request @param {import("../types/native-contracts.d.ts").BridgeCourseInstance} ci @param {import("../types/native-contracts.d.ts").NativeUser} user */
async function grantTrustedLoginRole(request, ci, user) {
  const administrator =
    settings.administratorEmail !== null &&
    request.email === settings.administratorEmail;
  if (administrator) {
    const answer = await db.queryRow(
      sql.grant_administrator,
      { uid: user.uid, user_id: user.id },
      z.object({ administrator: z.boolean() }),
    );
    if (!answer.administrator)
      throw new BridgeError(409, "Не удалось выдать native Administrator");
  }
  if (!administrator && request.role !== "teacher") return;
  const staffUser = await coursePermissions.insertCoursePermissionsByUserUid({
    course_id: ci.course_id,
    uid: user.uid,
    course_role: "Editor",
    authn_user_id: user.id,
  });
  if (staffUser.id !== user.id || staffUser.uid !== user.uid)
    throw new BridgeError(409, "Native identity изменилась при выдаче роли");
  await coursePermissions.insertCourseInstancePermissions({
    course_id: ci.course_id,
    course_instance_id: ci.id,
    user_id: user.id,
    course_instance_role: "Student Data Editor",
    authn_user_id: user.id,
  });
  const courseRole = await coursePermissions.selectCoursePermissionForUser({
    course_id: ci.course_id,
    user_id: user.id,
  });
  const instanceRole =
    await coursePermissions.selectCourseInstancePermissionForUser({
      course_instance_id: ci.id,
      user_id: user.id,
    });
  if (
    !["Editor", "Owner"].some((role) => role === courseRole) ||
    instanceRole !== "Student Data Editor"
  )
    throw new BridgeError(
      409,
      "Native преподавательские права не подтверждены",
    );
}
/** @param {z.infer<typeof enrollmentQuerySchema>} request */
async function enrollBasic(request) {
  const { ci, user } = await context(request);
  if (typeof ci.id !== "string" || !/^[1-9][0-9]*$/.test(ci.id))
    throw new BridgeError(409, "Invalid native instance identifier");
  return db.runInTransactionAsync(async () => {
    await db.execute(sql.lock, { lock_key: `gateway:${ci.id}:${user.uid}` });
    const prior = await enrollments.selectOptionalEnrollmentByUserId({
      userId: user.id,
      courseInstance: ci,
      authzData: system,
      requiredRole: ["System"],
    });
    if (prior?.status === "blocked")
      throw new BridgeError(403, "Blocked enrollment");
    const enrollment = await enrollments.ensureUncheckedEnrollment({
      userId: user.id,
      courseInstance: ci,
      authzData: system,
      requiredRole: ["System"],
      actionDetail: "implicit_joined",
    });
    if (!enrollment || enrollment.status !== "joined")
      throw new BridgeError(403, "Enrollment unavailable");
    await grantTrustedLoginRole(request, ci, user);
    const { authzData } = await studentAccess.constructCourseOrInstanceContext({
      user,
      course_id: ci.course_id,
      course_instance_id: ci.id,
      ip: null,
      req_date: new Date(),
      // Проверяем обычный native вход без предположения об активном admin mode cookie.
      is_administrator: false,
      // Это course/enrollment ACL, а не browser assessment context с известным IP.
      overrides: { mode: "Public" },
    });
    const hasStaffAccess =
      authzData?.has_course_permission_preview ||
      authzData?.has_course_instance_permission_view;
    if (
      !hasStaffAccess &&
      (!ci.modern_publishing || !authzData?.has_student_access_with_enrollment)
    )
      throw new BridgeError(403, "Native course instance access denied");
    return {
      schemaVersion: 1,
      userUid: user.uid,
      instance: request.instance,
      courseKey: request.courseKey,
      enrolled: true,
      path: `/pl/course_instance/${ci.id}/assessments`,
    };
  });
}
/** @template T @param {import("node:http").IncomingMessage} req @param {z.ZodType<T>} schema @returns {Promise<T>} */
async function readBody(req, schema) {
  let body = "";
  for await (const chunk of req) {
    body += chunk;
    if (Buffer.byteLength(body) > 8192)
      throw new BridgeError(413, "Body too large");
  }
  return schema.parse(/** @type {unknown} */ (JSON.parse(body)));
}
const server = createServer(async (req, res) => {
  try {
    const supplied = Buffer.from(req.headers.authorization ?? "");
    const expected = Buffer.from(`Bearer ${token}`);
    if (
      supplied.length !== expected.length ||
      !timingSafeEqual(supplied, expected)
    )
      throw new BridgeError(401, "Service authentication required");
    const url = new URL(/** @type {string} */ (req.url), "http://bridge");
    if (
      !(req.method === "PUT" && url.pathname === "/internal/gateway/enrollment")
    )
      throw new BridgeError(404, "Unknown route");
    if (/** @type {string} */ (req.url).includes("?"))
      throw new BridgeError(400, "Unexpected enrollment query");
    const answer = await enrollBasic(
      await readBody(req, enrollmentQuerySchema),
    );
    res
      .writeHead(200, {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      })
      .end(JSON.stringify(answer));
  } catch (error) {
    const status =
      error instanceof BridgeError
        ? error.status
        : error instanceof z.ZodError || error instanceof SyntaxError
          ? 400
          : 500;
    // Native ошибки не раскрывают приватные данные или учётные данные.
    res
      .writeHead(status, {
        "Content-Type": "application/json",
        "Cache-Control": "no-store",
      })
      .end(
        JSON.stringify({
          error:
            status === 500
              ? "Bridge operation failed"
              : /** @type {Error} */ (error).message,
        }),
      );
  }
});
server.listen(settings.listenPort, settings.listenHost, () =>
  console.log("Community gateway bridge ready"),
);
process.on("SIGTERM", () =>
  server.close(() => void db.closeAsync().then(() => process.exit(0))),
);
