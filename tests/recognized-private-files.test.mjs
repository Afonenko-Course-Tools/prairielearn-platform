import assert from "node:assert/strict";
import { test } from "node:test";
import {
  attachRecognizedPrivateFiles,
  privateDisplayName,
} from "../tools/recognized-credit-files.mjs";
function fixture() {
  const data = Buffer.from("class PrivateAnswer {}\n");
  const ref =
    /** @type {import("../types/recognized-credit.d.ts").PrivateReference & {source:import("../types/recognized-credit.d.ts").SubmissionReference}} */ ({
      sourceReference: "submission:12:raw:0",
      source: {
        kind: "submission",
        submissionId: "12",
        variantId: "13",
        assessmentInstanceId: "15",
        instanceQuestionId: "14",
        userId: "16",
        fileIndex: 0,
        filename: "Answer.java",
        answerField: "raw",
      },
      relativeName: "Answer.java",
      uid: "student@fixture.invalid",
    });
  const target = {
    uid: ref.uid,
    userId: "16",
    assessmentId: "22",
    assessmentInstanceId: "25",
    instanceQuestionId: "26",
  };
  /** @type {import("../types/recognized-credit.d.ts").PrivateFile[]} */
  const rows = [];
  /** @type {Map<string,Buffer>} */
  const content = new Map();
  /** @type {import("../types/recognized-credit.d.ts").PrivateFilesApi} */
  const api = {
    readSourceReference: async (r) => {
      if (r.source.kind !== "submission" || r.source.submissionId !== "12")
        throw Error("Foreign native source");
      return data;
    },
    context: async () => ({
      ...target,
      recognizedCredit: true,
      allowPersonalNotes: true,
      actorUserId: "99",
    }),
    findFiles: async (n) => rows.filter((r) => r.display_filename === n),
    uploadFile: async (options) => {
      const id = String(rows.length + 1),
        row =
          /** @type {import("../types/recognized-credit.d.ts").PrivateFile} */ ({
            ...options,
            id,
          });
      delete row.contents;
      rows.push(row);
      content.set(id, Buffer.from(options.contents));
      return id;
    },
    getFile: async (id) => {
      const file = rows.find((r) => r.id === id),
        contents = content.get(id);
      assert.ok(file && contents);
      return { file, contents };
    },
  };
  return {
    ref,
    target,
    rows,
    api,
    data,
    args: /** @type {{refs:typeof ref[],target:typeof target,actorUserId?:string}} */ ({
      refs: [ref],
      target,
      actorUserId: "99",
    }),
  };
}
test("actual native bytes and source IDs determine copy and replay without content fingerprints", async () => {
  const f = fixture();
  const result = await attachRecognizedPrivateFiles(f.args, f.api);
  assert.equal(result.files.length, 1);
  assert.equal(f.rows[0].user_id, "16");
  assert.equal(
    privateDisplayName(f.ref),
    "recognized-submission-12-raw-0-Answer.java",
  );
  assert.deepEqual(await attachRecognizedPrivateFiles(f.args, f.api), result);
  assert.equal(f.rows.length, 1);
});
test("duplicates, foreign UID and source parent IDs refuse before upload", async () => {
  for (const kind of ["duplicate", "uid", "source", "path"]) {
    const f = fixture();
    if (kind === "duplicate") f.args.refs.push(f.ref);
    if (kind === "uid") f.ref.uid = "foreign";
    if (kind === "source") {
      f.ref.sourceReference = "submission:99:raw:0";
      f.ref.source.submissionId = "99";
    }
    if (kind === "path") f.ref.relativeName = "../escape";
    await assert.rejects(attachRecognizedPrivateFiles(f.args, f.api));
    assert.equal(f.rows.length, 0);
  }
});
test("actor, personal notes and actual native owner control access", async () => {
  for (const kind of ["actor", "notes", "uid"]) {
    const f = fixture();
    if (kind === "actor") delete f.args.actorUserId;
    if (kind === "notes")
      f.api.context = async () => ({
        ...f.target,
        recognizedCredit: true,
        allowPersonalNotes: false,
        actorUserId: "99",
      });
    if (kind === "uid")
      f.api.context = async () => ({
        ...f.target,
        uid: "foreign",
        recognizedCredit: true,
        allowPersonalNotes: true,
        actorUserId: "99",
      });
    await assert.rejects(attachRecognizedPrivateFiles(f.args, f.api));
    assert.equal(f.rows.length, 0);
  }
});
test("native bytes mismatch or wrong existing owner never overwrites a student file", async () => {
  for (const kind of ["owner", "bytes"]) {
    const f = fixture();
    await attachRecognizedPrivateFiles(f.args, f.api);
    if (kind === "owner") f.rows[0].assessment_instance_id = "foreign";
    else
      f.api.getFile = async () => ({
        file: f.rows[0],
        contents: Buffer.from("different"),
      });
    await assert.rejects(attachRecognizedPrivateFiles(f.args, f.api));
    assert.equal(f.rows.length, 1);
  }
});
test("file and total size limits reject before the first native upload", async () => {
  const f = fixture();
  f.api.readSourceReference = async () => Buffer.alloc(1048577);
  await assert.rejects(attachRecognizedPrivateFiles(f.args, f.api));
  assert.equal(f.rows.length, 0);
});
test("empty selected file list requires no personal notes and does not upload", async () => {
  const f = fixture();
  f.args.refs = [];
  f.api.context = async () => ({
    ...f.target,
    recognizedCredit: true,
    allowPersonalNotes: false,
    actorUserId: "99",
  });
  assert.deepEqual(
    (await attachRecognizedPrivateFiles(f.args, f.api)).files,
    [],
  );
  assert.equal(f.rows.length, 0);
});
