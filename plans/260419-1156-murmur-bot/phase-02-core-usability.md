# Phase 2: Core Usability

## Context
- [Plan Overview](plan.md)
- Depends on: [Phase 1](phase-01-foundation.md) (Supabase schema + bot framework + group capture)

## Overview
- **Priority:** High — makes the bot immediately useful
- **Status:** Completed
- **Scope:** /catchup, /search, personal memory save flow

## Key Insights
- `/catchup` is the first command users will try — must work reliably
- Personal memory save should "just work": DM a link or forward a message, no special command needed
- `/search` must clearly label results as "group" or "personal" origin
- Privacy boundary: personal sources never leak into other users' results

## Requirements

### Functional
- `/catchup` via DM — digest of messages since user's last check-in
- `/search <keyword>` — full-text search across group + personal, labeled by origin
- DM a link → bot extracts content, stores as personal source
- Forward a message → bot captures as personal source
- `/note <text>` → save personal note
- `/sources` → list personal sources count and recent entries
- `/delete <id>` → remove a personal source
- Track per-user "last seen" timestamp for personalized catchups

### Non-Functional
- Personal sources isolated by tg_user_id — no cross-user access
- Full-text search via Postgres `tsvector` / `ts_query` with `simple` config (mixed-language chats)
- Link extraction reuses existing agent pipeline

## Architecture

```
/catchup [group_name]
  ├── Look up user's groups from user_chat_state
  ├── If 1 group → use it. If multiple → require group_name or show picker.
  ├── Verify user has row in user_chat_state for that tg_chat_id (v1 approximation — confirms user was seen in group, not live membership)
  ├── Query messages since last_catchup_at for that (user, chat) pair
  ├── Include link_summaries for those messages
  ├── Gemini 3 → grouped digest
  └── Update last_catchup_at in user_chat_state

/search <keyword>
  ├── Search messages (full-text) → label [GROUP]
  ├── Search link_summaries (full-text) → label [GROUP]
  ├── Search personal_sources (tg_user_id filtered) → label [PERSONAL]
  └── Return merged results, sorted by relevance

DM (non-command)
  ├── Has link? → reuse agent pipeline → store in personal_sources
  ├── Is forwarded? → extract text → store in personal_sources
  └── Plain text? → prompt user to use /note
```

## Database Additions

```sql
-- Full-text search support on existing tables
ALTER TABLE messages ADD COLUMN search_vector tsvector;
ALTER TABLE link_summaries ADD COLUMN search_vector tsvector;
ALTER TABLE personal_sources ADD COLUMN search_vector tsvector;

CREATE INDEX idx_messages_fts ON messages USING GIN(search_vector);
CREATE INDEX idx_links_fts ON link_summaries USING GIN(search_vector);
CREATE INDEX idx_personal_fts ON personal_sources USING GIN(search_vector);

-- Triggers to auto-populate search vectors
CREATE OR REPLACE FUNCTION update_messages_search() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('simple', COALESCE(NEW.text, ''));
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER messages_search_trigger
  BEFORE INSERT OR UPDATE ON messages
  FOR EACH ROW EXECUTE FUNCTION update_messages_search();

CREATE OR REPLACE FUNCTION update_links_search() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('simple',
    COALESCE(NEW.title, '') || ' ' || COALESCE(NEW.summary, '') || ' ' || COALESCE(NEW.extracted_content, ''));
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER links_search_trigger
  BEFORE INSERT OR UPDATE ON link_summaries
  FOR EACH ROW EXECUTE FUNCTION update_links_search();

CREATE OR REPLACE FUNCTION update_personal_search() RETURNS trigger AS $$
BEGIN
  NEW.search_vector := to_tsvector('simple',
    COALESCE(NEW.title, '') || ' ' || COALESCE(NEW.content, '') || ' ' || COALESCE(NEW.summary, ''));
  RETURN NEW;
END $$ LANGUAGE plpgsql;

CREATE TRIGGER personal_search_trigger
  BEFORE INSERT OR UPDATE ON personal_sources
  FOR EACH ROW EXECUTE FUNCTION update_personal_search();
```

## Related Code Files

### Files to modify:
- `bot.py` — add DM message handler (non-command messages), new command handlers
- `db.py` — add query functions (catchup, search, personal sources CRUD)
- `commands.py` — add catchup, search, note, sources, delete handlers

### Files to create:
- `summarizer.py` — Gemini 3 via `google-genai` SDK (async, `gemini-3-flash-preview`)
- `personal.py` — personal source processing (link extraction, forwarded message handling)

## Implementation Steps

