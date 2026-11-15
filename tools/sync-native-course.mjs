import { readNativeCoursePayload } from "./native-course-payload.mjs";
/** Локальная операция администратора: sync ровно одной immutable поставки. */
import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import {
  authorizeCourseSync,
  verifyNativeAdministrator,
  readDeclaredInstances,
  validateNativeInstances,
} from "./course-sync-policy.mjs";
import { assertProductionRuntime } from "../bridge/policy.mjs";
import {
  selectRegistryCourse,
  resolveInstitution,
} from "./institution-bootstrap.mjs";
const root = process.env.PL_ROOT ?? "/PrairieLearn";
/** @template {keyof import("../types/native-contracts.d.ts").NativeModules} K @param {K} path @returns {Promise<import("../types/native-contracts.d.ts").NativeModules[K]>} */
const native = (path) =>
  import(pathToFileURL(`${root}/apps/prairielearn/dist/${path}.js`).href);
const usage =
  "Use --course-id ID --path /course/ID/CURRENT --actor-uid UID [--registry PATH --course-key KEY --institutions PATH]";
const args = process.argv.slice(2);
if (args.length === 1 && args[0] === "--help") {
  console.log(usage);
  process.exit(0);
}
if (
  args.length < 4 ||
  args[0] !== "--course-id" ||
  !/^[1-9][0-9]*$/.test(args[1]) ||
  args[2] !== "--path"
)
  throw new Error(usage);
const id = args[1],
  path = args[3];
/** @type {Record<string,string>} */
const options = {};
for (let i = 4; i < args.length; i += 2) {
  if (
    !["--registry", "--course-key", "--institutions", "--actor-uid"].includes(
      args[i],
    ) ||
    !args[i + 1] ||
    Object.hasOwn(options, args[i])
  )
    throw new Error("Invalid registry sync options");
  options[args[i]] = args[i + 1];
}
if (
  !options["--actor-uid"]?.trim() ||
  options["--actor-uid"].trim() !== options["--actor-uid"]
)
  throw new Error(usage);
if (
  Boolean(options["--registry"]) !== Boolean(options["--course-key"]) ||
  (options["--institutions"] && !options["--registry"])
)
  throw new Error("Registry and course key must be supplied together");
/** @type {unknown} */
const catalog = options["--registry"]
  ? JSON.parse(
      await readFile(
        options["--institutions"] ??
          new URL("../config/institutions.json", import.meta.url),
        "utf8",
      ),
    )
  : null;
const record = options["--registry"]
  ? selectRegistryCourse(
      JSON.parse(await readFile(options["--registry"], "utf8")),
      options["--course-key"],
      catalog,
    )
  : null;
if (record && !path.startsWith("/course/" + record.id + "/"))
  throw new Error("Registry course path mismatch");
const { delivery, info } = await readNativeCoursePayload(path);
authorizeCourseSync({
  path,
  sourceCourseId: delivery.courseId,
  courseUuid: null,
  infoUuid: /** @type {Record<string,unknown>} */ (info).uuid,
});
if (record && record.id !== delivery.courseId)
  throw new Error("Registry source course ID mismatch");
const declared = await readDeclaredInstances(path, delivery);
const db = await import("@prairielearn/postgres");
const namedLocks = await import("@prairielearn/named-locks");
const { z } = await import("zod");
const { config, loadConfig } = await native("lib/config");
await loadConfig([root + "/config.json"]);
assertProductionRuntime(process.env.NODE_ENV, config);
const pg = {
  user: config.postgresqlUser,
  database: config.postgresqlDatabase,
  host: config.postgresqlHost,
  password: config.postgresqlPassword ?? undefined,
  max: 4,
};
await db.initAsync(pg, () => {
  process.exitCode = 1;
});
await namedLocks.init(pg, () => {
  process.exitCode = 1;
});
try {
  await db.setRandomSearchSchemaAsync("local-course-sync");
  await (await native("sprocs/index")).init();
  const courses = await native("models/course");
  let course = await courses.selectCourseById(id);
  /** @type {unknown} */
  const previousDelivery = JSON.parse(
    await readFile(course.path + "/delivery.json", "utf8"),
  );
  /** @type {unknown} */
  const previousInfo = JSON.parse(
    await readFile(course.path + "/infoCourse.json", "utf8"),
  );
  authorizeCourseSync({
    path,
    sourceCourseId: delivery.courseId,
    previousSourceCourseId: /** @type {Record<string,unknown>} */ (
      previousDelivery
    ).courseId,
    courseUuid: /** @type {{uuid:unknown}} */ (previousInfo).uuid,
    infoUuid: /** @type {Record<string,unknown>} */ (info).uuid,
  });
  const actor = await verifyNativeAdministrator(options["--actor-uid"], {
    ...(await native("models/user")),
    isAdministrator: /** @param {string} id */ (id) =>
      db.queryScalar(
        "SELECT EXISTS(SELECT 1 FROM administrators WHERE user_id=$id)",
        { id },
        z.boolean(),
      ),
  });
  const instanceSchema = z.object({
    id: z.string(),
    course_id: z.string(),
    uuid: z.string().nullable(),
    short_name: z.string(),
    deleted_at: z.unknown(),
  });
  const existingInstances = await db.queryRows(
    "SELECT id::text,course_id::text,uuid,short_name,deleted_at FROM course_instances WHERE course_id=$id",
    { id },
    instanceSchema,
  );
  validateNativeInstances(id, declared, existingInstances);
  if (record) {
    const institutions = await native("models/institution");
    const institutionId = await resolveInstitution(
      catalog,
      record.institution,
      {
        ...institutions,
        withLock:
          /** @template T @param {string} name @param {() => Promise<T>} fn */ (
            name,
            fn,
          ) => namedLocks.doWithLock(name, { timeout: 30000 }, fn),
      },
    );
    if (course.institution_id !== institutionId)
      throw new Error(
        "Native course institution mismatch; migration is not supported",
      );
  }
  if (course.path !== path)
    course = await courses.updateCourseColumn({
      courseId: id,
      columnName: "path",
      value: path,
      authnUserId: actor.id,
    });
  const logger = {
    info: /** @param {unknown} message */ (message) =>
      process.stderr.write(String(message) + "\n"),
    verbose: () => {},
    error: /** @param {unknown} message */ (message) =>
      process.stderr.write(String(message) + "\n"),
  };
  const result = await (
    await native("sync/syncFromDisk")
  ).syncDiskToSql(course, logger);
  if (
    result.status !== "complete" ||
    result.hadJsonErrors ||
    result.hadJsonErrorsOrWarnings
  )
    throw new Error("Native sync reported errors/warnings");
  const instances = await db.queryRows(
    "SELECT id::text,course_id::text,uuid,short_name,deleted_at FROM course_instances WHERE course_id=$id AND deleted_at IS NULL",
    { id },
    instanceSchema,
  );
  validateNativeInstances(id, declared, instances, true);
  process.stdout.write(
    JSON.stringify({ courseId: id, path, instances }) + "\n",
  );
} finally {
  await namedLocks.close();
  await db.closeAsync();
}
