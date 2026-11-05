import assert from 'node:assert/strict';
import { readFile, mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Readable } from 'node:stream';
import { timingSafeEqual } from 'node:crypto';
import { test } from 'node:test';
import { z } from 'zod';
import { loadVerifiedBindings } from '../../bridge/bindings.mjs';
import * as policy from '../../bridge/policy.mjs';

// Настоящий server core: settings/startup/context/enrollment/router. Изолированы
// native DB/models и listener; native DB, Moodle и grading runtime не проверяются.
const sourceFlag = process.argv.find(value => value.startsWith('--server-source='));
const source = await readFile(sourceFlag ? sourceFlag.slice('--server-source='.length) : new URL('../../bridge/server.mjs', import.meta.url), 'utf8');
const core = source.slice(source.indexOf('const settingsSchema ='), source.indexOf('server.listen('))
  .replaceAll('import.meta.url', JSON.stringify(new URL('../../bridge/server.mjs', import.meta.url).href));
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const uuid = '514a8336-f599-47bf-ae63-822cbac36f0b';
const binding = { courseKey: 'demo', instance: 'fall', courseId: '7', courseInstanceId: '73', courseInstanceUuid: uuid };
const request = { userUid: 'student@fixture.invalid', instance: 'fall', courseKey: 'demo' };
const loginRequest = { ...request, role: 'student', email: null };
const token = 'fixture-service-token-with-at-least-32-characters';

async function fixture(t, options = {}) {
  const path = await mkdtemp(join(tmpdir(), 'bridge-login-only-'));
  t.after(() => rm(path, { recursive: true, force: true }));
  await writeFile(join(path, 'token'), token);
  const settings = options.settings ?? {
    mode: 'login-only', listenHost: '127.0.0.1', listenPort: 3001,
    tokenFile: join(path, 'token'), bindings: [binding],
  };
  settings.tokenFile = join(path, 'token');
  await writeFile(join(path, 'config.json'), JSON.stringify(settings));
  const ci = { id: '73', course_id: '7', uuid, short_name: 'fall', deleted_at: null, modern_publishing: true, ...options.ci };
  const state = { migrations: 0, enrollmentWrites: [], locks: [], nativeReads: 0, bodyReads: 0, queries: 0,
    courseGrants: [], instanceGrants: [], administrators: new Set(), courseRole: options.courseRole ?? null, instanceRole: null };
  let handler;
  const args = {
    z, readFile, loadVerifiedBindings, ...policy, Buffer, URL, timingSafeEqual,
    process: { env: { PL_GATEWAY_CONFIG: join(path, 'config.json'), NODE_ENV: options.environment ?? 'production' }, exitCode: 0 },
    root: '/native', config: { devMode: false, hasShib: true, ...options.config }, loadConfig: async () => {},
    native: async name => { assert.equal(name, 'sprocs/index'); return { init: async () => {} }; },
    db: {
      initAsync: async () => {}, setRandomSearchSchemaAsync: async () => {},
      loadSqlEquiv: () => ({ migrate: 'migrate', lock: 'lock', grant_administrator: 'administrator' }),
      execute: async (sql, params) => { if (sql === 'migrate') state.migrations++; else { assert.equal(sql, 'lock'); state.locks.push(params); } },
      runInTransactionAsync: async fn => fn(),
      queryRow: async (sql, params) => {
        state.queries++; assert.equal(sql, 'administrator');
        assert.ok(['teacher@fixture.invalid', 'student@fixture.invalid'].includes(params.uid));
        assert.equal(params.user_id, params.uid.startsWith('teacher') ? '22' : '21');
        if (!options.adminGrantFailure) state.administrators.add(params.user_id);
        return { administrator: !options.adminGrantFailure };
      },
      queryOptionalRow: async () => { state.queries++; throw Error('Неожиданный native query'); },
    },
    dangerousFullSystemAuthz: () => ({ fixture: true }),
    instances: { selectCourseInstanceById: async id => { state.nativeReads++; assert.equal(id, '73'); return ci; } },
    users: { selectOptionalUserByUid: async uid => { state.nativeReads++; return options.missingUser ? null : { id: uid.startsWith('teacher') ? '22' : '21', uid }; } },
    coursePermissions: {
      insertCoursePermissionsByUserUid: async value => {
        assert.equal(value.course_id, '7'); assert.equal(value.uid, 'teacher@fixture.invalid');
        assert.equal(value.course_role, 'Editor'); assert.equal(value.authn_user_id, '22');
        state.courseGrants.push(value); state.courseRole = options.courseRole ?? 'Editor';
        return { id: options.changedUser ? '99' : '22', uid: value.uid };
      },
      insertCourseInstancePermissions: async value => {
        assert.equal(value.course_id, '7'); assert.equal(value.course_instance_id, '73');
        assert.equal(value.user_id, '22'); assert.equal(value.course_instance_role, 'Student Data Editor');
        assert.equal(value.authn_user_id, '22'); state.instanceGrants.push(value);
        if (!options.permissionFailure) state.instanceRole = 'Student Data Editor';
      },
      selectCoursePermissionForUser: async value => { assert.deepEqual(value, { course_id: '7', user_id: '22' }); return state.courseRole; },
      selectCourseInstancePermissionForUser: async value => { assert.deepEqual(value, { course_instance_id: '73', user_id: '22' }); return state.instanceRole; },
    },
    enrollments: {
      selectOptionalEnrollmentByUserId: async () => options.prior ?? null,
      ensureUncheckedEnrollment: async value => { state.enrollmentWrites.push(value); return options.unavailable ? null : { id: '11', status: 'joined' }; },
    },
    studentAccess: { calculateModernCourseInstanceStudentAccess: async () => ({ has_student_access_with_enrollment: !options.denied }) },
    AssessmentInstanceSchema: z.object({}), labels: {}, nativeAssessment: {}, assessmentAccess: {},
    createServer: fn => { handler = fn; return {}; },
  };
  const parsed = await new AsyncFunction(...Object.keys(args), core + ';return {settings, bindings};')(...Object.values(args));
  return { ...parsed, state, async send(options = {}) {
    const body = options.body ?? (settings.mode === 'login-only' ? loginRequest : request);
    const req = Readable.from([typeof body === 'string' ? body : JSON.stringify(body)]);
    const iterate = req[Symbol.asyncIterator].bind(req);
    req[Symbol.asyncIterator] = () => { state.bodyReads++; return iterate(); };
    req.method = options.method ?? 'PUT';
    req.url = options.url ?? '/internal/gateway/enrollment';
    req.headers = { authorization: options.authorization ?? `Bearer ${token}` };
    let status, answer;
    await handler(req, { writeHead(code) { status = code; return this; }, end(value) { answer = JSON.parse(value); } });
    return { status, body: answer };
  } };
}

