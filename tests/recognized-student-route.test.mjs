// Настоящие pinned middleware/route functions, только DB/authz/file I/O fixtures.
// Это source-контроль ветвей; настоящий HTTP/native authz sproc ещё не запускался.
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import { Readable, Writable } from "node:stream";
import { pipeline } from "node:stream/promises";
import vm from "node:vm";
import { z } from "zod";
const base = new URL(
  "./fixtures/native-credit-upstream/dist/",
  import.meta.url,
);
class HttpStatusError extends Error {
  /** @param {number} status @param {string} message */
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
/** @param {string} s */
function clean(s) {
  return s
    .replace(/^import[\s\S]*?;\n/gm, "")
    .replaceAll("export function", "function")
    .replace("export default asyncHandler", "const defaultHandler=asyncHandler")
    .replace("export default router;", "")
    .replaceAll("import.meta.url", JSON.stringify(base.href));
}
const authSource = clean(
    await readFile(
      new URL("middlewares/selectAndAuthzAssessmentInstance.js", base),
      "utf8",
    ),
  ),
  accessSource = clean(
    await readFile(
      new URL("middlewares/studentAssessmentAccess.js", base),
      "utf8",
    ),
  ),
  routeSource = clean(
    await readFile(
      new URL(
        "pages/studentAssessmentInstanceFile/studentAssessmentInstanceFile.js",
        base,
      ),
      "utf8",
    ),
  );
async function fixture({
  authorized = true,
  notes = true,
  showClosed = true,
  open = false,
  fileAI = "25",
  deleted = false,
  fileName = "recognized-private.java",
} = {}) {
  let streams = 0,
    status = 200;
  /** @type {Buffer[]} */
  const body = [];
  const file = {
    id: "31",
    assessment_instance_id: fileAI,
    display_filename: fileName,
    type: "student_upload",
    deleted_at: deleted ? "2026-11-02" : null,
  };
  const req = {
    method: "GET",
    params: {
      assessment_instance_id: "25",
      unsafe_file_id: "31",
      unsafe_display_filename: "recognized-private.java",
    },
    query: {},
    cookies: {},
  };
  const res =
    /** @type {import("../types/test-contracts.d.ts").RouteResponse} */ (
      new Writable({
        write(chunk, _e, done) {
          body.push(Buffer.from(chunk));
          done();
        },
      })
    );
  res.locals = {
    course_instance: { id: "21", display_timezone: "UTC" },
    authz_data: { user: { id: authorized ? "16" : "17" } },
    req_date: new Date(),
  };
  res.attachment = (name) => {
    res.filename = name;
  };
  res.status = (n) => {
    status = n;
    return res;
  };
  res.send = () => {};
  const schemas = Object.fromEntries(
    [
      "AssessmentInstanceSchema",
      "AssessmentSchema",
      "AssessmentSetSchema",
      "FileSchema",
      "GroupSchema",
      "SprocAuthzAssessmentInstanceSchema",
      "SprocUsersGetDisplayedRoleSchema",
      "UserSchema",
    ].map((k) => [k, z.unknown()]),
  );
  const auth = vm.createContext({
    z,
    ...schemas,
    asyncHandler: /** @template T @param {T} f */ (f) => f,
    error: { HttpStatusError },
    formatLegacyAssessmentInstanceAccess: /** @template T @param {T} v */ (v) =>
      v,
    resolveModernAssessmentInstanceAccess: async () => ({ authorized }),
    assessmentLabel: () => "",
    assessmentInstanceLabel: () => "",
    getAssessmentInstanceTimeLimit: () => ({}),
    sqldb: {
      loadSqlEquiv: () => ({ select_and_auth: "select_and_auth" }),
      queryOptionalRow: async (
        /** @type {string} */ _q,
        /** @type {{assessment_instance_id:string,course_instance_id:string,authz_data:{user:{id:string}}}} */ p,
      ) => {
        assert.equal(p.assessment_instance_id, "25");
        assert.equal(p.course_instance_id, "21");
        assert.equal(p.authz_data.user.id, authorized ? "16" : "17");
        return {
          assessment_instance: { id: "25", open },
          assessment: {
            id: "24",
            modern_access_control: false,
            allow_personal_notes: notes,
          },
          authz_result: {
            authorized,
            show_closed_assessment: showClosed,
            active: true,
          },
          assessment_set: {},
        };
      },
    },
  });
  new vm.Script(
    authSource + "\nglobalThis.entry=selectAndAuthzAssessmentInstance;",
  ).runInContext(auth);
  const access = vm.createContext({
    HttpStatusError,
    asyncHandler: /** @template T @param {T} f */ (f) => f,
    StudentAssessmentAccess: () => "",
    canDeleteAssessmentInstance: () => false,
    config: { secretKey: "fictional" },
    getCheckedSignedTokenData: () => null,
    logger: { verbose: () => {} },
    setCookie: () => {},
    flash: () => {},
    deleteAssessmentInstance: () => {
      throw Error("Unexpected lifecycle mutation");
    },
  });
  new vm.Script(
    accessSource + "\nglobalThis.entry=checkStudentAssessmentAccess;",
  ).runInContext(access);
  /** @type {import("../types/test-contracts.d.ts").Middleware[]|undefined} */
  let handlers;
  const route = vm.createContext({
    HttpStatusError,
    pipeline,
    loadSqlEquiv: () => ({ select_file: "select_file" }),
    FileSchema: z.unknown(),
    Router: () => ({
      /** @param {string} _path @param {import('../types/test-contracts.d.ts').Middleware[]} chain */
      get(_path, ...chain) {
        handlers = chain;
      },
    }),
    selectAndAuthzAssessmentInstance: auth.entry,
    studentAssessmentAccess: access.entry,
    clientFingerprint: () => {},
    logPageView: () => () => {},
    typedAsyncHandler: /** @template T @param {T} f */ (f) => f,
    queryOptionalRow: async (
      /** @type {string} */ _q,
      /** @type {{assessment_instance_id:string,unsafe_file_id:string,unsafe_display_filename:string}} */ p,
    ) =>
      p.assessment_instance_id === file.assessment_instance_id &&
      p.unsafe_file_id === file.id &&
      p.unsafe_display_filename === file.display_filename &&
      file.deleted_at === null
        ? file
        : null,
    fileStore: {
      getStream: async (/** @type {string} */ id) => {
        assert.equal(id, "31");
        streams++;
        return Readable.from([Buffer.from("private owned bytes")]);
      },
    },
  });
  new vm.Script(routeSource).runInContext(route);
  assert.ok(handlers);
  const boundHandlers = handlers;
  assert.equal(boundHandlers[0], auth.entry);
  assert.equal(boundHandlers[1], access.entry);
  return {
    run: async () => {
      await auth.entry(req, res);
      if (!access.entry(req, res)) return;
      const finalHandler = boundHandlers.at(-1);
      assert.ok(finalHandler);
      await finalHandler(req, res);
    },
    get streams() {
      return streams;
    },
    get status() {
      return status;
    },
    get bytes() {
      return Buffer.concat(body);
    },
  };
}
test("real closed-assessment route with permitted personal notes returns complete owned private bytes", async () => {
  const f = await fixture();
  await f.run();
  assert.equal(f.streams, 1);
  assert.equal(f.bytes.toString(), "private owned bytes");
});
test("real native authorization false (other UID) stops before private storage stream", async () => {
  const f = await fixture({ authorized: false });
  await assert.rejects(
    f.run(),
    (e) => e instanceof HttpStatusError && e.status === 403,
  );
  assert.equal(f.streams, 0);
});
test("real file handler refuses wrong AI/name/deleted file or missing personal-notes permission", async () => {
  for (const [
    change,
    status,
  ] of /** @type {Array<[Parameters<typeof fixture>[0],number]>} */ ([
    [{ fileAI: "777" }, 404],
    [{ fileName: "other.java" }, 404],
    [{ deleted: true }, 404],
    [{ notes: false }, 403],
  ])) {
    const f = await fixture(change);
    await assert.rejects(
      f.run(),
      (e) => e instanceof HttpStatusError && e.status === status,
    );
    assert.equal(f.streams, 0);
  }
});
test("real student-access middleware enforces closed-assessment visibility before file handler", async () => {
  const f = await fixture({ showClosed: false });
  await f.run();
  assert.equal(f.status, 403);
  assert.equal(f.streams, 0);
});
