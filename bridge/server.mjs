import {bridgeDeliverySchema} from './delivery.mjs';
import { readFile } from 'node:fs/promises';
import { createHash, timingSafeEqual } from 'node:crypto';
import { createServer } from 'node:http';
import { pathToFileURL } from 'node:url';
import * as db from '@prairielearn/postgres';
import { z } from 'zod';
import { BridgeError, resolveAssignment, assignmentTransition, completion, validateNativeGroups, assignedSlots } from './policy.mjs';
import {
  canonicalJSONString as canonical,
  validateBindings,
  assertProductionRuntime,
  authorizeAdministrator,
} from './policy.mjs';
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
const studentAccess = await native('lib/authz-data');
const nativeAssessment = await native('models/assessment');
const assessmentAccess = await native('lib/assessment-access-control/authz');
const { AssessmentInstanceSchema } = await native('lib/db-types');
const settingsSchema = z.strictObject({
  listenHost: z.string(),
  listenPort: z.number().int().min(1).max(65535),
  tokenFile: z.string(),
  administratorUid: z.union([z.string().regex(/^gw-[a-f0-9]{64}@example\.invalid$/), z.array(z.string().regex(/^gw-[a-f0-9]{64}@example\.invalid$/)).min(1)]).nullable().default(null),
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
const bindings = [];
for (const binding of settings.bindings) {
  const delivery = bridgeDeliverySchema.parse(
    JSON.parse(await readFile(`${binding.deliveryPath}/delivery.json`, 'utf8')),
  );
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
validateBindings(bindings);
await loadConfig([`${root}/config.json`]);
assertProductionRuntime(process.env.NODE_ENV, config);
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
  native_status: z.enum(['complete','unanswered','saved','correct','incorrect','grading','invalid']).nullable(),
  requires_manual_grading:z.boolean(),
  group_id: z.string(),
});
const workResultRow = resultRow.extend({
  attempt_points: z.number().nullable(),
  attempt_max_points: z.number().nullable(),
});
async function context(request, assignment = true) {
  const binding = bindings.find(
    (b) =>
      b.delivery.deliveryHash === request.deliveryHash && b.delivery.instances[request.instance],
  );
  if (!binding) throw new BridgeError(403, 'Unknown delivery/instance');
  if (assignment) resolveAssignment(request, binding.delivery);
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
  const groups = await db.queryRows(sql.validate_assessment,{course_instance_id:ci.id,work_id:workId},z.strictObject({group_id:z.string(),question_ids:z.array(z.string()),number_choose:z.number().int().nullable(),zone_id:z.string(),zone_best_questions:z.number().int().nullable(),zone_number_choose:z.number().int().nullable()}));
  validateNativeGroups(work,groups);
  return {...work,nativeGroups:groups};
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
    const attemptRow=await db.queryOptionalRow(sql.select_assignment_attempt,{course_instance_id:ci.id,work_id:work.id,user_id:user.id,activated_at:row.activated_at},z.strictObject({id:z.string(),number:z.number().int()}));
    const rows = attemptRow ? await db.queryRows(sql.select_results,{course_instance_id:ci.id,work_id:work.id,user_id:user.id,assessment_instance_id:attemptRow.id},resultRow) : [];
    const slots=assignedSlots(work,rows,attemptRow,work.nativeGroups);
    return {
      schemaVersion: 2,
      source: 'per-slot-results-v2',
      assignmentId: id,
      version,
      userUid: user.uid,
      instance: request.instance,
      deliveryHash: request.deliveryHash,
      workId: work.id,
      state: attemptRow ? 'started' : 'not-started',
      currentAttempt: attemptRow,
      slots,
      completion: completion(work, slots),
    };
  });
}
const workQuerySchema = z.strictObject({
  userUid: z.string().min(1).max(512),
  instance: z.string().min(1),
  deliveryHash: z.string().regex(/^[a-f0-9]{64}$/),
  workId: z.string().min(1),
});
async function nativeStudentWorkContext(request, allowAssignment = false) {
  const { binding, ci, user } = await context(request, false);
  if (!binding.delivery.instances[request.instance].works.includes(request.workId))
    throw new BridgeError(403, 'Work outside configured instance');
  const work = binding.delivery.works.find((w) => w.id === request.workId);
  if (!work?.completion || (!allowAssignment && work.policy?.assignment?.['student-label']))
    throw new BridgeError(403, 'Assignment-managed work requires assignment results');
  const enrollment = await enrollments.selectOptionalEnrollmentByUserId({
    userId: user.id,
    courseInstance: ci,
    authzData: system,
    requiredRole: ['System'],
  });
  if (!enrollment || enrollment.status !== 'joined')
    throw new BridgeError(403, 'Student enrollment required');
  const label = work.policy?.assignment?.['student-label'];
  if (label) {
    const slot = await db.queryOptionalRow(
      sql.select_user_assignment,
      { course_instance_id: ci.id, user_uid: user.uid },
      assignmentRow,
    );
    if (
      !slot ||
      slot.request.deliveryHash !== request.deliveryHash ||
      slot.request.newWork !== work.id ||
      slot.request.userUid !== user.uid
    )
      throw new BridgeError(403, 'Current assignment required');
    if (!(await labels.selectStudentLabelsForEnrollment(enrollment)).some((l) => l.name === label))
      throw new BridgeError(403, 'Current assignment label required');
  }
  const date = new Date();
  if (
    !ci.modern_publishing ||
    !(await studentAccess.calculateModernCourseInstanceStudentAccess(ci, user.id, date))
      .has_student_access_with_enrollment
  )
    throw new BridgeError(403, 'Native Student instance access denied');
  const nativeWork=await validateWork(binding, ci, work.id);
  const assessment = await nativeAssessment.selectAssessmentByTid({
    course_instance_id: ci.id,
    tid: work.id,
  });
  if (!assessment.modern_access_control || assessment.team_work)
    throw new BridgeError(409, 'Modern individual assessment required');
  const attemptRow = await db.queryOptionalRow(
    sql.select_work_attempt,
    { course_instance_id: ci.id, work_id: work.id, user_id: user.id },
    z.object({ attempt: AssessmentInstanceSchema }),
  );
  const authzData = {
    user: { id: user.id },
    mode: 'Public',
    course_role: 'None',
    course_instance_role: 'None',
    has_course_instance_permission_view: false,
  };
  const input = { assessment, userId: user.id, courseInstance: ci, authzData, reqDate: date };
  const access = attemptRow
    ? await assessmentAccess.resolveModernAssessmentInstanceAccess({
        ...input,
        assessmentInstance: attemptRow.attempt,
      })
    : await assessmentAccess.resolveModernAssessmentAccess(input);
  if (!access.authorized) throw new BridgeError(403, 'Native Student assessment access denied');
  return { binding, ci, user, work:nativeWork, assessment, attemptRow };
}
async function workResults(request) {
  const { ci, user, work, attemptRow } = await nativeStudentWorkContext(request);
  const attempt = attemptRow?.attempt;
  const rows = attempt ? await db.queryRows(
    sql.select_work_results,
    {
      course_instance_id: ci.id,
      work_id: work.id,
      user_id: user.id,
      assessment_instance_id: attempt.id,
    },
    workResultRow,
  ) : [];
  const currentAttempt=attempt?{id:attempt.id,number:attempt.number}:null;
  const slots=assignedSlots(work,rows,currentAttempt,work.nativeGroups);
  return {
    schemaVersion: 2,
    source: 'per-slot-results-v2',
    userUid: user.uid,
    instance: request.instance,
    deliveryHash: request.deliveryHash,
    workId: work.id,
    state: currentAttempt ? 'started' : 'not-started',
    currentAttempt,
    scoreGiven: rows[0]?.attempt_points ?? null,
    scoreMaximum: rows[0]?.attempt_max_points ?? null,
    slots,
    completion: completion(work, slots),
  };
}
async function workLaunch(request) {
  const { ci, user, work, assessment } = await nativeStudentWorkContext(request, true);
  return {
    workId: work.id,
    userUid: user.uid,
    instance: request.instance,
    deliveryHash: request.deliveryHash,
    path: `/pl/course_instance/${ci.id}/assessment/${assessment.id}/`,
  };
}
const enrollmentQuerySchema = workQuerySchema.omit({ workId: true });
async function grantAdministrator(request) {
  const uid = authorizeAdministrator(request.userUid, settings.administratorUid);
  const user = await users.selectOptionalUserByUid(uid);
  if (!user) throw new BridgeError(404, 'Verified user must exist');
  const answer = await db.queryRow(sql.grant_administrator, {uid, user_id: user.id}, z.object({administrator: z.boolean()}));
  if (!answer.administrator) throw new BridgeError(409, 'Administrator bootstrap failed');
  return {schemaVersion:1, userUid:uid, administrator:true, path:'/pl/administrator/courses'};
}
async function enrollBasic(request) {
  const { ci, user } = await context(request, false);
  return db.runInTransactionAsync(async () => {
    await db.execute(sql.lock, { lock_key: `gateway:${ci.id}:${user.uid}` });
    const prior = await enrollments.selectOptionalEnrollmentByUserId({
      userId: user.id,
      courseInstance: ci,
      authzData: system,
      requiredRole: ['System'],
    });
    if (prior?.status === 'blocked') throw new BridgeError(403, 'Blocked enrollment');
    const enrollment = await enrollments.ensureUncheckedEnrollment({
      userId: user.id,
      courseInstance: ci,
      authzData: system,
      requiredRole: ['System'],
      actionDetail: 'implicit_joined',
    });
    if (!enrollment || enrollment.status !== 'joined')
      throw new BridgeError(403, 'Enrollment unavailable');
    if (
      !ci.modern_publishing ||
      !(await studentAccess.calculateModernCourseInstanceStudentAccess(ci, user.id, new Date()))
        .has_student_access_with_enrollment
    )
      throw new BridgeError(403, 'Native Student instance access denied');
    return {
      schemaVersion: 1,
      userUid: user.uid,
      instance: request.instance,
      deliveryHash: request.deliveryHash,
      enrolled: true,
    };
  });
}
async function readBody(req, schema) {
  let body = '';
  for await (const chunk of req) {
    body += chunk;
    if (Buffer.byteLength(body) > 8192) throw new BridgeError(413, 'Body too large');
  }
  return schema.parse(JSON.parse(body));
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
    } else if (req.method === 'GET' && url.pathname === '/internal/gateway/work-results') {
      if ([...url.searchParams.keys()].sort().join(',') !== 'deliveryHash,instance,userUid,workId')
        throw new BridgeError(400, 'Invalid work result query');
      answer = await workResults(workQuerySchema.parse(Object.fromEntries(url.searchParams)));
    } else if (req.method === 'GET' && url.pathname === '/internal/gateway/work-launch') {
      if ([...url.searchParams.keys()].sort().join(',') !== 'deliveryHash,instance,userUid,workId')
        throw new BridgeError(400, 'Invalid work launch query');
      answer = await workLaunch(workQuerySchema.parse(Object.fromEntries(url.searchParams)));
    } else if (req.method === 'PUT' && url.pathname === '/internal/gateway/enrollment') {
      if ([...url.searchParams.keys()].length)
        throw new BridgeError(400, 'Unexpected enrollment query');
      answer = await enrollBasic(await readBody(req, enrollmentQuerySchema));
    } else if (req.method === 'PUT' && url.pathname === '/internal/gateway/administrator') {
      if ([...url.searchParams.keys()].length) throw new BridgeError(400, 'Unexpected administrator query');
      answer = await grantAdministrator(await readBody(req, z.strictObject({userUid:z.string().min(1).max(512)})));
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
