import assert from "node:assert/strict";
import test from "node:test";
import { bridgeDeliverySchema } from "../../bridge/delivery.mjs";
const q = "demo/exr-a",
  slot = "demo/lab/exr-a";
/** @returns {import("../../types/test-contracts.d.ts").MutableDelivery} */
const fixture = () => ({
  schemaVersion: 5,
  courseId: "demo",
  bookRoot: "tasks",
  questions: [q],
  gradingPayloads: {
    [q]: {
      kind: "project",
      uuid: "37d79ee7-fd7d-44db-bd45-6587711862a5",
      grading: { method: "manual" },
      submission: { mode: "upload" },
      sourceRoot: "projects/a",
    },
  },
  works: [
    {
      id: "lab",
      slots: [
        {
          id: slot,
          selection: "fixed",
          candidates: [q],
          assignment: { requirement: "required", workMode: "individual" },
        },
      ],
      policy: {},
      completion: {
        schemaVersion: 2,
        mode: "required-slot-completion",
        source: "per-slot-results-v2",
        slotIds: [slot],
        requiredSlotIds: [slot],
        atLeast: 1,
        fullyCompletedScore: 1,
      },
    },
  ],
  instances: { fixture: { works: ["lab"], selfEnrollment: false } },
  files: ["infoCourse.json"],
});
test("v3 reader requires explicit canonical grading/submission for exact question catalog", () => {
  assert.equal(
    bridgeDeliverySchema.parse(fixture()).gradingPayloads[q].grading.method,
    "manual",
  );
  for (const change of /** @type {Array<(d:import("../../types/test-contracts.d.ts").MutableDelivery)=>unknown>} */ ([
    (d) => (d.schemaVersion = 2),
    (d) => delete d.gradingPayloads[q].grading,
    (d) => delete d.gradingPayloads[q].submission,
    (d) => (d.gradingPayloads[q].runtime = "fake"),
    (d) => delete d.gradingPayloads[q],
    (d) => (d.gradingPayloads["demo/exr-extra"] = d.gradingPayloads[q]),
  ])) {
    const d = fixture();
    change(d);
    assert.throws(() => bridgeDeliverySchema.parse(d));
  }
});
test("ручная проверка проекта принимает editor и upload с закрытым DTO", () => {
  for (const submission of [
    { mode: "editor", aceMode: "ace/mode/java" },
    { mode: "upload", layout: "zip" },
  ]) {
    const d = fixture();
    d.gradingPayloads[q].submission = submission;
    assert.deepEqual(
      bridgeDeliverySchema.parse(d).gradingPayloads[q],
      d.gradingPayloads[q],
    );
    for (const extra of [
      { runtime: "java" },
      { projectCheck: "check" },
      {
        sources: [
          {
            projectRelativePath: "Main.java",
            submissionRelativePath: "Main.java",
          },
        ],
      },
      { upstreamGradingMethod: "Manual" },
      { trusted: true },
    ]) {
      const changed = structuredClone(d);
      Object.assign(changed.gradingPayloads[q], extra);
      assert.throws(() => bridgeDeliverySchema.parse(changed));
    }
  }
  for (const submission of [
    { mode: "editor", layout: "zip" },
    { mode: "upload", aceMode: "ace/mode/java" },
    { mode: "editor", aceMode: "java" },
    { mode: "upload", layout: "tar" },
    { mode: "workspace" },
    { mode: "editor", trusted: true },
  ]) {
    const d = fixture();
    d.gradingPayloads[q].submission = submission;
    assert.throws(() => bridgeDeliverySchema.parse(d));
  }
});
test("v3 choice has a required canonical pool and safe owner relative roots", () => {
  const d = fixture(),
    b = "demo/exr-b";
  d.questions.push(b);
  d.gradingPayloads[b] = {
    ...d.gradingPayloads[q],
    uuid: "8cb757ae-6f14-467a-83cf-c1cfcb65d116",
  };
  const w = d.works[0],
    s = w.slots[0];
  Object.assign(s, {
    id: "demo/lab/alt-pair",
    selection: "choice",
    candidates: [q, b],
  });
  w.completion.slotIds = [s.id];
  w.completion.requiredSlotIds = [s.id];
  assert.equal(
    bridgeDeliverySchema.parse(d).works[0].slots[0].selection,
    "choice",
  );
  for (const path of [
    "C:/private",
    "a\0b",
    "../secret",
    "a//b",
    "/absolute",
    "a\\b",
  ]) {
    const changed = structuredClone(d);
    changed.gradingPayloads[q].sourceRoot = path;
    assert.throws(() => bridgeDeliverySchema.parse(changed));
  }
  s.assignment.requirement = "optional";
  assert.throws(() => bridgeDeliverySchema.parse(d));
});
