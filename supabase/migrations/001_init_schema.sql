-- Murmur Bot: Initial Schema
-- Telegram ID naming convention:
--   tg_msg_id, tg_chat_id, tg_user_id = Telegram's native IDs (BIGINT)
--   id = our internal surrogate key (BIGSERIAL)

-- Group messages
CREATE TABLE IF NOT EXISTS messages (
    id BIGSERIAL PRIMARY KEY,
    tg_msg_id BIGINT NOT NULL,
    tg_chat_id BIGINT NOT NULL,
    tg_user_id BIGINT NOT NULL,
    username TEXT,
    text TEXT,
    timestamp TIMESTAMPTZ NOT NULL,
    has_links BOOLEAN DEFAULT FALSE,
    reply_to_tg_msg_id BIGINT,
    forwarded_from TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (tg_chat_id, tg_msg_id)
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_timestamp ON messages(tg_chat_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(tg_user_id);

-- Link summaries (shared pool)
CREATE TABLE IF NOT EXISTS link_summaries (
    id BIGSERIAL PRIMARY KEY,
    message_id BIGINT REFERENCES messages(id),
    url TEXT NOT NULL,
    url_normalized TEXT NOT NULL DEFAULT '',
    link_type TEXT,
    title TEXT,
    extracted_content TEXT,
    summary TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (message_id, url_normalized)
);

CREATE INDEX IF NOT EXISTS idx_links_message ON link_summaries(message_id);
CREATE INDEX IF NOT EXISTS idx_links_url_normalized ON link_summaries(url_normalized);

-- Personal sources (private pool)
CREATE TABLE IF NOT EXISTS personal_sources (
    id BIGSERIAL PRIMARY KEY,
    tg_user_id BIGINT NOT NULL,
    source_type TEXT NOT NULL,
    url TEXT,
    url_normalized TEXT,
    title TEXT,
    content TEXT,
    summary TEXT,
    original_text TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_personal_user ON personal_sources(tg_user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_personal_url ON personal_sources(tg_user_id, url_normalized);

-- Per-user per-chat catchup tracking
CREATE TABLE IF NOT EXISTS user_chat_state (
    tg_user_id BIGINT NOT NULL,
    tg_chat_id BIGINT NOT NULL,
    last_catchup_at TIMESTAMPTZ,
    PRIMARY KEY (tg_user_id, tg_chat_id)
);

-- Users and preferences
CREATE TABLE IF NOT EXISTS users (
    tg_user_id BIGINT PRIMARY KEY,
    username TEXT,
    reminder_frequency TEXT DEFAULT 'off',
    timezone TEXT DEFAULT 'UTC',
    reminder_time TEXT DEFAULT '09:00',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Exports tracking (Phase 4, schema ready now)
-- Topic name is metadata (LLM-derived, may drift). content_hash is the stable dedup key.
CREATE TABLE IF NOT EXISTS exports (
    id BIGSERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    export_target TEXT DEFAULT 'notebooklm',
    content_hash TEXT NOT NULL,
    notebooklm_source_id TEXT,
    exported_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_exports_dedup ON exports(export_target, content_hash);

-- RLS (defense-in-depth — app-layer filtering is primary control)
ALTER TABLE personal_sources ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE tablename = 'personal_sources' AND policyname = 'personal_sources_user_isolation'
    ) THEN
        CREATE POLICY personal_sources_user_isolation ON personal_sources
            USING (tg_user_id = current_setting('app.current_user_id')::BIGINT);
    END IF;
END
$$;
