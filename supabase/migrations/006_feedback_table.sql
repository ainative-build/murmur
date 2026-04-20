-- User feedback collection for product iteration
CREATE TABLE IF NOT EXISTS feedback (
    id BIGSERIAL PRIMARY KEY,
    tg_user_id BIGINT NOT NULL,
    username TEXT,
    feedback_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(tg_user_id, created_at);
ALTER TABLE feedback DISABLE ROW LEVEL SECURITY;
