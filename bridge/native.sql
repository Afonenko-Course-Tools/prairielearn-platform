-- BLOCK grant_administrator
WITH inserted AS (
    INSERT INTO administrators (user_id)
    SELECT id FROM users
    WHERE uid = $uid AND id = $user_id
    ON CONFLICT (user_id) DO NOTHING
    RETURNING *
),

audit AS (
    INSERT INTO audit_logs (
        authn_user_id, user_id, table_name, row_id, action, new_state
    )
    SELECT
        $user_id,
        inserted.user_id,
        'administrators',
        inserted.id,
        'insert',
        to_jsonb(inserted)
    FROM inserted
)

SELECT
    (
        EXISTS (SELECT 1 FROM inserted) OR EXISTS (
            SELECT 1 FROM administrators a JOIN users u ON u.id = a.user_id
            WHERE u.id = $user_id AND u.uid = $uid
        )
    ) AS administrator;

-- BLOCK lock
SELECT
    pg_advisory_xact_lock(hashtextextended($lock_key, 0));