test('login-only запускается без delivery и сохраняет прежние UID без assignment DDL', async t => {
  let f;
  await assert.doesNotReject(async () => { f = await fixture(t); });
  assert.equal(f.state.migrations, 0);
  for (const userUid of ['student@fixture.invalid', 'teacher@fixture.invalid']) {
    for (let i = 0; i < 2; i++) {
      const result = await f.send({ body: { ...loginRequest, userUid } });
      assert.equal(result.status, 200);
      assert.deepEqual(result.body, { schemaVersion: 1, ...request, userUid, enrolled: true, path: '/pl/course_instance/73/assessments' });
    }
  }
  assert.deepEqual(f.state.enrollmentWrites.map(value => value.userId), ['21', '21', '22', '22']);
  assert.equal(f.state.queries, 0);
});

test('login-only отклоняет остальные routes до body parsing и native операций', async t => {
  const f = await fixture(t);
  for (const [method, url] of [
    ['PUT', '/internal/gateway/assignments/a'], ['GET', '/internal/gateway/results'],
    ['GET', '/internal/gateway/work-results'], ['GET', '/internal/gateway/work-launch'],
    ['PUT', '/internal/gateway/administrator'], ['GET', '/internal/gateway/enrollment'],
    ['POST', '/internal/gateway/enrollment'], ['PUT', '/internal/gateway/enrollment/'],
  ]) assert.equal((await f.send({ method, url, body: '{' })).status, 404);
  assert.equal(f.state.bodyReads, 0);
  assert.equal(f.state.nativeReads, 0);
  assert.equal(f.state.queries, 0);
  assert.deepEqual(f.state.enrollmentWrites, []);
});

