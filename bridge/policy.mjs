export class BridgeError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
  }
}
const fail = (message) => {
  throw new BridgeError(409, message);
};
export function resolveAssignment(request, delivery) {
  const keys = ['version', 'userUid', 'instance', 'deliveryHash', 'oldWork', 'newWork'];
  if (
    !request ||
    Object.keys(request).length !== keys.length ||
    keys.some((k) => !Object.hasOwn(request, k))
  )
    fail('Invalid assignment fields');
  if (
    !Number.isSafeInteger(request.version) ||
    request.version < 1 ||
    typeof request.userUid !== 'string' ||
    !request.userUid.length ||
    request.userUid.length > 512 ||
    typeof request.instance !== 'string'
  )
    fail('Invalid identity or version');
  if (
    request.deliveryHash !== delivery.deliveryHash ||
    !/^[a-f0-9]{64}$/.test(request.deliveryHash)
  )
    fail('Delivery mismatch');
  const instance = delivery.instances[request.instance];
  if (!instance) fail('Instance not in delivery');
  const resolve = (id) => {
    if (id === null) return null;
    if (typeof id !== 'string' || !instance.works.includes(id)) fail('Work not in instance');
    const work = delivery.works.find((w) => w.id === id);
    const label = work?.policy?.assignment?.['student-label'];
    if (
      !label ||
      !work.completion ||
      work.completion.questionIds.some((q) => !delivery.questions.includes(q))
    )
      fail('Work is not bridge ready');
    return label;
  };
  return { oldLabel: resolve(request.oldWork), newLabel: resolve(request.newWork) };
}
export function assignmentTransition(request, prior) {
  if (!prior) {
    if (request.version !== 1 || request.oldWork !== null)
      fail('First assignment must start at version one');
    return 'apply';
  }
  for (const key of ['userUid', 'instance'])
    if (request[key] !== prior[key]) fail('Assignment identity is immutable');
  if (request.version === prior.version) {
    if (['deliveryHash', 'oldWork', 'newWork'].some((k) => request[k] !== prior[k]))
      fail('Version conflict');
    return 'duplicate';
  }
  if (request.version !== prior.version + 1 || request.oldWork !== prior.newWork)
    fail('Stale assignment transition');
  // Cross-delivery replacement needs an explicit migration of its old ACL binding.
  if (request.deliveryHash !== prior.deliveryHash) fail('Delivery migration required');
  return 'apply';
}
export function completion(work, rows) {
  const c = work.completion;
  const seen = new Set();
  let count = 0;
  for (const row of rows) {
    if (!c.questionIds.includes(row.qualifiedId) || seen.has(row.qualifiedId))
      fail('Unscoped or duplicate result');
    seen.add(row.qualifiedId);
    if (row.score !== null && (!Number.isFinite(row.score) || row.score < 0 || row.score > 1))
      fail('Invalid result score');
    if (
      c.requiredQuestionIds.includes(row.qualifiedId) &&
      row.score === c.fullyCompletedScore &&
      row.status === 'complete'
    )
      count++;
  }
  return {
    completedRequired: count,
    requiredCount: c.requiredQuestionIds.length,
    atLeast: c.atLeast,
    passed: count >= c.atLeast,
  };
}
