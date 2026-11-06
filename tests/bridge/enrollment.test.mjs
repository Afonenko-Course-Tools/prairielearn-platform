import assert from 'node:assert/strict';
import { readFile, mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { Readable } from 'node:stream';
import { timingSafeEqual } from 'node:crypto';
import { test } from 'node:test';
import { z } from 'zod';
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
  const path = await mkdtemp(join(tmpdir(), 'bridge-auth-only-'));
  t.after(() => rm(path, { recursive: true, force: true }));
  await writeFile(join(path, 'token'), token);
  const settings = options.settings ?? {
    listenHost: '127.0.0.1', listenPort: 3001,
    tokenFile: join(path, 'token'), bindings: [binding],
  };
  settings.tokenFile = join(path, 'token');
  await writeFile(join(path, 'config.json'), JSON.stringify(settings));
  const ci = { id: '73', course_id: '7', uuid, short_name: 'fall', deleted_at: null, modern_publishing: true, ...options.ci };
  const state = { migrations: 0, enrollmentWrites: [], locks: [], nativeReads: 0, bodyReads: 0, queries: 0,
    courseGrants: [], instanceGrants: [], administrators: new Set(), courseRole: options.courseRole ?? null, instanceRole: null };
  let handler;
  const args = {
    z, readFile, ...policy, Buffer, URL, timingSafeEqual,
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
    instances: { selectCourseInstanceById: async id => { state.nativeReads++; assert.equal(id, '73'); if (options.nativeError) throw Error('private-db-password ' + token); return ci; } },
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
    createServer: fn => { handler = fn; return {}; },
  };
  const parsed = await new AsyncFunction(...Object.keys(args), core + ';return {settings, bindings};')(...Object.values(args));
  return { ...parsed, state, async send(options = {}) {
    const body = options.body ?? loginRequest;
    const req = Readable.from([typeof body === 'string' ? body : JSON.stringify(body)]);
    const iterate = req[Symbol.asyncIterator].bind(req);
    req[Symbol.asyncIterator] = () => { state.bodyReads++; return iterate(); };
    req.method = options.method ?? 'PUT';
    req.url = options.url ?? '/internal/gateway/enrollment';
    req.headers = { authorization: options.authorization ?? `Bearer ${token}` };
    let status, headers, answer;
    await handler(req, { writeHead(code, values) { status = code; headers = values; return this; }, end(value) { answer = JSON.parse(value); } });
    return { status, headers, body: answer };
  } };
}

test('auth-only запускается без delivery и сохраняет прежние UID без assignment DDL', async t => {
  let f;
  await assert.doesNotReject(async () => { f = await fixture(t); });
  assert.equal(f.state.migrations, 0);
  for (const userUid of ['student@fixture.invalid', 'teacher@fixture.invalid']) {
    for (let i = 0; i < 2; i++) {
      const result = await f.send({ body: { ...loginRequest, userUid } });
      assert.equal(result.status, 200);
      assert.equal(result.headers['Cache-Control'], 'no-store');
      assert.deepEqual(result.body, { schemaVersion: 1, ...request, userUid, enrolled: true, path: '/pl/course_instance/73/assessments' });
    }
  }
  assert.deepEqual(f.state.enrollmentWrites.map(value => value.userId), ['21', '21', '22', '22']);
  assert.equal(f.state.queries, 0);
  assert.deepEqual(f.state.locks, [
    { lock_key: 'gateway:73:student@fixture.invalid' }, { lock_key: 'gateway:73:student@fixture.invalid' },
    { lock_key: 'gateway:73:teacher@fixture.invalid' }, { lock_key: 'gateway:73:teacher@fixture.invalid' },
  ]);
  assert.deepEqual(f.state.courseGrants, []);
  assert.deepEqual(f.state.instanceGrants, []);
});

test('auth-only отклоняет остальные routes до body parsing и native операций', async t => {
  const f = await fixture(t);
  for (const [method, url] of [
    ['PUT', '/internal/gateway/assignments/a'], ['GET', '/internal/gateway/grades'], ['GET', '/internal/gateway/results'],
    ['GET', '/internal/gateway/work-results'], ['GET', '/internal/gateway/work-launch'],
    ['PUT', '/internal/gateway/administrator'], ['GET', '/internal/gateway/enrollment'],
    ['POST', '/internal/gateway/enrollment'], ['PUT', '/internal/gateway/enrollment/'],
  ]) assert.equal((await f.send({ method, url, body: '{' })).status, 404);
  assert.equal(f.state.bodyReads, 0);
  assert.equal(f.state.nativeReads, 0);
  assert.equal(f.state.queries, 0);
  assert.deepEqual(f.state.enrollmentWrites, []);
});

