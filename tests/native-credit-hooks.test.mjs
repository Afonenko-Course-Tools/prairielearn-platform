// Реальные pinned upstream функции; только SQL/metrics I/O заменены fixture.
// Это проверка source control-flow hooks, не PostgreSQL/runtime qualification.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stripTypeScriptTypes } from "node:module";
import vm from "node:vm";
import { test } from "node:test";
import { pathToFileURL } from "node:url";
const old = process.argv.includes("--old"),
  dist = process.argv.includes("--dist");
const base = old
  ? new URL("./fixtures/native-credit-upstream/", import.meta.url)
  : pathToFileURL(
      /** @type {string} */ (
        process.argv.find((v) => v.startsWith("--fixture-root="))
      ).slice("--fixture-root=".length) + "/",
    );
/** @type {import("../types/test-contracts.d.ts").SchemaProxy} */
const schema =
  /** @type {import("../types/test-contracts.d.ts").SchemaProxy} */ (
    new Proxy(
      function () {
        return schema;
      },
      { get: () => schema, apply: () => schema },
    )
  );
/** @param {string} kind */
function source(kind) {
  let text = readFileSync(
    new URL(
      (dist ? "dist/" : "") +
        (kind === "grading-job" ? "models/grading-job" : "lib/" + kind) +
        (dist ? ".js" : ".ts"),
      base,
    ),
    "utf8",
  );
  return (dist ? text : stripTypeScriptTypes(text, { mode: "strip" }))
    .replace(/^import[\s\S]*?from ['"][^'"]+['"];\s*/gm, "")
    .replace(/\bexport (?=(?:async )?function|const|class)/g, "")
    .replaceAll("import.meta.url", JSON.stringify(base.href));
}
function fixture() {
  /** @type {import("../types/test-contracts.d.ts").HookState} */
  const s = {
    points: 100,
    manual: 20,
    status: "complete",
    pending: false,
    recognized: true,
    answer: null,
    job: {
      id: "70",
      submission_id: "60",
      grading_request_canceled_at: null,
      graded_at: null,
      auth_user_id: "99",
      score: 0,
    },
    ai: {
      id: "25",
      max_points: 100,
      max_bonus_points: 0,
      points: 0,
      score_perc: 0,
    },
    guardCalls: 0,
  };
  const row = async (
    /** @type {string} */ q,
    /** @type {Record<string,unknown>} */ p,
  ) => {
    if (q === "update_variant_true_answer")
      return {
        user_id: "16",
        team_id: null,
        open: true,
        instance_question_open: true,
        assessment_instance_open: true,
        instance_question_id: "26",
        assessment_instance_id: "25",
        max_manual_points: 20,
        broken_at: null,
      };
    if (q === "update_instance_question_post_submission") {
      s.status = p.status;
      s.pending = p.requires_manual_grading;
      return { id: "26" };
    }
    if (q === "select_and_lock_assessment_instance") return s.ai;
    if (q === "insert_grading_job") {
      s.status = "grading";
      return { ...s.job, assessment_instance_id: "25", credit: 100 };
    }
    if (q === "select_grading_job") return { ...s.job };
    if (q === "select_variant_for_grading_job_update")
      return {
        has_newer_submission: false,
        instance_question_id: "26",
        assessment_instance_id: "25",
        variant_id: "50",
        credit: 100,
      };
    if (q === "update_grading_job_after_grading") {
      s.job = { ...s.job, ...p };
      if (!p.gradable) s.status = "invalid";
      return { ...s.job };
    }
    throw Error("unexpected native fixture query " + q);
  };
  /** @type {Record<string,unknown>} */
  const ctx = {
    console,
    z: schema,
    IdSchema: schema,
    IntervalSchema: schema,
    VariantSchema: schema,
    QuestionSchema: schema,
    SubmissionSchema: schema,
    InstanceQuestionSchema: schema,
    AssessmentQuestionSchema: schema,
    GradingJobSchema: schema,
    AssessmentInstanceSchema: schema,
    queryRow: row,
    queryOptionalScalar: async () => 50,
    queryRows: async () => [
      {
        zone_id: "1",
        points: s.points,
        iq_ids: ["26"],
        max_points: 100,
        max_iq_ids: ["26"],
      },
    ],
    execute: async (
      /** @type {string} */ q,
      /** @type {Record<string,unknown>} */ p,
    ) => {
      if (q === "update_assessment_instance_grade")
        Object.assign(s.ai, { points: p.points, score_perc: p.score_perc });
      else throw Error("unexpected execute " + q);
    },
    /** @template T @param {()=>Promise<T>} f */
    runInTransactionAsync: async (f) => f(),
    loadSqlEquiv: () => new Proxy({}, { get: (_, k) => k }),
    lockVariant: async () => {},
    lockSubmission: async () => {},
    updateCourseInstanceUsagesForSubmission: async () => {},
    updateInstanceQuestionStats: async () => {},
    applyRecognizedCredit: async () => {
      s.guardCalls++;
      if (!s.recognized) return 0;
      s.points = 100;
      s.manual = 20;
      s.status = "complete";
      s.pending = false;
      return 1;
    },
    updateInstanceQuestionGrade: async () => {
      s.points = 20;
      s.status = "complete";
    },
  };
  ctx.sqldb = {
    ...ctx,
    queryOptionalScalar: async () => 0,
    queryScalar: async (
      /** @type {string} */ q,
      /** @type {Record<string,unknown>} */ p,
    ) => {
      assert.equal(q, "insert_submission");
      s.answer = p.raw_submitted_answer;
      return "60";
    },
  };
  return { s, ctx };
}
/** @param {string} kind @param {Record<string,unknown>} ctx @param {string} entry @returns {(args:Record<string,unknown>)=>Promise<Record<string,unknown>>} */
function load(kind, ctx, entry) {
  const c = vm.createContext({ ...ctx });
  new vm.Script(
    source(kind) + "\nglobalThis.entry=" + entry + ";",
  ).runInContext(c);
  return c.entry;
}
/** @param {import("../types/test-contracts.d.ts").HookState} s */
function full(s) {
  assert.equal(s.points, 100);
  assert.equal(s.status, "complete");
  assert.equal(s.pending, false);
}
test("real insertSubmission entrypoint preserves new raw failed answer and recognized complete state", async () => {
  const { s, ctx } = fixture();
  const entry = load("grading", ctx, "insertSubmission");
  await entry({
    variant_id: "50",
    user_id: "16",
    auth_user_id: "16",
    raw_submitted_answer: { answer: "new failed bytes" },
    submitted_answer: { answer: "new failed bytes" },
    gradable: true,
    broken: false,
  });
  full(s);
  assert.ok(s.answer && typeof s.answer === "object" && "answer" in s.answer);
  assert.equal(s.answer.answer, "new failed bytes");
});
test("real aggregate recompute discards stale precomputed points only for recognized IQs", async () => {
  const { s, ctx } = fixture();
  s.points = 0;
  s.status = "saved";
  s.pending = true;
  const entry = load(
    "assessment-grading",
    ctx,
    "updateAssessmentInstanceGrade",
  );
  const r = await entry({
    assessment_instance_id: "25",
    authn_user_id: "99",
    precomputedPointsByZone: [{ points: 0, iq_ids: ["26"] }],
  });
  full(s);
  assert.equal(r.points, 100);
  assert.equal(r.score_perc, 100);
  assert.equal(s.ai.score_perc, 100);
});
test("real grading request cannot leave a recognized IQ pending/grading", async () => {
  const { s, ctx } = fixture();
  ctx.updateAssessmentInstanceGrade = load(
    "assessment-grading",
    ctx,
    "updateAssessmentInstanceGrade",
  );
  const entry = load("grading-job", ctx, "insertGradingJob");
  await entry({ submission_id: "60", authn_user_id: "16" });
  full(s);
});
test("real failed grading completion preserves score0/new job while recognized IQ stays full", async () => {
  const { s, ctx } = fixture();
  ctx.updateAssessmentInstanceGrade = load(
    "assessment-grading",
    ctx,
    "updateAssessmentInstanceGrade",
  );
  const entry = load("grading-job", ctx, "updateGradingJobAfterGrading");
  const job = await entry({
    grading_job_id: "70",
    gradable: true,
    broken: false,
    score: 0,
    submitted_answer: { answer: "failed" },
  });
  full(s);
  assert.equal(job.score, 0);
});
test("real ungradable completion preserves invalid new job without leaving recognized IQ invalid", async () => {
  const { s, ctx } = fixture();
  ctx.updateAssessmentInstanceGrade = load(
    "assessment-grading",
    ctx,
    "updateAssessmentInstanceGrade",
  );
  const entry = load("grading-job", ctx, "updateGradingJobAfterGrading");
  const job = await entry({
    grading_job_id: "70",
    gradable: false,
    broken: true,
    score: 0,
  });
  full(s);
  assert.equal(job.score, null);
  assert.equal(job.gradable, false);
});
