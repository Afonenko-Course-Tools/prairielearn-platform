-- BLOCK lock_ai
-- Same native AI lock/order as manualGrading; no open-state mutation.
SELECT
    c.id::text AS "courseId",
    c.path AS "coursePath",
    ci.uuid::text AS "courseInstanceUUID",
    ci.id::text AS "courseInstanceId",
    a.tid AS "workId",
    a.uuid::text AS "assessmentUUID",
    a.id::text AS "assessmentId",
    ai.id::text AS "assessmentInstanceId",
    u.id::text AS "userId",
    u.uid,
    ai.open,
    EXISTS(
        SELECT 1 FROM administrators
        WHERE user_id = $actor
    ) AS administrator
FROM assessment_instances ai JOIN assessments a ON a.id = ai.assessment_id
JOIN course_instances ci ON ci.id = a.course_instance_id
JOIN courses c ON c.id = ci.course_id
JOIN users u ON u.id = ai.user_id
WHERE
    ai.id = $assessment_instance_id
    AND ai.team_id IS NULL
    AND a.deleted_at IS NULL
FOR NO KEY UPDATE OF ai;

-- BLOCK context
SELECT
    c.id::text AS "courseId",
    c.path AS "coursePath",
    ci.uuid::text AS "courseInstanceUUID",
    ci.id::text AS "courseInstanceId",
    a.tid AS "workId",
    a.uuid::text AS "assessmentUUID",
    a.id::text AS "assessmentId",
    ai.id::text AS "assessmentInstanceId",
    u.id::text AS "userId",
    u.uid,
    q.uuid::text AS "questionUUID",
    q.id::text AS "questionId",
    aq.id::text AS "assessmentQuestionId",
    iq.id::text AS "instanceQuestionId",
    a.allow_personal_notes,
    iq.open,
    iq.modified_at,
    iq.points,
    iq.auto_points,
    iq.manual_points,
    iq.score_perc,
    iq.status::text AS status,
    iq.requires_manual_grading,
    aq.max_points,
    aq.max_auto_points,
    aq.max_manual_points
FROM instance_questions iq
JOIN assessment_instances ai ON ai.id = iq.assessment_instance_id
JOIN
    assessment_questions aq
    ON aq.id = iq.assessment_question_id AND aq.assessment_id = ai.assessment_id
JOIN assessments a ON a.id = ai.assessment_id
JOIN questions q ON q.id = aq.question_id
JOIN course_instances ci ON ci.id = a.course_instance_id
JOIN courses c ON c.id = ci.course_id
JOIN users u ON u.id = ai.user_id
WHERE
    iq.id = $instanceQuestionId
    AND ai.id = $assessment_instance_id
    AND ai.team_id IS NULL
    AND aq.deleted_at IS NULL AND a.deleted_at IS NULL AND q.deleted_at IS NULL;

-- BLOCK readback
SELECT
    c.id::text AS "courseId",
    c.path AS "coursePath",
    ci.uuid::text AS "courseInstanceUUID",
    ci.id::text AS "courseInstanceId",
    a.tid AS "workId",
    a.uuid::text AS "assessmentUUID",
    a.id::text AS "assessmentId",
    ai.id::text AS "assessmentInstanceId",
    u.id::text AS "userId",
    u.uid,
    q.uuid::text AS "questionUUID",
    q.id::text AS "questionId",
    aq.id::text AS "assessmentQuestionId",
    iq.id::text AS "instanceQuestionId",
    a.allow_personal_notes,
    iq.open,
    iq.modified_at,
    iq.points,
    iq.auto_points,
    iq.manual_points,
    iq.score_perc,
    iq.status::text AS status,
    iq.requires_manual_grading,
    aq.max_points,
    aq.max_auto_points,
    aq.max_manual_points
FROM instance_questions iq
JOIN assessment_instances ai ON ai.id = iq.assessment_instance_id
JOIN
    assessment_questions aq
    ON aq.id = iq.assessment_question_id AND aq.assessment_id = ai.assessment_id
