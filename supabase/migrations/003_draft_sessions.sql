-- Draft sessions for /draft multi-turn conversation mode
CREATE TABLE IF NOT EXISTS draft_sessions (
    id BIGSERIAL PRIMARY KEY,
    tg_user_id BIGINT NOT NULL,
    topic TEXT NOT NULL,
    context_snapshot JSONB,
    conversation_history JSONB DEFAULT '[]'::jsonb,
    started_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    ended_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_draft_user ON draft_sessions(tg_user_id, started_at);

-- Partial unique index: one active session per user (ended_at IS NULL)
CREATE UNIQUE INDEX IF NOT EXISTS idx_draft_active ON draft_sessions(tg_user_id) WHERE ended_at IS NULL;