test('login-only сохраняет bearer, query и strict enrollment body guards', async t => {
  const f = await fixture(t);
  assert.equal((await f.send({ authorization: 'Bearer wrong' })).status, 401);
  assert.equal((await f.send({ url: '/internal/gateway/enrollment?workId=lab' })).status, 400);
  for (const extra of [{ role: 'administrator' }, { administrator: true }, { workId: 'lab' }, { path: '//evil.invalid' }, { courseInstanceId: '1' }]) {
    assert.equal((await f.send({ body: { ...loginRequest, ...extra } })).status, 400);
  }
  for (const name of Object.keys(loginRequest)) {
    const body = { ...loginRequest }; delete body[name];
    assert.equal((await f.send({ body })).status, 400);
  }
  assert.equal(f.state.nativeReads, 0);
});

for (const [name, options, body, status] of [
  ['неизвестный courseKey', {}, { ...request, courseKey: 'other' }, 403],
  ['неизвестный instance', {}, { ...request, instance: 'other' }, 403],
  ['native CIID', { ci: { id: '74' } }, request, 403],
  ['native course ID', { ci: { course_id: '8' } }, request, 403],
  ['native UUID', { ci: { uuid: '44167bfa-a17e-444f-b4f8-af2877980aa1' } }, request, 403],
  ['native short_name', { ci: { short_name: 'other' } }, request, 403],
  ['deleted instance', { ci: { deleted_at: '2026-11-05' } }, request, 403],
  ['отсутствующий UID', { missingUser: true }, request, 404],
  ['blocked membership', { prior: { status: 'blocked' } }, request, 403],
  ['недоступное зачисление', { unavailable: true }, request, 403],
  ['native student access', { denied: true }, request, 403],
  ['старый publishing mode', { ci: { modern_publishing: false } }, request, 403],
]) test(`login-only отклоняет: ${name}`, async t => {
  const f = await fixture(t, options);
  const result = await f.send({ body: { ...loginRequest, ...body } });
  assert.equal(result.status, status);
  assert.equal(result.body.path, undefined);
  assert.equal(f.state.queries, 0);
  if (['неизвестный courseKey', 'неизвестный instance', 'native CIID', 'native course ID', 'native UUID', 'native short_name', 'deleted instance', 'отсутствующий UID', 'blocked membership'].includes(name)) assert.deepEqual(f.state.enrollmentWrites, []);
});

test('login-only config закрыт, bindings однозначны и сохраняется production guard', async t => {
  const base = { mode: 'login-only', listenHost: '127.0.0.1', listenPort: 3001, bindings: [binding] };
  for (const settings of [
    { ...base, administratorUid: null }, { ...base, bindings: [{ ...binding, deliveryPath: '/candidate' }] },
    { ...base, bindings: [binding, binding] }, { ...base, bindings: [] },
    { ...base, bindings: [{ ...binding, courseInstanceId: '1/../2' }] },
    { ...base, bindings: [{ ...binding, courseId: '0' }] },
    { ...base, bindings: [{ ...binding, courseInstanceUuid: 'wrong' }] },
    { ...base, mode: 'automatic' }, { ...base, administratorEmail: 'OWNER@fixture.invalid' },
    { ...base, administratorEmail: ' owner@fixture.invalid' },
  ]) await assert.rejects(fixture(t, { settings }));
  for (const options of [{ environment: 'development' }, { config: { devMode: true } }, { config: { hasShib: false } }]) {
    await assert.rejects(fixture(t, options), /production/);
  }
});

test('подтверждённый Teacher получает только native Editor и Student Data Editor с прежним UID и audit actor', async t => {
  const f = await fixture(t);
  for (let i = 0; i < 2; i++) {
    const result = await f.send({ body: { ...loginRequest, userUid: 'teacher@fixture.invalid', role: 'teacher', email: 'teacher@fixture.invalid' } });
    assert.equal(result.status, 200);
    assert.deepEqual(Object.keys(result.body).sort(), ['courseKey', 'enrolled', 'instance', 'path', 'schemaVersion', 'userUid']);
  }
  assert.equal(f.state.courseRole, 'Editor');
  assert.equal(f.state.instanceRole, 'Student Data Editor');
  assert.equal(f.state.courseGrants.length, 2);
  assert.equal(f.state.instanceGrants.length, 2);
  assert.equal(f.state.administrators.size, 0);
});

