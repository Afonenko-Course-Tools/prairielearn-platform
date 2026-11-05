import assert from 'node:assert/strict';
import { readFile, mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Readable } from 'node:stream';
import { test } from 'node:test';
import { z } from 'zod';
import { BridgeError } from '../../bridge/policy.mjs';

// Исполняются настоящие context, enrollBasic, schema и HTTP handler из server.mjs.
// Изолированы только native DB/models и listener; это не native DB/Moodle smoke.
const source = await readFile(new URL('../../bridge/server.mjs', import.meta.url), 'utf8');
const contextSource = source.slice(source.indexOf('async function context('), source.indexOf('async function validateWork('));
const schemaSource = source.slice(source.indexOf('const workQuerySchema'), source.indexOf('async function nativeStudentWorkContext('));
const enrollmentSource = source.slice(source.indexOf('const enrollmentQuerySchema'), source.indexOf('server.listen('));
const request = { userUid: 'student@fixture.invalid', instance: 'fall', courseKey: 'demo' };
const token = 'fixture-service-token-with-at-least-32-characters';

async function fixture(t, changes = {}) {
  const deliveryPath = await mkdtemp(join(tmpdir(), 'bridge-enrollment-'));
  t.after(() => rm(deliveryPath, { recursive: true, force: true }));
  await mkdir(join(deliveryPath, 'courseInstances/fall'), { recursive: true });
  await writeFile(join(deliveryPath, 'courseInstances/fall/infoCourseInstance.json'), JSON.stringify({ uuid: 'native-course-uuid' }));
  const state = { writes: [], identities: [], access: [], adminGrants: 0 };
  const ci = { id: '73', uuid: 'native-course-uuid', deleted_at: null, modern_publishing: true, ...changes.ci };
  const user = changes.missingUser ? null : { id: '21', uid: request.userUid };
  let handler;
  const args = {
    settings: {},
    bindings: [{ courseInstanceId: '73', deliveryPath, delivery: { courseId: 'demo', instances: { fall: { works: [] } } } }],
    instances: { selectCourseInstanceById: async id => { assert.equal(id, '73'); return ci; } },
    users: { selectOptionalUserByUid: async uid => { state.identities.push(uid); return user; } },
    readFile, z, BridgeError, Buffer, URL, token, system: { fixture: true },
    resolveAssignment: () => { throw Error('Enrollment не должен требовать assignment'); },
    db: {
      runInTransactionAsync: async fn => fn(),
      execute: async (sql, params) => { assert.equal(sql, 'lock'); state.writes.push(params); },
      queryRow: async () => { state.adminGrants++; throw Error('Неожиданный administrator grant'); },
    },
    sql: { lock: 'lock' },
    enrollments: {
      selectOptionalEnrollmentByUserId: async () => changes.prior ?? null,
      ensureUncheckedEnrollment: async params => { state.writes.push(params); return changes.unavailable ? null : { id: '11', status: 'joined' }; },
    },
    studentAccess: { calculateModernCourseInstanceStudentAccess: async (instance, userId) => { state.access.push({ instance, userId }); return { has_student_access_with_enrollment: !changes.denied }; } },
    timingSafeEqual: (a, b) => a.equals(b),
    createServer: callback => { handler = callback; return {}; },
  };
  new Function(...Object.keys(args), contextSource + schemaSource + enrollmentSource)(...Object.values(args));
  return { state, ci, async send(body = request, options = {}) {
    const req = Readable.from([typeof body === 'string' ? body : JSON.stringify(body)]);
    req.method = 'PUT'; req.url = '/internal/gateway/enrollment' + (options.query ?? '');
    req.headers = { authorization: options.authorization ?? `Bearer ${token}` };
    let status, headers, answer;
    await handler(req, { writeHead(code, values) { status = code; headers = values; return this; }, end(value) { answer = JSON.parse(value); } });
    return { status, headers, body: answer };
  } };
}

test('зачисление возвращает проверенный native список курса и сохраняет UID при повторе', async t => {
  const f = await fixture(t);
  const expected = { schemaVersion: 1, ...request, enrolled: true, path: '/pl/course_instance/73/assessments' };
  for (let i = 0; i < 2; i++) {
    const result = await f.send();
    assert.equal(result.status, 200);
    assert.deepEqual(result.body, expected);
    assert.equal(result.headers['Cache-Control'], 'no-store');
  }
  assert.deepEqual(f.state.identities, [request.userUid, request.userUid]);
  assert.equal(f.state.adminGrants, 0);
  assert.ok(f.state.writes.filter(value => value.userId).every(value => value.userId === '21' && value.courseInstance === f.ci));
});

test('body и query не принимают роль, assignment, redirect или посторонние поля', async t => {
  const f = await fixture(t);
  for (const extra of [{ role: 'teacher' }, { administrator: true }, { workId: 'lab' }, { assignmentId: 'a' }, { path: '//evil.invalid/' }, { deliveryHash: 'old' }]) {
    assert.equal((await f.send({ ...request, ...extra })).status, 400);
  }
  for (const field of Object.keys(request)) {
    const incomplete = { ...request }; delete incomplete[field];
    assert.equal((await f.send(incomplete)).status, 400);
  }
  assert.equal((await f.send('{')).status, 400);
  assert.equal((await f.send(request, { query: '?workId=lab' })).status, 400);
  assert.equal((await f.send(request, { authorization: 'Bearer foreign' })).status, 401);
  assert.deepEqual(f.state.writes, []);
});

for (const [name, changes, body, status] of [
  ['неизвестный курс', {}, { ...request, courseKey: 'other' }, 403],
  ['неизвестный экземпляр', {}, { ...request, instance: 'other' }, 403],
  ['удалённый native экземпляр', { ci: { deleted_at: '2026-11-05' } }, request, 403],
  ['несовпадение native UUID', { ci: { uuid: 'foreign' } }, request, 403],
  ['отсутствующий проверенный UID', { missingUser: true }, request, 404],
  ['blocked membership', { prior: { status: 'blocked' } }, request, 403],
  ['недоступное зачисление', { unavailable: true }, request, 403],
  ['закрытый native student доступ', { denied: true }, request, 403],
  ['старый publishing mode', { ci: { modern_publishing: false } }, request, 403],
  ['нечисловой native id', { ci: { id: '73/../administrator' } }, request, 409],
]) {
  test(`зачисление отклоняет: ${name}`, async t => {
    const f = await fixture(t, changes);
    const result = await f.send(body);
    assert.equal(result.status, status);
    assert.equal(result.body.path, undefined);
    assert.equal(f.state.adminGrants, 0);
    if (status === 404 || ['неизвестный курс', 'неизвестный экземпляр', 'удалённый native экземпляр', 'несовпадение native UUID', 'нечисловой native id'].includes(name)) assert.deepEqual(f.state.writes, []);
    if (name === 'blocked membership') assert.equal(f.state.writes.filter(value => value.userId).length, 0);
  });
}
