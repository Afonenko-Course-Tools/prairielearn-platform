import { readFile } from 'node:fs/promises';
import { createHash, timingSafeEqual } from 'node:crypto';
import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';
import * as db from '@prairielearn/postgres';
import { z } from 'zod';
import { BridgeError, resolveAssignment, assignmentTransition, completion } from './policy.mjs';
const root = process.env.PL_ROOT ?? '/PrairieLearn';
const native = (path) => import(pathToFileURL(`${root}/apps/prairielearn/dist/${path}.js`).href);
const [
  { config, loadConfig },
  enrollments,
  labels,
  users,
  instances,
  { dangerousFullSystemAuthz },
] = await Promise.all([
  native('lib/config'),
  native('models/enrollment'),
  native('models/student-label'),
  native('models/user'),
  native('models/course-instances'),
  native('lib/authz-data-lib'),
]);
const settingsSchema = z.strictObject({
  listenHost: z.string(),
  listenPort: z.number().int().min(1).max(65535),
  tokenFile: z.string(),
  bindings: z
    .array(
      z.strictObject({
        deliveryPath: z.string(),
        courseInstanceId: z.string().regex(/^[1-9][0-9]*$/),
      }),
    )
    .min(1),
});
const settings = settingsSchema.parse(
  JSON.parse(await readFile(process.env.PL_GATEWAY_CONFIG, 'utf8')),
);
const token = (await readFile(settings.tokenFile, 'utf8')).trim();
if (token.length < 32) throw new Error('Service token needs at least 32 characters');
const canonical = (value) =>
  JSON.stringify(
    value && typeof value === 'object'
      ? Array.isArray(value)
        ? value.map((v) => JSON.parse(canonical(v)))
        : Object.fromEntries(
            Object.keys(value)
              .sort()
              .map((k) => [k, JSON.parse(canonical(value[k]))]),
          )
      : value,
  );