1. **Run FTS migration** — Add search_vector columns + triggers to Supabase
2. **Extend `db.py`** — New query functions:
   - `get_messages_since(chat_id, since_dt)` — for catchup
   - `get_link_summaries_for_messages(message_ids)` — enrich catchup
   - `update_last_catchup(tg_user_id, chat_id)` — track per-user per-chat via `user_chat_state`
   - `get_last_catchup(tg_user_id, chat_id)` — read from `user_chat_state`
   - `search_all(tg_user_id, query)` — full-text across all tables, personal filtered by tg_user_id, returns with origin label
   - `store_personal_source(tg_user_id, source_type, content, url?, summary?)`
   - `get_personal_sources(tg_user_id, limit=10)`
   - `delete_personal_source(tg_user_id, source_id)` — with tg_user_id ownership check
3. **Create `summarizer.py`** — Gemini 3 via `google-genai` SDK:
   - Init: `client = genai.Client(api_key=config.GEMINI_API_KEY)` (local) or `genai.Client(vertexai=True)` (Cloud Run)
   - `async generate_catchup(messages, link_summaries)` — uses `client.aio.models.generate_content(model='gemini-3-flash-preview', ...)` with system instruction for digest formatting
   - All calls async via `.aio` for non-blocking Telegram bot
4. **Create `personal.py`** — Personal source processing:
   - `handle_dm_link(tg_user_id, url)` — detect link → reuse agent pipeline → store in personal_sources
   - `handle_dm_forward(tg_user_id, message)` — extract forwarded text + links → store
   - `handle_dm_note(tg_user_id, text)` — direct store as note
5. **Modify `bot.py`** — Add handlers:
   - `CommandHandler("catchup", catchup_handler)` with `filters.ChatType.PRIVATE`
   - `CommandHandler("search", search_handler)` with `filters.ChatType.PRIVATE`
   - `CommandHandler("note", note_handler)` with `filters.ChatType.PRIVATE`
   - `CommandHandler("sources", sources_handler)` with `filters.ChatType.PRIVATE`
   - `CommandHandler("delete", delete_handler)` with `filters.ChatType.PRIVATE`
   - `MessageHandler(filters.ChatType.PRIVATE & ~filters.COMMAND, dm_message_handler)` — catches non-command DMs
6. **Implement `commands.py`** handlers:
   - `catchup_handler` — get messages since last catchup → summarizer → reply → update last_catchup
   - `search_handler` — parse query → db.search_all → format with [GROUP] / [PERSONAL] labels
   - `note_handler` — extract text → personal.py
   - `sources_handler` — list count + last 5 personal sources
   - `delete_handler` — parse ID → delete with ownership check
   - `dm_message_handler` — route to personal.py based on content (link, forward, or prompt for /note)
7. **Test**:
   - `/catchup` returns coherent digest grouped by topic
   - `/search blockchain` returns group + personal results, labeled
   - DM a link → extracted and stored privately
   - Forward a message → captured as personal source
   - `/note` → stored
   - User A cannot see User B's personal sources

## Todo
- [x] Run Supabase migration — FTS columns + triggers
- [x] Extend db.py — catchup, search, personal CRUD queries
- [x] Create summarizer.py — Gemini 3 catchup digest
- [x] Create personal.py — link/forward/note processing
- [x] Add /catchup, /search, /note, /sources, /delete to bot.py
- [x] Add DM message handler for non-command messages
- [x] Implement all handlers in commands.py
- [x] Test catchup digest quality
- [x] Test search across both pools with labeling
- [x] Test privacy isolation between users

## Acceptance Criteria (Testable)
- [x] `/catchup` returns digest covering messages since user's last catchup, grouped by topic, in <10s
- [x] After `/catchup`, `user_chat_state.last_catchup_at` is updated; next `/catchup` only covers new messages
- [x] `/catchup` with multiple groups → prompts user to pick group (or shows picker)
- [x] `/search blockchain` returns results with [GROUP] and [PERSONAL] labels; results sorted by relevance
- [x] DM a link → `personal_sources` row created with url, url_normalized, summary populated
- [x] Forward a message to bot DM → stored as `source_type='forwarded_message'`
- [x] `/note important thing` → stored as `source_type='note'` with content = "important thing"
- [x] `/sources` → shows count + last 5 entries for requesting user
- [x] `/delete <id>` with valid ID → row removed; with other user's ID → rejected
- [x] User A runs `/search` → never sees User B's personal_sources rows

## Security
- All personal_sources queries filtered by tg_user_id (app level + RLS)
- `/delete` checks ownership before removing
- Search results respect privacy boundary before returning

## Next Phase
→ [Phase 3: Structured Intelligence](phase-03-structured-intelligence.md)
