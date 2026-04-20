# Phase 1: Foundation

## Context
- [Plan Overview](plan.md)
- [Base Bot Analysis](../reports/researcher-260419-1157-telegram-summarizer-analysis.md)
- [Vertex AI / Gemini 3 Research](../reports/researcher-260419-1340-vertex-ai-gemini-3-research.md)
- Forked from: https://github.com/kargarisaac/telegram_link_summarizer_agent

## Overview
- **Priority:** Critical — everything else builds on this
- **Status:** Completed
- **Scope:** Supabase schema, group message capture, link summary storage, shared vs private memory boundary, /start, upgrade BAML to Gemini 3

## Key Insights (from codebase scout)
- **Codebase already forked and running locally**
- `bot.py` (375 lines) — FastAPI + python-telegram-bot v21+, webhook + polling modes
- `agent.py` (846 lines) — LangGraph + BAML pipeline, 5 content extractors
- Currently only handles `TEXT & (~COMMAND)` messages → extracts URL → runs agent → replies with summary
- **No group message capture, no commands, no persistence** — all to be added
- BAML uses `google-ai` provider with `gemini-2.5-flash-preview-04-17` → upgrade to `gemini-3-flash-preview`
- Dependencies managed via `uv` + `pyproject.toml`
- Dockerfile uses Playwright image, starts with `uv run uvicorn bot:app`
- Deploy scripts exist in `scripts/` (Cloud Run, Docker, local polling)

## Requirements

### Functional
- Add Supabase persistence for all group messages
- Store link extraction results in Supabase after existing agent pipeline
- `/start` — welcome message explaining bot capabilities
- Enforce shared vs private memory boundary at the data layer
- Upgrade BAML clients from Gemini 2.5 to Gemini 3

### Non-Functional
- Messages stored with: tg_user_id, username, text, timestamp, tg_chat_id, has_links, reply_to_tg_msg_id
- Bot handles both group messages (capture) and DM messages (commands) simultaneously
- Existing link summarization pipeline (LangGraph + BAML) upgraded to Gemini 3 but logic untouched
- Environment variables for secrets (bot token, Supabase URL/key, Gemini API key / Vertex AI credentials)

## Architecture

```
┌──────────────────────────────────────────────┐
│  bot.py (FastAPI + python-telegram-bot)       │
│  ├── GroupHandler: capture all group messages  │
│  │   ├── Store in Supabase via db.py          │
│  │   └── If has links → existing agent.py     │
│  │       pipeline → summarize → reply + store │
│  ├── DMHandler: process commands              │
│  │   └── /start → welcome + help              │
│  └── Existing: handle_message (link → agent)  │
├──────────────────────────────────────────────┤
│  Supabase (Postgres)                          │
│  ├── messages (group messages)                │
│  ├── link_summaries (extracted content)       │
│  ├── personal_sources (private per user)      │
│  ├── user_chat_state (per-user per-chat)      │
│  └── users (preferences, timezone)            │
├──────────────────────────────────────────────┤
│  LLM Layer (Gemini 3 only)                    │
│  ├── BAML: gemini-3-flash-preview (routing +  │
│  │         summarization via google-ai)       │
│  └── google-genai SDK: Gemini 3 Flash/Pro     │
│       (new features in Phase 2+)              │
└──────────────────────────────────────────────┘
```

## Gemini 3 Upgrade (BAML)

Update `baml_src/clients.baml` to use Gemini 3:

```baml
# Before
client<llm> Gemini2.5-flash {
  provider "google-ai"
  options {
    model "gemini-2.5-flash-preview-04-17"
    api_key env.GEMINI_API_KEY
  }
}

# After
client<llm> Gemini3Flash {
  provider "google-ai"
  options {
    model "gemini-3-flash-preview"
    api_key env.GEMINI_API_KEY
  }
}
```

Also update any fallback chain references. BAML `google-ai` provider works with Gemini 3 model strings — just swap the model ID.

## Database Schema (Supabase / Postgres)

All tables created upfront so the memory model is unified from the start.