test('точное подтверждённое session email выдаёт Administrator независимо от Moodle роли', async t => {
  const settings = { mode: 'login-only', listenHost: '127.0.0.1', listenPort: 3001, administratorEmail: 'owner@fixture.invalid', bindings: [binding] };
  const f = await fixture(t, { settings });
  for (const body of [
    { ...loginRequest, email: 'other@fixture.invalid' },
    { ...loginRequest, userUid: 'teacher@fixture.invalid', role: 'teacher', email: null },
    { ...loginRequest, userUid: 'teacher@fixture.invalid', role: 'teacher', email: 'other@fixture.invalid' },
    { ...loginRequest, userUid: 'teacher@fixture.invalid', role: 'teacher', email: 'owner+alias@fixture.invalid' },
  ]) {
    assert.equal((await f.send({ body })).status, 200);
    assert.equal(f.state.administrators.size, 0);
  }
  const before = f.state.courseGrants.length;
  for (const [userUid, role] of [['student@fixture.invalid', 'student'], ['teacher@fixture.invalid', 'teacher']]) {
    for (let i = 0; i < 2; i++) assert.equal((await f.send({ body: { ...loginRequest, userUid, role, email: 'owner@fixture.invalid' } })).status, 200);
  }
  assert.deepEqual([...f.state.administrators], ['21', '22']);
  assert.equal(f.state.courseGrants.length, before);
});

test('неподтверждённая native Administrator запись отклоняется', async t => {
  const settings = { mode: 'login-only', listenHost: '127.0.0.1', listenPort: 3001, administratorEmail: 'owner@fixture.invalid', bindings: [binding] };
  const f = await fixture(t, { settings, adminGrantFailure: true });
  assert.equal((await f.send({ body: { ...loginRequest, email: 'owner@fixture.invalid' } })).status, 409);
});

test('неподтверждённый вызов, неизвестная роль и неканонический email не дают grant', async t => {
  const f = await fixture(t);
  const teacher = { ...loginRequest, userUid: 'teacher@fixture.invalid', role: 'teacher', email: 'owner@fixture.invalid' };
  assert.equal((await f.send({ authorization: 'Bearer wrong', body: teacher })).status, 401);
  for (const change of [{ role: 'administrator' }, { email: 'OWNER@fixture.invalid' }, { email: ' owner@fixture.invalid' }, { email: '' }, { email: 'x'.repeat(65)+'@fixture.invalid' }, { email: 'owner@'+'x'.repeat(64)+'.invalid' }, { email: 'owner..name@fixture.invalid' }, { email: 'owner@fixture.invalid\n' }, { email: 'ownér@fixture.invalid' }, { email: 'owner@localhost' }, { verifiedEmail: 'owner@fixture.invalid' }, { email_verified: true }]) {
    assert.equal((await f.send({ body: { ...teacher, ...change } })).status, 400);
  }
  assert.equal(f.state.nativeReads, 0);
  assert.equal(f.state.courseGrants.length, 0);
  assert.equal(f.state.administrators.size, 0);
});

test('teacher grant проверяет native identity и фактические permissions; существующий Owner не понижается', async t => {
  const body = { ...loginRequest, userUid: 'teacher@fixture.invalid', role: 'teacher', email: null };
  for (const options of [{ changedUser: true }, { permissionFailure: true }]) {
    const f = await fixture(t, options);
    assert.equal((await f.send({ body })).status, 409);
    assert.equal(f.state.administrators.size, 0);
    if (options.changedUser) assert.equal(f.state.instanceGrants.length, 0);
  }
  const owner = await fixture(t, { courseRole: 'Owner' });
  assert.equal((await owner.send({ body })).status, 200);
  assert.equal(owner.state.courseRole, 'Owner');
});

test('отказ existing UID, blocked или native access происходит до teacher/admin grant', async t => {
  for (const options of [{ missingUser: true }, { prior: { status: 'blocked' } }, { denied: true }]) {
    const f = await fixture(t, options);
    const result = await f.send({ body: { ...loginRequest, userUid: 'teacher@fixture.invalid', role: 'teacher', email: 'owner@fixture.invalid' } });
    assert.equal(result.status, options.missingUser ? 404 : 403);
    assert.equal(f.state.courseGrants.length, 0);
    assert.equal(f.state.administrators.size, 0);
  }
});