test('auth-only сохраняет bearer, query и strict enrollment body guards', async t => {
  const f = await fixture(t);
  assert.equal((await f.send({ authorization: 'Bearer wrong' })).status, 401);
  for (const query of ['?workId=lab', '?', '?='])
    assert.equal((await f.send({ url: '/internal/gateway/enrollment' + query })).status, 400);
  assert.equal((await f.send({ body: request })).status, 400);
  assert.equal((await f.send({ body: '{' })).status, 400);
  const oversized = await f.send({ body: ' '.repeat(8193) });
  assert.equal(oversized.status, 413);
  assert.equal(oversized.headers['Cache-Control'], 'no-store');
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
]) test(`auth-only отклоняет: ${name}`, async t => {
  const f = await fixture(t, options);
  const result = await f.send({ body: { ...loginRequest, ...body } });
  assert.equal(result.status, status);
  assert.equal(result.body.path, undefined);
  assert.equal(f.state.queries, 0);
  if (['неизвестный courseKey', 'неизвестный instance', 'native CIID', 'native course ID', 'native UUID', 'native short_name', 'deleted instance', 'отсутствующий UID', 'blocked membership'].includes(name)) assert.deepEqual(f.state.enrollmentWrites, []);
});

test('auth-only config закрыт, bindings однозначны и сохраняется production guard', async t => {
  const base = { listenHost: '127.0.0.1', listenPort: 3001, bindings: [binding] };
  for (const settings of [
    { ...base, mode: 'login-only' }, { ...base, administratorUid: null }, { ...base, bindings: [{ ...binding, deliveryPath: '/candidate' }] },
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
  const settings = { listenHost: '127.0.0.1', listenPort: 3001, administratorEmail: 'owner@fixture.invalid', bindings: [binding] };
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
  const settings = { listenHost: '127.0.0.1', listenPort: 3001, administratorEmail: 'owner@fixture.invalid', bindings: [binding] };
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

test('старые delivery settings запрещены до native чтений', async t => {
  await assert.rejects(fixture(t, { settings: {
    listenHost: '127.0.0.1', listenPort: 3001,
    bindings: [{ deliveryPath: '/nonexistent', courseInstanceId: '73' }],
  } }), error => error instanceof z.ZodError);
});

test('Student сохраняет ранее выданные Teacher права без нового grant', async t => {
  const f = await fixture(t);
  assert.equal((await f.send({ body: { ...loginRequest, userUid: 'teacher@fixture.invalid', role: 'teacher' } })).status, 200);
  assert.equal((await f.send({ body: { ...loginRequest, userUid: 'teacher@fixture.invalid' } })).status, 200);
  assert.equal(f.state.courseRole, 'Editor');
  assert.equal(f.state.instanceRole, 'Student Data Editor');
  assert.equal(f.state.courseGrants.length, 1);
  assert.equal(f.state.instanceGrants.length, 1);
});

test('native ошибки скрыты и не раскрывают токен', async t => {
  const f = await fixture(t, { nativeError: true });
  const result = await f.send();
  assert.equal(result.status, 500);
  assert.deepEqual(result.body, { error: 'Bridge operation failed' });
  assert.equal(result.headers['Cache-Control'], 'no-store');
});

test('canonical settings example запускает auth-only Bridge без delivery конфигурации', async t => {
  const example = JSON.parse(await readFile(new URL('../../config/pl.gateway.example.json', import.meta.url), 'utf8'));
  const schema = new Function('z', 'isCanonicalEmail',
    source.slice(source.indexOf('const settingsSchema ='), source.indexOf('const settings =')) + ';return settingsSchema;')(z, policy.isCanonicalEmail);
  schema.parse(example);
  const f = await fixture(t, { settings: example });
  assert.equal(f.state.migrations, 0);
  assert.equal(f.state.nativeReads, 0);
  assert.deepEqual(f.bindings, example.bindings);
});

test('settings example не допускает прежние delivery и login-only варианты', async t => {
  for (const settings of [
    { listenHost: '0.0.0.0', listenPort: 3001, administratorUid: null, bindings: [{ deliveryPath: '/course-deliveries/approved', courseInstanceId: '1' }] },
    { mode: 'login-only', listenHost: '0.0.0.0', listenPort: 3001, administratorEmail: 'owner@fixture.invalid', bindings: [binding] },
  ]) await assert.rejects(fixture(t, { settings }), error => error instanceof z.ZodError);
});