const bindings = [];
for (const binding of settings.bindings) {
  const delivery = JSON.parse(await readFile(`${binding.deliveryPath}/delivery.json`, 'utf8'));
  const { deliveryHash, ...payload } = delivery;
  if (createHash('sha256').update(canonical(payload)).digest('hex') !== deliveryHash)
    throw new Error('Delivery hash mismatch');
  for (const [path, hash] of Object.entries(delivery.files)) {
    if (path.startsWith('/') || path.split('/').includes('..'))
      throw new Error('Unsafe delivery path');
    if (
      createHash('sha256')
        .update(await readFile(`${binding.deliveryPath}/${path}`))
        .digest('hex') !== hash
    )
      throw new Error('Delivery file mismatch');
  }
  bindings.push({ ...binding, delivery });
}
await loadConfig([`${root}/config.json`]);
await db.initAsync(
  {
    user: config.postgresqlUser,
    database: config.postgresqlDatabase,
    host: config.postgresqlHost,
    password: config.postgresqlPassword ?? undefined,
    max: 4,
  },
  () => {
    process.exitCode = 1;
  },
);
await db.setRandomSearchSchemaAsync('gateway-bridge');
await (await native('sprocs/index')).init();
const sql = db.loadSqlEquiv(new URL('./native.mjs', import.meta.url).href);
await db.execute(sql.migrate, {});
const system = dangerousFullSystemAuthz();
const requestSchema = z.strictObject({
  version: z.number().int().positive(),
  userUid: z.string().min(1).max(512),
  instance: z.string().min(1),
  deliveryHash: z.string().regex(/^[a-f0-9]{64}$/),
  oldWork: z.string().nullable(),
  newWork: z.string().nullable(),
});
const idSchema = z.string().regex(/^[A-Za-z0-9_-]{1,128}$/);
const assignmentRow = z.object({ request: requestSchema, activated_at: z.string() });
const resultRow = z.strictObject({
  attempt_id: z.string(),
  attempt_number: z.number().int(),
  qualified_id: z.string(),
  points: z.number().nullable(),
  max_points: z.number().nullable(),
  score: z.number().nullable(),
  native_status: z.string(),
});
async function context(request) {
  const binding = bindings.find(
    (b) =>
      b.delivery.deliveryHash === request.deliveryHash && b.delivery.instances[request.instance],
  );
  if (!binding) throw new BridgeError(403, 'Unknown delivery/instance');
  resolveAssignment(request, binding.delivery);
  const ci = await instances.selectCourseInstanceById(binding.courseInstanceId);
  if (ci.deleted_at !== null) throw new BridgeError(403, 'Deleted instance');
  const instanceInfo = JSON.parse(
    await readFile(
      `${binding.deliveryPath}/courseInstances/${request.instance}/infoCourseInstance.json`,
      'utf8',
    ),
  );
  if (ci.uuid !== instanceInfo.uuid)
    throw new BridgeError(403, 'Native instance differs from delivery');
  const user = await users.selectOptionalUserByUid(request.userUid);
  if (!user) throw new BridgeError(404, 'Verified user must exist');
  return { binding, ci, user };
}
async function validateWork(binding, ci, workId) {
  const work = binding.delivery.works.find((w) => w.id === workId);
  const row = await db.queryOptionalRow(
    sql.validate_assessment,
    { course_instance_id: ci.id, work_id: workId },
    z.object({ id: z.string(), question_ids: z.array(z.string()) }),
  );
  if (
    !row ||
    canonical([...new Set(row.question_ids)].sort()) !==
      canonical([...work.completion.questionIds].sort())
  )
    throw new BridgeError(409, 'Native assessment differs from manifest');
  return work;
}
async function apply(id, request) {
  const { binding, ci, user } = await context(request);
  if (request.newWork !== null) await validateWork(binding, ci, request.newWork);
  return db.runInTransactionAsync(async () => {
    await db.execute(sql.lock, { lock_key: `gateway:${ci.id}:${request.userUid}` });
    const slot = await db.queryOptionalRow(
      sql.select_slot,
      { course_instance_id: ci.id, user_uid: user.uid },
      z.object({ id: z.string() }),
    );
    if (slot && slot.id !== id) throw new BridgeError(409, 'Assignment slot already bound');
    const prior = await db.queryOptionalRow(sql.select_assignment, { id }, assignmentRow);
    const transition = assignmentTransition(request, prior?.request ?? null);
    const enrollment = await enrollments.ensureUncheckedEnrollment({
      userId: user.id,
      courseInstance: ci,
      authzData: system,
      requiredRole: ['System'],
      actionDetail: 'implicit_joined',
    });
    if (!enrollment || enrollment.status !== 'joined')
      throw new BridgeError(403, 'Enrollment unavailable');
    const managed = new Set(
      binding.delivery.instances[request.instance].works
        .map(
          (id) =>
            binding.delivery.works.find((w) => w.id === id)?.policy?.assignment?.['student-label'],
        )
        .filter(Boolean),
    );
    const allLabels = await labels.selectStudentLabelsInCourseInstance(ci);
    const target =
      request.newWork === null
        ? null
        : binding.delivery.works.find((w) => w.id === request.newWork).policy.assignment[
            'student-label'
          ];
    if (target && !allLabels.some((l) => l.name === target))
      throw new BridgeError(409, 'Native label missing');
    for (const label of allLabels.filter((l) => managed.has(l.name))) {
      if (label.name === target)
        await labels.addLabelToEnrollment({ enrollment, label, authzData: system });
      else await labels.removeLabelFromEnrollment({ enrollment, label, authzData: system });
    }
    const actual = (await labels.selectStudentLabelsForEnrollment(enrollment))
      .filter((l) => managed.has(l.name))
      .map((l) => l.name);
    if (canonical(actual.sort()) !== canonical(target ? [target] : []))
      throw new BridgeError(409, 'ACL reconciliation failed');
    if (transition === 'apply')
      await db.execute(sql.store_assignment, {
        id,
        course_instance_id: ci.id,
        user_uid: user.uid,
        request: JSON.stringify(request),
      });
    return {
      schemaVersion: 1,
      id,
      ...request,
      reconciled: true,
      duplicate: transition === 'duplicate',
    };
  });
}
async function results(id, version) {
  return db.runInTransactionAsync(async () => {
    const row = await db.queryOptionalRow(sql.select_assignment, { id }, assignmentRow);
    if (!row || row.request.version !== version || !row.request.newWork)
      throw new BridgeError(409, 'Inactive or stale assignment');
    const request = row.request;
    const { binding, ci, user } = await context(request);
    const enrollment = await enrollments.selectOptionalEnrollmentByUserId({
      userId: user.id,
      courseInstance: ci,
      authzData: system,
      requiredRole: ['System'],
    });
    const work = await validateWork(binding, ci, request.newWork);
    const label = work.policy.assignment['student-label'];
    if (
      !enrollment ||
      enrollment.status !== 'joined' ||
      !(await labels.selectStudentLabelsForEnrollment(enrollment)).some((l) => l.name === label)
    )
      throw new BridgeError(403, 'Assignment ACL absent');
    const rows = await db.queryRows(
      sql.select_results,
      {
        course_instance_id: ci.id,
        work_id: work.id,
        user_id: user.id,
        question_ids: work.completion.questionIds,
        activated_at: row.activated_at,
      },
      resultRow,
    );
    const questions = work.completion.questionIds.map((qualifiedId) => {
      const r = rows.find((r) => r.qualified_id === qualifiedId);
      return {
        qualifiedId,
        score: r?.score ?? null,
        points: r?.points ?? null,
        maxPoints: r?.max_points ?? null,
        status:
          r && ['complete', 'correct', 'incorrect'].includes(r.native_status)
            ? 'complete'
            : r?.native_status === 'grading'
              ? 'grading'
              : 'unanswered',
      };
    });
    return {
      schemaVersion: 1,
      source: 'per-question-results-v1',
      assignmentId: id,
      version,
      userUid: user.uid,
      instance: request.instance,
      deliveryHash: request.deliveryHash,
      workId: work.id,
      currentAttempt: rows.length
        ? { id: rows[0].attempt_id, number: rows[0].attempt_number }
        : null,
      questions,
      completion: completion(work, questions),
    };
  });
}
const server = createServer(async (req, res) => {
  try {
    const supplied = Buffer.from(req.headers.authorization ?? '');
    const expected = Buffer.from(`Bearer ${token}`);
    if (supplied.length !== expected.length || !timingSafeEqual(supplied, expected))
      throw new BridgeError(401, 'Service authentication required');
    const url = new URL(req.url, 'http://bridge');
    let answer;
    const match = url.pathname.match(/^\/internal\/gateway\/assignments\/([^/]+)$/);
    if (req.method === 'PUT' && match) {
      const id = idSchema.parse(match[1]);
      let body = '';
      for await (const chunk of req) {
        body += chunk;
        if (Buffer.byteLength(body) > 8192) throw new BridgeError(413, 'Body too large');
      }
      answer = await apply(id, requestSchema.parse(JSON.parse(body)));
    } else if (req.method === 'GET' && url.pathname === '/internal/gateway/results') {
      if ([...url.searchParams.keys()].sort().join(',') !== 'assignmentId,version')
        throw new BridgeError(400, 'Invalid result query');
      const id = idSchema.parse(url.searchParams.get('assignmentId'));
      const version = z.coerce.number().int().positive().parse(url.searchParams.get('version'));
      answer = await results(id, version);
    } else throw new BridgeError(404, 'Unknown route');
    res
      .writeHead(200, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
      .end(JSON.stringify(answer));
  } catch (error) {
    const status =
      error instanceof BridgeError
        ? error.status
        : error instanceof z.ZodError || error instanceof SyntaxError
          ? 400
          : 500;
    // Details and native database errors must not disclose private results or credentials.
    res
      .writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' })
      .end(JSON.stringify({ error: status === 500 ? 'Bridge operation failed' : error.message }));
  }
});
server.listen(settings.listenPort, settings.listenHost, () =>
  console.log('Community gateway bridge ready'),
);
process.on('SIGTERM', () => server.close(() => void db.closeAsync().then(() => process.exit(0))));