```sql
-- Telegram ID naming convention:
--   tg_msg_id, tg_chat_id, tg_user_id = Telegram's native IDs (BIGINT)
--   id = our internal surrogate key (BIGSERIAL)

-- Group messages
CREATE TABLE messages (
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

CREATE INDEX idx_messages_chat_timestamp ON messages(tg_chat_id, timestamp);
CREATE INDEX idx_messages_user ON messages(tg_user_id);

-- Link summaries (shared pool)
CREATE TABLE link_summaries (
    id BIGSERIAL PRIMARY KEY,
    message_id BIGINT REFERENCES messages(id),
    url TEXT NOT NULL,
    url_normalized TEXT,
    link_type TEXT,
    title TEXT,
    extracted_content TEXT,
    summary TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (message_id, url_normalized)
);

CREATE INDEX idx_links_message ON link_summaries(message_id);
CREATE INDEX idx_links_url_normalized ON link_summaries(url_normalized);

-- Personal sources (private pool)
CREATE TABLE personal_sources (
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
    -- No UNIQUE on (tg_user_id, url_normalized): same user may save the same link
    -- in different contexts (e.g., as 'link' and later as 'note' referencing it).
    -- Dedup handled at retrieval time (GROUP BY url_normalized) when needed.
);

CREATE INDEX idx_personal_user ON personal_sources(tg_user_id, created_at);
CREATE INDEX idx_personal_url ON personal_sources(tg_user_id, url_normalized);

-- Per-user per-chat catchup tracking
CREATE TABLE user_chat_state (
    tg_user_id BIGINT NOT NULL,
    tg_chat_id BIGINT NOT NULL,
    last_catchup_at TIMESTAMPTZ,
    PRIMARY KEY (tg_user_id, tg_chat_id)
);

-- Users and preferences
CREATE TABLE users (
    tg_user_id BIGINT PRIMARY KEY,
    username TEXT,
    reminder_frequency TEXT DEFAULT 'off',
    timezone TEXT DEFAULT 'UTC',
    reminder_time TEXT DEFAULT '09:00',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Exports tracking (for Phase 4, schema ready now)
-- Topic name is metadata (LLM-derived, may drift between runs).
-- content_hash is the stable dedup key.
CREATE TABLE exports (
    id BIGSERIAL PRIMARY KEY,
    topic TEXT NOT NULL,           -- metadata label, not part of dedup
    export_target TEXT DEFAULT 'notebooklm',
    content_hash TEXT NOT NULL,    -- SHA256 of exported content, primary dedup key
    notebooklm_source_id TEXT,
    exported_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_exports_dedup ON exports(export_target, content_hash);

-- RLS (defense-in-depth — app-layer filtering is primary control)
ALTER TABLE personal_sources ENABLE ROW LEVEL SECURITY;

CREATE POLICY personal_sources_user_isolation ON personal_sources
    USING (tg_user_id = current_setting('app.current_user_id')::BIGINT);
```

## Privacy Boundary

**App-layer filtering is the primary privacy control. RLS is defense-in-depth.**

- Group messages (`messages`, `link_summaries`) = shared pool, accessible by all group members
- Personal sources (`personal_sources`) = private pool, filtered by `tg_user_id` at query time
- **Every DB query for personal data MUST include `WHERE tg_user_id = ?`**
- **DM commands that retrieve group data** check `user_chat_state` for a matching row. This is a v1 approximation — it confirms the user has *been seen* in the group (their messages were captured), not live Telegram membership. True membership verification would require `getChatMember` API calls, which adds latency and rate-limit risk. Acceptable for v1; revisit if abuse scenarios emerge.
- When building prompts: query shared pool for user's group(s), personal pool only for requesting user
- RLS on `personal_sources` as second layer
- No command ever returns another user's personal data

## Related Code Files

### Existing files to modify:
- `bot.py` (375 lines) — add group message handler, /start command, DB init on startup
- `baml_src/clients.baml` — upgrade model IDs from `gemini-2.5-*` to `gemini-3-flash-preview`
- `pyproject.toml` — add `supabase`, `google-genai` dependencies
- `.env` / `.env.example` — add `SUPABASE_URL`, `SUPABASE_KEY`

### Existing files to keep untouched:
- `agent.py` (846 lines) — LangGraph pipeline logic (BAML model upgrade is via clients.baml, not agent.py)
- `baml_src/router.baml`, `baml_src/summarize.baml` — prompt logic unchanged
- `tools/` — content extractors
- `scripts/` — deployment scripts

### Files to create:
- `config.py` — centralized config from env vars
- `db.py` — Supabase client wrapper (init, insert, query)
- `commands.py` — DM command handlers (/start initially, more in Phase 2+)
- `url_normalize.py` — URL normalization for dedup
- `supabase/migrations/001_init_schema.sql` — migration file with full schema

## Implementation Steps