JOIN assessments a ON a.id = ai.assessment_id
JOIN questions q ON q.id = aq.question_id
JOIN course_instances ci ON ci.id = a.course_instance_id
JOIN courses c ON c.id = ci.course_id
JOIN users u ON u.id = ai.user_id
WHERE
    iq.id = $instanceQuestionId
    AND ai.id = $assessment_instance_id
    AND ai.team_id IS NULL
    AND aq.deleted_at IS NULL AND a.deleted_at IS NULL AND q.deleted_at IS NULL;

-- BLOCK source_success
-- Original auto job and raw answer remain untouched. No text feedback can grant credit.
SELECT
    CURRENT_DATABASE() AS database,
    gj.id::text AS "autoJobId",
    s.id::text AS "submissionId",
    v.id::text AS "variantId",
    iq.id::text AS "instanceQuestionId",
    ai.id::text AS "assessmentInstanceId",
    q.uuid::text AS "questionUUID",
    a.uuid::text AS "workUUID",
    u.id::text AS "userId",
    u.uid,
    gj.grading_method::text,
    gj.graded_at,
    gj.grading_request_canceled_at,
    gj.deleted_at,
    gj.gradable,
    gj.correct,
    gj.score,
    s.broken AS submission_broken,
    s.raw_submitted_answer AS raw_answer,
    gj.feedback AS auto_feedback,
    gj.output AS auto_output,
    gj.grading_finished_at
FROM grading_jobs gj
JOIN submissions s ON s.id = gj.submission_id
JOIN variants v ON v.id = s.variant_id
JOIN instance_questions iq ON iq.id = v.instance_question_id
JOIN assessment_instances ai ON ai.id = iq.assessment_instance_id
JOIN assessment_questions aq ON aq.id = iq.assessment_question_id
JOIN questions q ON q.id = aq.question_id
JOIN assessments a ON a.id = ai.assessment_id JOIN users u ON u.id = ai.user_id
WHERE
    gj.id = $autoJobId
    AND ai.team_id IS NULL
    AND v.user_id = ai.user_id
    AND v.team_id IS NULL
    AND v.question_id = q.id;

-- BLOCK existing_event
SELECT
    id::text,
    authn_user_id::text,
    new_state AS record
FROM audit_logs
WHERE
    table_name = 'instance_questions'
    AND row_id = $instance_question_id
    AND action = 'recognized_credit'
ORDER BY id;

-- BLOCK insert_event
INSERT INTO audit_logs (
    authn_user_id,
    user_id,
    course_instance_id,
    table_name,
    row_id,
    action,
    new_state
)
VALUES (
    $actor,
    $userId,
    $courseInstanceId,
    'instance_questions',
    $instanceQuestionId,
    'recognized_credit',
    $record::jsonb
)
RETURNING id::text, authn_user_id::text, new_state AS record;

-- BLOCK recognized_events
SELECT
    al.id::text,
    al.authn_user_id::text,
    al.new_state AS record
FROM audit_logs al JOIN instance_questions iq ON iq.id = al.row_id
WHERE
    al.table_name = 'instance_questions'
    AND al.action = 'recognized_credit'
    AND iq.assessment_instance_id = $assessment_instance_id
ORDER BY iq.id, al.id;

-- BLOCK repair
WITH repaired AS (
    UPDATE instance_questions iq SET
        points = aq.max_points,
        auto_points = COALESCE(aq.max_auto_points, 0),
        manual_points = COALESCE(aq.max_manual_points, 0),
        score_perc = 100,
        status = 'complete',
        requires_manual_grading = FALSE,
        last_grader = $actor,
        modified_at = NOW(),
        is_ai_graded = FALSE
    FROM
        assessment_questions aq
    WHERE
        iq.id = $instance_question_id
        AND iq.assessment_instance_id = $assessment_instance_id
        AND aq.id = iq.assessment_question_id
    RETURNING
        iq.id,
        iq.points,
        iq.auto_points,
        iq.manual_points,
        iq.score_perc,
        aq.max_points,
        aq.max_auto_points,
        aq.max_manual_points
)