async function gradingSettings(t, candidate = false) {
  const path = await mkdtemp(join(tmpdir(), 'bridge-grading-mode-'));
  t.after(() => rm(path, { recursive: true, force: true }));
  await mkdir(join(path, 'courseInstances/fall'), { recursive: true });
  await writeFile(join(path, 'infoCourse.json'), '{"name":"Fixture"}');
  await writeFile(join(path, 'courseInstances/fall/infoCourseInstance.json'), JSON.stringify({ uuid }));
  const q = 'demo/exr-a', slot = 'demo/lab/exr-a';
  await writeFile(join(path, 'delivery.json'), JSON.stringify({
    schemaVersion: 5, courseId: 'demo', bookRoot: 'tasks', questions: [q],
    gradingPayloads: { [q]: { kind: 'project', uuid, grading: { method: 'manual' }, submission: { mode: 'upload' }, sourceRoot: 'projects/a' } },
    works: [{ id: 'lab', slots: [{ id: slot, selection: 'fixed', candidates: [q], assignment: { requirement: 'required', workMode: 'individual' } }], policy: {}, completion: { schemaVersion: 2, mode: 'required-slot-completion', source: 'per-slot-results-v2', slotIds: [slot], requiredSlotIds: [slot], atLeast: 1, fullyCompletedScore: 1 } }],
    instances: { fall: { works: ['lab'], selfEnrollment: false } },
    files: ['infoCourse.json', 'courseInstances/fall/infoCourseInstance.json'], ...(candidate ? { candidate: true } : {}),
  }));
  return { listenHost: '127.0.0.1', listenPort: 3001, bindings: [{ deliveryPath: path, courseInstanceId: '73' }] };
}

test('стандартный режим сохраняет full payload, миграцию и grading routes', async t => {
  const f = await fixture(t, { settings: await gradingSettings(t) });
  assert.equal(f.state.migrations, 1);
  assert.equal(f.bindings[0].delivery.courseId, 'demo');
  assert.equal((await f.send()).status, 200);
  assert.equal((await f.send({ body: loginRequest })).status, 400);
  assert.equal((await f.send({ method: 'GET', url: '/internal/gateway/work-results' })).status, 400);
});

test('стандартный режим сохраняет отказ candidate и неполного grading payload', async t => {
  await assert.rejects(fixture(t, { settings: await gradingSettings(t, true) }), /Candidate/);
  const settings = await gradingSettings(t);
  await writeFile(join(settings.bindings[0].deliveryPath, 'delivery.json'), '{}');
  await assert.rejects(fixture(t, { settings }));
});

test('стандартный режим сохраняет digest guard workspace OCI', async t => {
  const settings = await gradingSettings(t);
  const file = join(settings.bindings[0].deliveryPath, 'delivery.json');
  const delivery = JSON.parse(await readFile(file, 'utf8'));
  const workspaceOptions = {
    image: 'docker.io/example/fixture@sha256:' + 'b'.repeat(64), home: '/workspace', port: 8080,
    gradedFiles: ['work/**', 'work/.git/**', 'work/.*', 'explanation.m[d]', '.pl-seed/identity.jso[n]'],
  };
  delivery.gradingPayloads['demo/exr-a'] = {
    kind: 'workspace', uuid, grading: { method: 'manual' }, sourceRoot: 'projects/a',
    submission: { mode: 'workspace', workspaceOptions },
    seed: { schema: 'pl-git-workspace-seed-v1', archive: 'workspace/.pl-seed/starter.zip', manifest: 'workspace/.pl-seed/manifest.json' },
    upstreamGradingMethod: 'Manual', singleVariant: true,
  };
  await writeFile(file, JSON.stringify(delivery));
  assert.equal((await fixture(t, { settings })).bindings[0].delivery.gradingPayloads['demo/exr-a'].submission.workspaceOptions.image, workspaceOptions.image);
  workspaceOptions.image = 'docker.io/example/fixture:latest';
  await writeFile(file, JSON.stringify(delivery));
  await assert.rejects(fixture(t, { settings }));
});
