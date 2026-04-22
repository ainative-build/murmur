-- Scheduled message deletions — persists auto-delete timers across Cloud Run container restarts.
-- Cloud Scheduler calls /api/cleanup-messages every 10 min to process due deletions.
CREATE TABLE IF NOT EXISTS scheduled_deletions (
    id BIGSERIAL PRIMARY KEY,
    tg_chat_id BIGINT NOT NULL,
    tg_message_id BIGINT NOT NULL,
    delete_after TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tg_chat_id, tg_message_id)
);

-- Index for efficient cleanup queries
CREATE INDEX IF NOT EXISTS idx_scheduled_deletions_due
    ON scheduled_deletions (delete_after)
    WHERE delete_after IS NOT NULL;