INSERT INTO question_score_logs (
    instance_question_id,
    auth_user_id,
    max_points,
    max_manual_points,
    max_auto_points,
    points,
    score_perc,
    auto_points,
    manual_points
)
SELECT
    id,
    $actor,
    max_points,
    max_manual_points,
    max_auto_points,
    points,
    score_perc,
    auto_points,
    manual_points
FROM repaired;

-- BLOCK insert_manual_job
-- Explicit Manual recognition event; no submission UPDATE and no autograder.
INSERT INTO grading_jobs (
    submission_id,
    auth_user_id,
    graded_by,
    graded_at,
    grading_method,
    correct,
    score,
    auto_points,
    manual_points,
    feedback
)
VALUES (
    $submission_id,
    $actor,
    $actor,
    NOW(),
    'Manual',
    TRUE,
    1,
    $auto_points,
    $manual_points,
    JSONB_BUILD_OBJECT('recognized_credit', $record::jsonb)
);

-- BLOCK find_private_files
SELECT f.* FROM files f
WHERE
    f.assessment_id = $assessmentId
    AND f.assessment_instance_id = $assessment_instance_id
    AND f.instance_question_id = $instanceQuestionId
    AND f.user_id = $userId
    AND f.type = 'student_upload'
    AND f.display_filename = $display_filename AND f.deleted_at IS NULL
ORDER BY f.id;

-- BLOCK source_private_submission
-- Historical submission bytes stay unchanged, including failed attempts.
SELECT
    CURRENT_DATABASE() AS database,
    s.id::text AS "submissionId",
    v.id::text AS "variantId",
    iq.id::text AS "instanceQuestionId",
    ai.id::text AS "assessmentInstanceId",
    q.uuid::text AS "questionUUID",
    a.uuid::text AS "workUUID",
    u.id::text AS "userId",
    u.uid,
    s.raw_submitted_answer AS raw_answer,
    s.submitted_answer AS submitted_answer
FROM submissions s JOIN variants v ON v.id = s.variant_id
JOIN instance_questions iq ON iq.id = v.instance_question_id
JOIN assessment_instances ai ON ai.id = iq.assessment_instance_id
JOIN assessment_questions aq ON aq.id = iq.assessment_question_id
JOIN questions q ON q.id = aq.question_id
JOIN assessments a ON a.id = ai.assessment_id JOIN users u ON u.id = ai.user_id
WHERE
    s.id = $submissionId
    AND ai.team_id IS NULL
    AND v.user_id = ai.user_id
    AND v.team_id IS NULL
    AND v.question_id = q.id;

-- BLOCK source_private_file
SELECT
    CURRENT_DATABASE() AS database,
    iq.id::text AS "instanceQuestionId",
    ai.id::text AS "assessmentInstanceId",
    q.uuid::text AS "questionUUID",
    a.uuid::text AS "workUUID",
    u.id::text AS "userId",
    u.uid
FROM files f JOIN instance_questions iq ON iq.id = f.instance_question_id
JOIN
    assessment_instances ai
    ON ai.id = iq.assessment_instance_id AND ai.id = f.assessment_instance_id
JOIN assessment_questions aq ON aq.id = iq.assessment_question_id
JOIN questions q ON q.id = aq.question_id
JOIN assessments a ON a.id = ai.assessment_id AND a.id = f.assessment_id
JOIN users u ON u.id = ai.user_id AND u.id = f.user_id
WHERE
    f.id = $fileId
    AND f.type = 'student_upload'
    AND f.deleted_at IS NULL
    AND ai.team_id IS NULL;

-- BLOCK owned_private_file
SELECT f.* FROM files f
WHERE
    f.id = $file_id
    AND f.assessment_id = $assessmentId
    AND f.assessment_instance_id = $assessment_instance_id
    AND f.instance_question_id = $instanceQuestionId
    AND f.user_id = $userId
    AND f.type = 'student_upload'
    AND f.deleted_at IS NULL;
