import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { completion } from '../../bridge/policy.mjs';

const source = await readFile(new URL('../../bridge/server.mjs', import.meta.url), 'utf8');
const body = source.slice(source.indexOf('async function workResults(request) {'), source.indexOf('async function workLaunch(request) {'));
const work = { id: 'lab', completion: { questionIds: ['fixture/q1'], requiredQuestionIds: ['fixture/q1'], atLeast: 1, fullyCompletedScore: 1 } };
const attempt = { id: '100', number: 1, points: 1, max_points: 4 };
const authorized = { attempt_id: '100', attempt_number: 1, qualified_id: 'fixture/q1', points: 2, max_points: 4, score: .5, native_status: 'complete', attempt_points: 2, attempt_max_points: 4 };
const newer = { ...authorized, attempt_id: '200', attempt_number: 2, points: 4, score: 1, attempt_points: 4 };
const request = { userUid: 'fixture-user', instance: 'fixture', deliveryHash: 'a'.repeat(64), workId: 'lab' };
for (const captured of [attempt, null]) {
  const db = { queryRows: async (_sql, params) => [params.assessment_instance_id === attempt.id ? authorized : newer] };
  const context = async () => ({ ci: { id: '1' }, user: { id: '1', uid: 'fixture-user' }, work, attemptRow: captured ? { attempt: captured } : null });
  const fn = new Function('nativeStudentWorkContext', 'db', 'sql', 'resultRow', 'workResultRow', 'completion', body + ';return workResults;')(context, db, { select_results: 'latest', select_work_results: 'captured' }, null, null, completion);
  const actual = await fn(request);
  if (captured) {
    assert.equal(actual.currentAttempt.id, attempt.id);
    assert.equal(actual.questions[0].points, authorized.points, 'New attempt created after authorization must not replace authorized question outcomes');
    assert.equal(actual.scoreGiven, authorized.attempt_points, 'Aggregate and questions must come from one captured-attempt query snapshot');
    assert.equal(actual.scoreMaximum, authorized.attempt_max_points);
    assert.equal(actual.completion.passed, false);
  } else {
    assert.equal(actual.currentAttempt, null);
    assert.equal(actual.scoreGiven, null);
    assert.equal(actual.questions[0].score, null, 'Attempt created after an unattempted snapshot must not invent question outcomes');
  }
}
console.log('PASS captured authorized attempt, coherent aggregate/questions, and unattempted snapshot');
