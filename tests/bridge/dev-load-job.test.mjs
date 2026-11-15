import assert from "node:assert/strict";
import {
  mkdtemp,
  readFile,
  rm,
  stat,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import {
  readJobState,
  runNativeLoadJob,
} from "../../tools/dev-load-course.mjs";

/** @param {(statePath: string) => Promise<void>} run */
async function withState(run) {
  const directory = await mkdtemp(path.join(tmpdir(), "pl-load-journal-"));
  try {
    await run(path.join(directory, "job.json"));
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}
/** @param {string} statePath */
function options(statePath) {
  return {
    statePath,
    resume: false,
    coursePath: "/course/fixture/current",
    uuid: "fixture-course-uuid",
    previousCourseId: "7",
    previousInstances: [
      {
        id: "11",
        short_name: "fixture",
        uuid: "fixture-instance-uuid",
        sync_errors: null,
      },
    ],
    timeoutMs: 0,
    intervalMs: 0,
    start: async () => "42",
    poll: async (/** @type {string} */ id) => {
      assert.equal(id, "42");
      return { status: /** @type {const} */ ("Success") };
    },
  };
}

test("intent is durable and readable by host controller before request; lost response cannot trigger a second request", async () =>
  withState(async (statePath) => {
    let requests = 0;
    const initial = options(statePath);
    initial.start = async () => {
      requests++;
      assert.equal((await readJobState(statePath))?.phase, "intent");
      assert.equal((await stat(statePath)).mode & 0o777, 0o644);
      throw new Error("response lost after native job started");
    };
    await assert.rejects(runNativeLoadJob(initial), /response lost/);
    await assert.rejects(runNativeLoadJob(initial), /уже существует/);
    await assert.rejects(
      runNativeLoadJob({ ...initial, resume: true }),
      /ID неизвестен/,
    );
    assert.equal(requests, 1);
    assert.equal((await readJobState(statePath))?.phase, "intent");
  }));

test("restrictive container umask preserves host readability for intent and atomic terminal writes", async () =>
  withState(async (statePath) => {
    const previousUmask = process.umask(0o077);
    try {
      const initial = options(statePath);
      await runNativeLoadJob({
        ...initial,
        start: async () => {
          assert.equal((await stat(statePath)).mode & 0o777, 0o644);
          return "42";
        },
      });
      assert.equal((await stat(statePath)).mode & 0o777, 0o644);
    } finally {
      process.umask(previousUmask);
    }
  }));

test("timeout retains exact job ID; resume polls it without a new request and retains original baseline", async () =>
  withState(async (statePath) => {
    const initial = options(statePath);
    let requests = 0;
    let polls = 0;
    await assert.rejects(
      runNativeLoadJob({
        ...initial,
        start: async () => {
          requests++;
          return "42";
        },
        poll: async (id) => {
          polls++;
          assert.equal(id, "42");
          const state = await readJobState(statePath);
          assert.equal(state?.phase, "running");
          assert.equal(state?.jobSequenceId, id);
          return { status: "Stopping" };
        },
      }),
      /Превышено время/,
    );
    const running = await readJobState(statePath);
    assert.equal(running?.phase, "running");
    assert.equal(running?.nativeStatus, undefined);
    const completed = await runNativeLoadJob({
      ...initial,
      resume: true,
      previousCourseId: "999",
      previousInstances: [],
      start: async () => {
        requests++;
        return "43";
      },
    });
    assert.equal(requests, 1);
    assert.equal(polls, 1);
    assert.equal(completed.phase, "terminal");
    assert.equal(completed.nativeStatus, "Success");
    assert.equal(completed.previousCourseId, "7");
    assert.deepEqual(completed.previousInstances, initial.previousInstances);
    assert.deepEqual(await readJobState(statePath), completed);
  }));

for (const terminal of /** @type {const} */ (["Error", "Stopped"])) {
  test(`${terminal} is durable native terminal; repeated resume does not start or poll`, async () =>
    withState(async (statePath) => {
      const initial = options(statePath);
      await assert.rejects(
        runNativeLoadJob({
          ...initial,
          poll: async () => ({ status: terminal }),
        }),
        new RegExp(terminal),
      );
      const state = await readJobState(statePath);
      assert.equal(state?.phase, "terminal");
      assert.equal(state?.nativeStatus, terminal);
      await assert.rejects(
        runNativeLoadJob({
          ...initial,
          resume: true,
          start: async () => {
            throw new Error("must not request");
          },
          poll: async () => {
            throw new Error("must not poll");
          },
        }),
        new RegExp(terminal),
      );
      await assert.rejects(runNativeLoadJob(initial), /уже существует/);
    }));
}

test("missing or foreign state refuses resume before request", async () =>
  withState(async (statePath) => {
    const initial = options(statePath);
    await assert.rejects(
      runNativeLoadJob({ ...initial, resume: true }),
      /отсутствует/,
    );
    await runNativeLoadJob(initial);
    for (const mismatch of [
      { uuid: "another-uuid" },
      { coursePath: "/course/other/current" },
    ]) {
      await assert.rejects(
        runNativeLoadJob({
          ...initial,
          ...mismatch,
          resume: true,
          start: async () => {
            throw new Error("must not request");
          },
          poll: async () => {
            throw new Error("must not poll");
          },
        }),
        /UUID/,
      );
    }
  }));

test("two normal invocations share one exclusive intent and produce one request", async () =>
  withState(async (statePath) => {
    let requests = 0;
    const initial = {
      ...options(statePath),
      start: async () => {
        requests++;
        return "42";
      },
    };
    const outcomes = await Promise.allSettled([
      runNativeLoadJob(initial),
      runNativeLoadJob(initial),
    ]);
    assert.equal(
      outcomes.filter((outcome) => outcome.status === "fulfilled").length,
      1,
    );
    assert.equal(requests, 1);
    assert.equal((await readJobState(statePath))?.nativeStatus, "Success");
  }));

test("symlink and corrupt state fail closed without overwriting their contents", async () =>
  withState(async (statePath) => {
    const target = `${statePath}.target`;
    await writeFile(target, "operator evidence");
    await symlink(target, statePath);
    await assert.rejects(runNativeLoadJob(options(statePath)), /ELOOP/);
    assert.equal(await readFile(target, "utf8"), "operator evidence");
    await rm(statePath);
    await writeFile(
      statePath,
      JSON.stringify({
        schemaVersion: 1,
        phase: "terminal",
        nativeStatus: "Success",
      }),
    );
    await assert.rejects(
      runNativeLoadJob({ ...options(statePath), resume: true }),
      /Некорректный/,
    );
  }));
