import assert from "node:assert/strict";
import { existsSync } from "node:fs";
import { test } from "node:test";
const source = new URL("../../tools/migrate-users.mjs", import.meta.url);
test("identity-only migration tool exists", () =>
  assert.ok(existsSync(source)));
if (existsSync(source)) {
  const { planImport, applyImport } =
    await import("../../tools/migrate-users.mjs");
  const snapshot = () => ({
    schema: "pl-users-v1",
    users: [
      {
        uid: "one",
        name: "One",
        email: "same@example.test",
        uin: null,
        institution: "Default",
      },
      {
        uid: "two",
        name: "Two",
        email: "same@example.test",
        uin: null,
        institution: "Default",
      },
    ],
    administrators: ["one"],
    instances: [
      { id: "34", courseId: "34", coursePath: "/old/java", uuid: "same-uuid" },
      {
        id: "35",
        courseId: "35",
        coursePath: "/old/java-copy",
        uuid: "same-uuid",
      },
    ],
    enrollments: [
      { uid: "one", instanceId: "34", status: "blocked", isGuest: false },
      { uid: "two", instanceId: "35", status: "joined", isGuest: false },
    ],
    coursePermissions: [{ uid: "one", courseId: "34", role: "Editor" }],
    instancePermissions: [
      { uid: "one", instanceId: "34", role: "Student Data Editor" },
    ],
  });
  const mapping = [
    {
      sourceInstanceId: "34",
      sourceCourseId: "34",
      targetInstanceId: "9",
      targetCourseId: "7",
    },
    {
      sourceInstanceId: "35",
      sourceCourseId: "35",
      targetInstanceId: "9",
      targetCourseId: "7",
    },
  ];
  test("exact UID preserves separate identities with equal email, rights, and blocked access", () => {
    const p = planImport(snapshot(), mapping);
    assert.equal(p.users.length, 2);
    assert.equal(p.enrollments[0].status, "blocked");
    assert.equal(p.enrollments[0].instanceId, "9");
    assert.equal(p.coursePermissions[0].courseId, "7");
    assert.equal(p.instancePermissions[0].instanceId, "9");
    assert.deepEqual(p.administrators, ["one"]);
  });
  test("rejects history/score fields, missing maps, wrong parent and conflicting merged access", () => {
    assert.throws(
      () => planImport({ ...snapshot(), submissions: [] }, mapping),
      /identity-only/,
    );
    assert.throws(
      () =>
        planImport(
          { ...snapshot(), users: [{ ...snapshot().users[0], score: 100 }] },
          mapping,
        ),
      /identity-only/,
    );
    assert.throws(() => planImport(snapshot(), mapping.slice(1)), /mapping/);
    assert.throws(
      () =>
        planImport(snapshot(), [
          { ...mapping[0], sourceCourseId: "35" },
          mapping[1],
        ]),
      /parent/,
    );
    const s = snapshot();
    s.enrollments.push({
      uid: "one",
      instanceId: "35",
      status: "joined",
      isGuest: false,
    });
    assert.throws(() => planImport(s, mapping), /Conflicting/);
  });
  test("all identity/access operations run in one fresh-target transaction and keep statuses", async () => {
    /** @type {(string|string[])[]} */ const events = [];
    const p = planImport(snapshot(), mapping);
    await applyImport(p, {
      async transaction(fn) {
        events.push("begin");
        await fn();
        events.push("commit");
      },
      async assertFresh() {
        events.push("fresh");
      },
      async checkTargets() {
        events.push("targets");
      },
      async putUser(u) {
        events.push(["user", u.uid]);
      },
      async putAdministrator(uid) {
        events.push(["admin", uid]);
      },
      async putEnrollment(e) {
        events.push(["enrollment", e.uid, e.status]);
      },
      async putCoursePermission(p) {
        events.push(["course", p.uid, p.role]);
      },
      async putInstancePermission(p) {
        events.push(["instance", p.uid, p.role]);
      },
    });
    assert.deepEqual(events.slice(0, 3), ["begin", "fresh", "targets"]);
    assert.deepEqual(
      events.filter(Array.isArray).filter((e) => e[0] === "user"),
      [
        ["user", "one"],
        ["user", "two"],
      ],
    );
    assert.ok(
      events.some(
        (e) => Array.isArray(e) && e[0] === "enrollment" && e[2] === "blocked",
      ),
    );
    assert.equal(events.at(-1), "commit");
  });
  test("fresh-target refusal prevents all imports", async () => {
    let writes = 0;
    await assert.rejects(
      () =>
        applyImport(planImport(snapshot(), mapping), {
          async transaction(fn) {
            await fn();
          },
          async assertFresh() {
            throw new Error("Target is not fresh");
          },
          async checkTargets() {},
          async putUser() {
            writes++;
          },
          async putAdministrator() {
            writes++;
          },
          async putEnrollment() {
            writes++;
          },
          async putCoursePermission() {
            writes++;
          },
          async putInstancePermission() {
            writes++;
          },
        }),
      /not fresh/,
    );
    assert.equal(writes, 0);
  });
}
