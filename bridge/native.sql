-- BLOCK migrate
CREATE TABLE IF NOT EXISTS public.pl_gateway_assignments (
  id text PRIMARY KEY,
  course_instance_id bigint NOT NULL REFERENCES course_instances (id),
  user_uid text NOT NULL,
  request jsonb NOT NULL,
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (course_instance_id, user_uid)
);

-- BLOCK lock
SELECT
  pg_advisory_xact_lock(hashtextextended ($lock_key, 0));

-- BLOCK select_assignment
SELECT
  request,
  updated_at::text AS activated_at
FROM
  pl_gateway_assignments
WHERE
  id = $id
FOR UPDATE;

-- BLOCK store_assignment
INSERT INTO
  pl_gateway_assignments (id, course_instance_id, user_uid, request, updated_at)
VALUES
  (
    $id,
    $course_instance_id,
    $user_uid,
    $request::jsonb,
    clock_timestamp()
  )
ON CONFLICT (id) DO UPDATE
SET
  request = EXCLUDED.request,
  updated_at = clock_timestamp();

-- BLOCK select_results
WITH
  current_attempt AS (
    SELECT
      ai.*
    FROM
      assessment_instances ai
      JOIN assessments a ON a.id = ai.assessment_id
    WHERE
      a.course_instance_id = $course_instance_id
      AND a.tid = $work_id
      AND a.deleted_at IS NULL
      AND ai.user_id = $user_id
      AND ai.team_id IS NULL
      AND ai.date >= $activated_at::timestamptz
    ORDER BY
      ai.number DESC,
      ai.id DESC
    LIMIT
      1
  )
SELECT
  ai.id::text AS attempt_id,
  ai.number AS attempt_number,
  q.qid AS qualified_id,
  iq.points,
  aq.max_points,
  iq.score_perc / 100.0 AS score,
  iq.status::text AS native_status
FROM
  current_attempt ai
  JOIN instance_questions iq ON iq.assessment_instance_id = ai.id
  JOIN assessment_questions aq ON aq.id = iq.assessment_question_id
  AND aq.deleted_at IS NULL
  JOIN questions q ON q.id = aq.question_id
  AND q.deleted_at IS NULL
WHERE
  q.qid = ANY ($question_ids::text[])
ORDER BY
  q.qid;

-- BLOCK validate_assessment
SELECT
  a.id::text AS id,
  array_agg(
    q.qid
    ORDER BY
      q.qid
  ) AS question_ids
FROM
  assessments a
  JOIN assessment_questions aq ON aq.assessment_id = a.id
  AND aq.deleted_at IS NULL
  JOIN questions q ON q.id = aq.question_id
  AND q.deleted_at IS NULL
WHERE
  a.course_instance_id = $course_instance_id
  AND a.tid = $work_id
  AND a.deleted_at IS NULL
GROUP BY
  a.id;

-- BLOCK select_slot
SELECT
  id
FROM
  pl_gateway_assignments
WHERE
  course_instance_id = $course_instance_id
  AND user_uid = $user_uid;

-- BLOCK select_work_attempt
SELECT
  to_jsonb(ai.*) AS attempt
FROM
  assessment_instances ai
  JOIN assessments a ON a.id = ai.assessment_id
WHERE
  a.course_instance_id = $course_instance_id
  AND a.tid = $work_id
  AND a.deleted_at IS NULL
  AND ai.user_id = $user_id
  AND ai.team_id IS NULL
ORDER BY
  ai.number DESC,
  ai.id DESC
LIMIT
  1;

-- BLOCK select_user_assignment
SELECT
  request,
  updated_at::text AS activated_at
FROM
  pl_gateway_assignments
WHERE
  course_instance_id = $course_instance_id
  AND user_uid = $user_uid;

-- BLOCK select_work_results
-- Bind the authorized attempt; one MVCC snapshot supplies its aggregate and
-- per-question outcomes even if a new native attempt is created concurrently.
SELECT
  ai.id::text AS attempt_id,
  ai.number AS attempt_number,
  ai.points AS attempt_points,
  ai.max_points AS attempt_max_points,
  q.qid AS qualified_id,
  iq.points,
  aq.max_points,
  iq.score_perc / 100.0 AS score,
  iq.status::text AS native_status
FROM
  assessment_instances ai
  JOIN assessments a ON a.id = ai.assessment_id
  AND a.deleted_at IS NULL
  JOIN instance_questions iq ON iq.assessment_instance_id = ai.id
  JOIN assessment_questions aq ON aq.id = iq.assessment_question_id
  AND aq.deleted_at IS NULL
  JOIN questions q ON q.id = aq.question_id
  AND q.deleted_at IS NULL
WHERE
  ai.id = $assessment_instance_id
  AND a.course_instance_id = $course_instance_id
  AND a.tid = $work_id
  AND ai.user_id = $user_id
  AND ai.team_id IS NULL
  AND q.qid = ANY ($question_ids::text[])
ORDER BY
  q.qid;
