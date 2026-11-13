/** One-off identity/access transfer. Never transfers results or student files. */
import { readFile, writeFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";
/** @typedef {{uid:string,name:string|null,email:string|null,uin:string|null,institution:string}} Profile */
/** @typedef {{uid:string,instanceId:string,status:string,isGuest:boolean}} Access */
/** @typedef {{uid:string,courseId:string,role:string}} CourseAccess */
/** @typedef {{uid:string,instanceId:string,role:string}} InstanceAccess */
/** @typedef {{id:string,courseId:string,coursePath:string,uuid:string|null}} Instance */
/** @typedef {{sourceInstanceId:string,sourceCourseId:string,targetInstanceId:string,targetCourseId:string}} Mapping */
/** @typedef {{schema:string,users:Profile[],administrators:string[],instances:Instance[],enrollments:Access[],coursePermissions:CourseAccess[],instancePermissions:InstanceAccess[]}} Snapshot */
/** @typedef {{users:Profile[],administrators:string[],mappings:Mapping[],enrollments:Access[],coursePermissions:CourseAccess[],instancePermissions:InstanceAccess[]}} Plan */
/** @param {unknown} v @param {string[]} fields @returns {v is Record<string,unknown>} */
function closed(v, fields) {
  return (
    !!v &&
    typeof v === "object" &&
    !Array.isArray(v) &&
    Object.keys(v).sort().join(",") === [...fields].sort().join(",")
  );
}
/** @param {unknown} v */
function text(v) {
  return typeof v === "string" && v.length > 0 && v.trim() === v;
}
/** @param {unknown} v */
function id(v) {
  return typeof v === "string" && /^[1-9][0-9]*$/.test(v);
}
/** @param {unknown} v @returns {asserts v is Snapshot} */
function validate(v) {
  if (
    !closed(v, [
      "schema",
      "users",
      "administrators",
      "instances",
      "enrollments",
      "coursePermissions",
      "instancePermissions",
    ]) ||
    v.schema !== "pl-users-v1"
  )
    throw new Error("Closed identity-only document required");
  for (const k of [
    "users",
    "administrators",
    "instances",
    "enrollments",
    "coursePermissions",
    "instancePermissions",
  ])
    if (!Array.isArray(v[k])) throw new Error("Invalid identity-only list");
  const s = /** @type {Snapshot} */ (/** @type {unknown} */ (v));
  const uids = new Set();
  for (const u of s.users) {
    if (
      !closed(u, ["uid", "name", "email", "uin", "institution"]) ||
      !text(u.uid) ||
      !text(u.institution) ||
      uids.has(u.uid) ||
      [u.name, u.email, u.uin].some((x) => x !== null && typeof x !== "string")
    )
      throw new Error("Invalid identity-only user");
    uids.add(u.uid);
  }
  for (const uid of s.administrators)
    if (!uids.has(uid)) throw new Error("Unknown administrator UID");
  const instances = new Set();
  for (const c of s.instances) {
    if (
      !closed(c, ["id", "courseId", "coursePath", "uuid"]) ||
      !id(c.id) ||
      !id(c.courseId) ||
      !text(c.coursePath) ||
      (c.uuid !== null && !text(c.uuid)) ||
      instances.has(c.id)
    )
      throw new Error("Invalid source instance");
    instances.add(c.id);
  }
  const courses = new Set(s.instances.map((c) => c.courseId));
  for (const e of s.enrollments)
    if (
      !closed(e, ["uid", "instanceId", "status", "isGuest"]) ||
      !text(e.uid) ||
      !instances.has(e.instanceId) ||
      !["joined", "blocked", "left", "removed", "invited", "rejected"].includes(
        e.status,
      ) ||
      typeof e.isGuest !== "boolean" ||
      (!uids.has(e.uid) && !["invited", "rejected"].includes(e.status))
    )
      throw new Error("Invalid identity-only enrollment");
  for (const p of s.coursePermissions)
    if (
      !closed(p, ["uid", "courseId", "role"]) ||
      !uids.has(p.uid) ||
      !courses.has(p.courseId) ||
      !["None", "Previewer", "Viewer", "Editor", "Owner"].includes(p.role)
    )
      throw new Error("Invalid course permission");
  for (const p of s.instancePermissions)
    if (
      !closed(p, ["uid", "instanceId", "role"]) ||
      !uids.has(p.uid) ||
      !instances.has(p.instanceId) ||
      !["None", "Student Data Viewer", "Student Data Editor"].includes(p.role)
    )
      throw new Error("Invalid instance permission");
}
/** @template T @param {T[]} rows @param {(row:T)=>string} key */
function deduplicate(rows, key) {
  const seen = new Map();
  for (const row of rows) {
    const k = key(row);
    if (seen.has(k) && JSON.stringify(seen.get(k)) !== JSON.stringify(row))
      throw new Error("Conflicting access after instance mapping");
    seen.set(k, row);
  }
  return [...seen.values()];
}
/** @param {unknown} snapshot @param {unknown} mapping @returns {Plan} */
export function planImport(snapshot, mapping) {
  validate(snapshot);
  if (!Array.isArray(mapping) || mapping.length !== snapshot.instances.length)
    throw new Error("Every source instance needs explicit mapping");
  const maps = /** @type {Mapping[]} */ (mapping),
    byInstance = new Map(),
    byCourse = new Map();
  for (const m of maps) {
    if (
      !closed(m, [
        "sourceInstanceId",
        "sourceCourseId",
        "targetInstanceId",
        "targetCourseId",
      ]) ||
      !Object.values(m).every(id) ||
      byInstance.has(m.sourceInstanceId)
    )
      throw new Error("Invalid explicit instance mapping");
    const c = snapshot.instances.find((c) => c.id === m.sourceInstanceId);
    if (!c || c.courseId !== m.sourceCourseId)
      throw new Error("Source instance parent mismatch");
    if (
      byCourse.has(c.courseId) &&
      byCourse.get(c.courseId) !== m.targetCourseId
    )
      throw new Error("Conflicting target course mapping");
    byCourse.set(c.courseId, m.targetCourseId);
    byInstance.set(c.id, m.targetInstanceId);
  }
  return {
    users: snapshot.users,
    administrators: [...new Set(snapshot.administrators)],
    mappings: maps,
    enrollments: deduplicate(
      snapshot.enrollments.map((e) => ({
        ...e,
        instanceId: byInstance.get(e.instanceId),
      })),
      (e) => JSON.stringify([e.uid, e.instanceId]),
    ),
    coursePermissions: deduplicate(
      snapshot.coursePermissions.map((p) => ({
        ...p,
        courseId: byCourse.get(p.courseId),
      })),
      (p) => JSON.stringify([p.uid, p.courseId]),
    ),
    instancePermissions: deduplicate(
      snapshot.instancePermissions.map((p) => ({
        ...p,
        instanceId: byInstance.get(p.instanceId),
      })),
      (p) => JSON.stringify([p.uid, p.instanceId]),
    ),
  };
}
/** @typedef {{transaction:(fn:()=>Promise<void>)=>Promise<void>,assertFresh:()=>Promise<void>,checkTargets:(m:Mapping[])=>Promise<void>,putUser:(u:Profile)=>Promise<void>,putAdministrator:(uid:string)=>Promise<void>,putEnrollment:(e:Access)=>Promise<void>,putCoursePermission:(p:CourseAccess)=>Promise<void>,putInstancePermission:(p:InstanceAccess)=>Promise<void>}} ImportApi */
/** @param {Plan} plan @param {ImportApi} api */
export async function applyImport(plan, api) {
  await api.transaction(async () => {
    await api.assertFresh();
    await api.checkTargets(plan.mappings);
    for (const u of plan.users) await api.putUser(u);
    for (const uid of plan.administrators) await api.putAdministrator(uid);
    for (const e of plan.enrollments) await api.putEnrollment(e);
    for (const p of plan.coursePermissions) await api.putCoursePermission(p);
    for (const p of plan.instancePermissions)
      await api.putInstancePermission(p);
  });
}
// Deliberately enumerated columns/relations; no SELECT *, generic table copy or results.
const exportSql = `SELECT json_build_object(
 'schema','pl-users-v1',
 'users',coalesce((SELECT json_agg(json_build_object('uid',u.uid,'name',u.name,'email',u.email,'uin',u.uin,'institution',i.short_name) ORDER BY u.id) FROM users u JOIN institutions i ON i.id=u.institution_id),'[]'::json),
 'administrators',coalesce((SELECT json_agg(u.uid ORDER BY u.id) FROM administrators a JOIN users u ON u.id=a.user_id),'[]'::json),
 'instances',coalesce((SELECT json_agg(json_build_object('id',ci.id::text,'courseId',c.id::text,'coursePath',c.path,'uuid',ci.uuid) ORDER BY ci.id) FROM course_instances ci JOIN courses c ON c.id=ci.course_id),'[]'::json),
 'enrollments',coalesce((SELECT json_agg(json_build_object('uid',coalesce(u.uid,e.pending_uid),'instanceId',e.course_instance_id::text,'status',e.status,'isGuest',e.is_guest) ORDER BY e.id) FROM enrollments e LEFT JOIN users u ON u.id=e.user_id),'[]'::json),
 'coursePermissions',coalesce((SELECT json_agg(json_build_object('uid',u.uid,'courseId',p.course_id::text,'role',p.course_role) ORDER BY p.id) FROM course_permissions p JOIN users u ON u.id=p.user_id),'[]'::json),
 'instancePermissions',coalesce((SELECT json_agg(json_build_object('uid',u.uid,'instanceId',p.course_instance_id::text,'role',p.course_instance_role) ORDER BY p.id) FROM course_instance_permissions p JOIN course_permissions cp ON cp.id=p.course_permission_id JOIN users u ON u.id=cp.user_id),'[]'::json)
)`;
const usage =
  "export --output PRIVATE_JSON | import --input PRIVATE_JSON --map MAP_JSON --actor-uid UID (fresh isolated target only)";
/** @param {string[]} args */
async function main(args) {
  const mode = args.shift();
  if (mode === "--help") {
    console.log(usage);
    return;
  }
  /** @type {Record<string,string>} */ const opts = {};
  for (let i = 0; i < args.length; i += 2) {
    if (
      !["--output", "--input", "--map", "--actor-uid"].includes(args[i]) ||
      !args[i + 1] ||
      Object.hasOwn(opts, args[i])
    )
      throw new Error(usage);
    opts[args[i]] = args[i + 1];
  }
  if (
    (mode !== "export" && mode !== "import") ||
    (mode === "export" && Object.keys(opts).sort().join(",") !== "--output") ||
    (mode === "import" &&
      Object.keys(opts).sort().join(",") !== "--actor-uid,--input,--map")
  )
    throw new Error(usage);
  const plan =
    mode === "import"
      ? planImport(
          JSON.parse(await readFile(opts["--input"], "utf8")),
          JSON.parse(await readFile(opts["--map"], "utf8")),
        )
      : null;
  const root = process.env.PL_ROOT ?? "/PrairieLearn";
  const native = (/** @type {string} */ p) =>
    import(pathToFileURL(`${root}/apps/prairielearn/dist/${p}.js`).href);
  const [{ config, loadConfig }, db, { z }] = await Promise.all([
    native("lib/config"),
    import("@prairielearn/postgres"),
    import("zod"),
  ]);
  await loadConfig([root + "/config.json"]);
  await db.initAsync(
    {
      user: config.postgresqlUser,
      database: config.postgresqlDatabase,
      host: config.postgresqlHost,
      password: config.postgresqlPassword ?? undefined,
      max: 1,
    },
    () => {
      process.exitCode = 1;
    },
  );
  try {
    if (mode === "export") {
      const snapshot = await db.runInTransactionAsync(async () => {
        await db.execute(
          "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY",
        );
        await db.execute("SET LOCAL statement_timeout = '10s'");
        if (
          await db.queryScalar(
            "SELECT EXISTS(SELECT 1 FROM enrollments WHERE (user_id IS NULL AND pending_uid IS NULL) OR pending_lti13_sub IS NOT NULL OR pending_uin IS NOT NULL OR pending_lti13_course_instance_id IS NOT NULL)",
            z.boolean(),
          )
        )
          throw new Error("Unsupported pending identity; export stopped");
        return await db.queryScalar(exportSql, z.unknown());
      });
      validate(snapshot);
      await writeFile(
        opts["--output"],
        JSON.stringify(snapshot, null, 2) + "\n",
        { mode: 0o600, flag: "wx" },
      );
      console.log(
        JSON.stringify({
          users: snapshot.users.length,
          administrators: snapshot.administrators.length,
          enrollments: snapshot.enrollments.length,
        }),
      );
      return;
    }
    if (!plan) throw new Error(usage);
    await (await native("sprocs/index")).init();
    const [
      users,
      enrollments,
      instances,
      permissions,
      { dangerousFullSystemAuthz },
    ] = await Promise.all([
      native("models/user"),
      native("models/enrollment"),
      native("models/course-instances"),
      native("models/course-permissions"),
      native("lib/authz-data-lib"),
    ]);
    const actor = await users.selectOptionalUserByUid(opts["--actor-uid"]);
    if (
      !actor ||
      !(await db.queryScalar(
        "SELECT EXISTS(SELECT 1 FROM administrators WHERE user_id=$id)",
        { id: actor.id },
        z.boolean(),
      ))
    )
      throw new Error("Existing native administrator required");
    const authzData = dangerousFullSystemAuthz(),
      requiredRole = ["System"];
    /** @type {Map<string,Awaited<ReturnType<typeof instances.selectCourseInstanceById>>>} */ const targetInstances =
      new Map();
    /** @param {string} uid */ const user = async (uid) => {
      const u = await users.selectOptionalUserByUid(uid);
      if (!u || u.uid !== uid) throw new Error("Exact UID lookup failed");
      return u;
    };
    await applyImport(plan, {
      transaction: (fn) => db.runInTransactionAsync(fn),
      async assertFresh() {
        const fresh = await db.queryScalar(
          `SELECT NOT EXISTS(SELECT 1 FROM users WHERE id<>$actor) AND NOT EXISTS(SELECT 1 FROM administrators WHERE user_id<>$actor) AND NOT EXISTS(SELECT 1 FROM enrollments) AND NOT EXISTS(SELECT 1 FROM course_permissions) AND NOT EXISTS(SELECT 1 FROM course_instance_permissions) AND NOT EXISTS(SELECT 1 FROM assessment_instances) AND NOT EXISTS(SELECT 1 FROM variants) AND NOT EXISTS(SELECT 1 FROM submissions) AND NOT EXISTS(SELECT 1 FROM grading_jobs)`,
          { actor: actor.id },
          z.boolean(),
        );
        if (!fresh) throw new Error("Target is not fresh: no import performed");
        if (!plan.administrators.includes(actor.uid))
          throw new Error("Bootstrap UID must be a source administrator");
      },
      async checkTargets(maps) {
        for (const m of maps) {
          const ci = await instances.selectCourseInstanceById(
            m.targetInstanceId,
          );
          if (ci.course_id !== m.targetCourseId || ci.deleted_at !== null)
            throw new Error("Target instance parent mismatch");
          targetInstances.set(ci.id, ci);
        }
        for (const u of plan.users) {
          const count = await db.queryScalar(
            "SELECT count(*)::int FROM institutions WHERE short_name=$name",
            { name: u.institution },
            z.number(),
          );
          if (count !== 1)
            throw new Error("User institution missing or ambiguous");
        }
      },
      async putUser(u) {
        const created = await users.selectOrInsertUserByUid(u.uid);
        if (created.uid !== u.uid) throw new Error("Native UID changed");
        await db.execute(
          "UPDATE users SET name=$name,email=$email,uin=$uin,institution_id=(SELECT id FROM institutions WHERE short_name=$institution) WHERE id=$id AND uid=$uid",
          { ...u, id: created.id },
        );
      },
      async putAdministrator(uid) {
        const u = await user(uid);
        await db.execute(
          "INSERT INTO administrators(user_id) VALUES($id) ON CONFLICT(user_id) DO NOTHING",
          { id: u.id },
        );
      },
      async putEnrollment(e) {
        const courseInstance = targetInstances.get(e.instanceId);
        let enrollment;
        if (["invited", "rejected"].includes(e.status)) {
          enrollment = await enrollments.inviteStudentByUid({
            uid: e.uid,
            courseInstance,
            authzData,
            requiredRole,
          });
          if (e.status === "rejected")
            enrollment = await enrollments.setEnrollmentStatus({
              enrollment,
              status: "rejected",
              authzData,
              requiredRole,
            });
        } else {
          const u = await user(e.uid);
          enrollment = await enrollments.ensureUncheckedEnrollment({
            userId: u.id,
            courseInstance,
            authzData,
            requiredRole,
            actionDetail: "implicit_joined",
          });
          if (e.status !== "joined")
            enrollment = await enrollments.setEnrollmentStatus({
              enrollment,
              status: e.status,
              authzData,
              requiredRole,
            });
        }
        if (!enrollment || enrollment.status !== e.status)
          throw new Error("Enrollment status mismatch");
        await db.execute(
          "UPDATE enrollments SET is_guest=$guest WHERE id=$id",
          { guest: e.isGuest, id: enrollment.id },
        );
      },
      async putCoursePermission(p) {
        await permissions.insertCoursePermissionsByUserUid({
          course_id: p.courseId,
          uid: p.uid,
          course_role: p.role,
          authn_user_id: actor.id,
        });
      },
      async putInstancePermission(p) {
        const u = await user(p.uid),
          ci = targetInstances.get(p.instanceId);
        await permissions.insertCourseInstancePermissions({
          course_id: ci.course_id,
          course_instance_id: ci.id,
          user_id: u.id,
          course_instance_role: p.role,
          authn_user_id: actor.id,
        });
      },
    });
    console.log(
      JSON.stringify({
        users: plan.users.length,
        administrators: plan.administrators.length,
        enrollments: plan.enrollments.length,
        coursePermissions: plan.coursePermissions.length,
        instancePermissions: plan.instancePermissions.length,
      }),
    );
  } finally {
    await db.closeAsync();
  }
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href)
  main(process.argv.slice(2)).catch(() => {
    console.error(
      "Identity-only transfer failed; inspect configuration privately. No row data logged.",
    );
    process.exitCode = 1;
  });