1. **Verify base bot runs** — `uv run python bot.py` with `USE_POLLING=true`, confirm link summarization works
2. **Upgrade BAML to Gemini 3** — Update `baml_src/clients.baml`: swap all model IDs to `gemini-3-flash-preview`, update client names, regenerate BAML client. Test link summarization still works.
3. **Add dependencies** — `uv add supabase google-genai`
4. **Create `config.py`** — Centralize env vars: `BOT_TOKEN`, `SUPABASE_URL`, `SUPABASE_KEY`, `GEMINI_API_KEY`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION`. Replace scattered `os.environ.get()` calls in bot.py.
5. **Create migration file** — `supabase/migrations/001_init_schema.sql` with full schema above
6. **Run Supabase migration** — Apply via Supabase dashboard or CLI
7. **Create `url_normalize.py`** — `normalize_url(url)` → lowercase host, strip UTM params, trailing slash, common tracking params
8. **Create `db.py`** — Supabase client wrapper:
   - `get_client()` — singleton Supabase client
   - `store_message(msg)` — insert group message with idempotency (ON CONFLICT DO NOTHING)
   - `store_link_summary(message_id, url, link_type, title, content, summary)` — insert with normalized URL dedup
   - `upsert_user(tg_user_id, username)` — create/update user record
   - `ensure_user_chat_state(tg_user_id, tg_chat_id)` — create row on first group message
9. **Modify `bot.py`** — Refactor handler registration:
   - Keep existing `handle_message` but restrict to group context with link detection
   - Add `group_message_handler` — captures ALL group messages → `db.store_message()`, then if has links → run existing agent → `db.store_link_summary()`
   - Add `CommandHandler("start", start_handler)` — welcome + command list
   - Init Supabase client on app startup (in lifespan)
10. **Create `commands.py`** — `/start` handler: welcome message with all available commands listed
11. **Test locally** — Polling mode:
    - Send messages in group → verify stored in Supabase `messages` table
    - Send link in group → verify agent summarizes (now via Gemini 3) AND summary stored in `link_summaries`
    - DM `/start` → verify welcome message
    - Send same message twice → verify idempotency (no duplicate)

## BotFather Setup
1. Create bot via @BotFather → get token (or reuse existing)
2. `/setprivacy` → Disable (bot sees all group messages)
3. `/setcommands`:
   ```
   start - Welcome and help
   catchup - Get digest of recent discussions
   search - Search messages and links
   topics - List active discussion threads
   topic - Deep dive on a specific topic
   draft - Brainstorm with AI using team context
   decide - Structured decision view on a topic
   ```
4. Add bot to group chat

## Todo
- [x] Verify base bot runs locally with polling mode
- [x] Upgrade BAML clients to Gemini 3 (`gemini-3-flash-preview`)
- [x] Regenerate BAML client, test link summarization
- [x] Add supabase + google-genai to pyproject.toml
- [x] Create config.py — centralized env var loading
- [x] Create migration file + run Supabase migration
- [x] Create url_normalize.py
- [x] Create db.py — Supabase client wrapper
- [x] Modify bot.py — add group capture handler
- [x] Modify bot.py — add /start command
- [x] Create commands.py — /start handler
- [x] Hook link summaries into Supabase after agent pipeline
- [x] Test end-to-end: group capture + /start + link summaries in Supabase
- [x] BotFather setup and group onboarding

## Acceptance Criteria (Testable)
- [x] Send a link in group → BAML routes to correct extractor using `gemini-3-flash-preview` → summary reply appears in group within 30s
- [x] Send 5 text messages in group → all 5 appear in Supabase `messages` table with correct tg_chat_id, tg_user_id, timestamp
- [x] Send same message twice (same tg_msg_id) → only 1 row in `messages` (UNIQUE constraint)
- [x] Send a link in group → `link_summaries` row created with url, url_normalized, summary, link_type populated
- [x] DM `/start` to bot → response within 2s listing all commands (catchup, search, topics, topic, draft, decide)
- [x] Supabase tables exist: messages, link_summaries, personal_sources, user_chat_state, users, exports — all with correct indexes
- [x] RLS policy active on personal_sources
- [x] `user_chat_state` row created when a user's first group message is captured
- [x] Bot runs locally with `USE_POLLING=true` and on Cloud Run with webhook mode

## Risk Assessment
| Risk | Impact | Mitigation |
|------|--------|------------|
| Supabase connection latency from Cloud Run | Slow message storage | Use async client, batch inserts if needed |
| bot.py refactoring breaks existing handler | Link summarization stops | Test link flow end-to-end after changes |
| agent.py run_agent() return format | Hook may miss summary data | Read agent.py output format carefully before hooking |
| BAML Gemini 3 model string not recognized | Routing fails | BAML accepts any string; test with actual API call |
| Supabase free tier limits | Throttling at scale | Monitor usage; upgrade plan if needed |

## Security
- Bot token, API keys, Supabase key via env vars, never in code
- Personal data isolated by tg_user_id + RLS
- No PII stored beyond Telegram username (already public)
- Supabase connection over HTTPS

## Next Phase
→ [Phase 2: Core Usability](phase-02-core-usability.md)
