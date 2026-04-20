# Phase 3: Structured Intelligence

## Context
- [Plan Overview](plan.md)
- Depends on: [Phase 2](phase-02-core-usability.md) (catchup, search, personal memory)

## Overview
- **Priority:** High — the differentiating features
- **Status:** Completed
- **Scope:** /topics, /topic, /draft, /decide

## Key Insights
- `/topics` and `/topic` should **start simple** — don't try perfect topic clustering on day one. LLM-based grouping of recent messages is enough.
- `/draft` is the killer feature — private AI brainstorming with full team context
- `/decide` compiles scattered discussion into structured decision view
- **All outputs must be grounded** — /draft and /decide clearly cite where outputs come from (which messages, which links)
- All commands merge group + personal sources for richer context
- Gemini 3 via Vertex AI for all LLM features (drafting, deciding, topic listing)

## Requirements

### Functional
- `/topics` via DM — AI-grouped active discussion threads from recent messages
- `/topic <name>` via DM — deep dive on specific topic with relevant messages + links
- `/draft <topic>` — compile all context (group + personal) → enter conversational brainstorm mode in DM
- `/decide <topic>` — compile all positions, arguments, links into structured decision format

### Non-Functional
- `/topics` v1 scope: single LLM call over last 48h of messages → returns 3-8 labeled threads. No embedding, no clustering infra, no topic persistence. Just a prompt that groups messages.
- `/topic` filters by keyword match + LLM relevance, not vector similarity
- Draft mode = multi-turn conversation in DM (not one-shot)
- **One active draft session per user.** Starting a new /draft while one is active prompts to /cancel or /done first.
- Draft sessions auto-expire after 24h of inactivity.
- `/cancel` exits draft mode without saving.
- All LLM outputs cite source: "[username, date]" or "[link: title]"

## Architecture

```
/topics
  ├── Query recent messages (48h default)
  └── Gemini 3 → group into topics with brief description

/topic <name>
  ├── Query recent messages + link_summaries
  ├── Filter by keyword + LLM relevance
  └── Gemini 3 → synthesize topic context with citations

/draft <topic>
  ├── Query group messages + personal sources for topic
  ├── Build rich context prompt with citations
  └── Enter conversational mode (multi-turn with Gemini 3)
      ├── User refines arguments
      ├── Bot challenges assumptions, cites team context
      ├── /done → exit draft mode, optionally save as personal note
      └── /cancel → exit without saving
      (one active session per user, auto-expire after 24h)

/decide <topic>
  ├── Gather all messages + links on topic
  └── Structured output with citations:
      ├── Options identified [cited from messages]
      ├── Arguments for/against each [cited]
      ├── Key evidence (links, quotes) [cited]
      └── What's missing for decision
```

## Database Additions

```sql
-- Draft sessions (ephemeral, clean up after 24h inactivity)
CREATE TABLE draft_sessions (
    id BIGSERIAL PRIMARY KEY,
    tg_user_id BIGINT NOT NULL,
    topic TEXT NOT NULL,
    context_snapshot JSONB, -- gathered context at draft start
    conversation_history JSONB, -- multi-turn messages
    started_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(), -- tracks last activity for 24h expiry
    ended_at TIMESTAMPTZ
);

CREATE INDEX idx_draft_user ON draft_sessions(tg_user_id, started_at);
-- Partial index for quick "get active session" lookups
CREATE UNIQUE INDEX idx_draft_active ON draft_sessions(tg_user_id) WHERE ended_at IS NULL;
```

## Related Code Files

### Files to modify:
- `bot.py` — add /topics, /topic, /draft, /decide commands, ConversationHandler for draft mode
- `commands.py` — add handler functions
- `summarizer.py` — add topics, topic detail, draft, decide prompt templates
- `db.py` — add topic query helpers, draft session CRUD

### Files to create:
- `draft_mode.py` — conversational draft session manager

## Implementation Steps

1. **Extend `db.py`** — New queries:
   - `get_recent_messages(chat_id, hours=48)` — for /topics
   - `get_messages_by_keyword(chat_id, keyword, hours=72)` — for /topic
   - `create_draft_session(user_id, topic, context)` — start draft (fail if active session exists)
   - `get_active_draft_session(user_id)` — get active session (NULL if none or expired >24h)
   - `append_draft_message(session_id, role, content)` — add to conversation
   - `end_draft_session(session_id)` — mark ended
   - `cancel_draft_session(session_id)` — mark ended without save
   - `expire_stale_drafts()` — `SET ended_at = NOW() WHERE ended_at IS NULL AND updated_at < NOW() - INTERVAL '24 hours'`

2. **Extend `summarizer.py`** — New Gemini 3 calls via `google-genai`:
   - `async generate_topics(messages)` — uses `gemini-3-flash-preview` with `response_mime_type='application/json'` + `response_schema` for structured topic list
   - `async generate_topic_detail(messages, links, topic_name)` — `gemini-3-flash-preview` with system instruction to cite as [username, date]
   - `async generate_decision_view(messages, links, topic)` — `gemini-3-flash-preview` with structured JSON output: options, pros/cons, evidence, gaps
   - `draft_system_prompt(context)` — system instruction for draft mode

3. **Create `draft_mode.py`** — Draft session manager using `gemini-3.1-pro-preview` (quality matters for multi-turn):
   - `start_draft(user_id, topic)` — check no active session exists → gather context → create session → send initial context summary → "Ready to brainstorm"
   - `continue_draft(session_id, user_message)` — append to conversation, call `client.aio.models.generate_content(model='gemini-3.1-pro-preview', contents=conversation_history, config=GenerateContentConfig(system_instruction=...))` → reply with citations
   - `end_draft(session_id)` — mark ended, optionally save final draft as personal note
   - `cancel_draft(session_id)` — mark ended, discard without saving
   - Context gathering: keyword match on messages + link_summaries + personal_sources, then LLM relevance filter

4. **Modify `bot.py`** — Add handlers:
   - `CommandHandler("topics", topics_handler)` with `filters.ChatType.PRIVATE`
   - `CommandHandler("topic", topic_handler)` with `filters.ChatType.PRIVATE`
   - `ConversationHandler` for draft mode:
     - Entry: `CommandHandler("draft", draft_start_handler)`
     - States: `DRAFTING` → `MessageHandler(filters.TEXT, draft_continue_handler)`
     - Fallbacks: `CommandHandler("done", draft_end_handler)`, `CommandHandler("cancel", draft_cancel_handler)`
   - `CommandHandler("decide", decide_handler)` with `filters.ChatType.PRIVATE`

5. **Extend `commands.py`**:
   - `topics_handler` — get recent messages → summarizer.generate_topics → reply
   - `topic_handler` — parse topic name → gather messages + links → summarizer.generate_topic_detail → reply with citations
   - `decide_handler` — gather context → summarizer.generate_decision_view → reply with citations
   - `draft_start_handler` — draft_mode.start_draft → enter DRAFTING state
   - `draft_continue_handler` — draft_mode.continue_draft → reply
   - `draft_end_handler` — draft_mode.end_draft → exit conversation, offer to save as /note

6. **Test**:
   - `/topics` → returns 3-8 grouped threads with descriptions
   - `/topic pricing` → detailed context with message citations
   - `/draft pricing` → enters conversational mode, multi-turn works, cites team context
   - `/done` → exits draft, optionally saves as personal note
   - `/decide payment-provider` → structured view with cited arguments

## Todo
- [x] Extend db.py — topic queries + draft session CRUD
- [x] Extend summarizer.py — topics, topic detail, decide, draft prompts (all with citation instructions)
- [x] Create draft_mode.py — session manager with multi-turn conversation
- [x] Add /topics, /topic commands to bot.py
- [x] Add ConversationHandler for /draft flow
- [x] Add /decide command
- [x] Test topic grouping quality (simple is fine, improve later)
- [x] Test citation accuracy in /topic and /decide outputs
- [x] Test multi-turn draft mode end-to-end

## Acceptance Criteria (Testable)
- [x] `/topics` returns 3-8 labeled threads from last 48h; each has a name and 1-2 sentence description
- [x] `/topic pricing` returns synthesis with ≥80% of points citing [username, date] or [link: title]
- [x] `/draft pricing` → bot replies with context summary + "Ready to brainstorm"; user can send 5+ messages; `/done` exits and offers to save as /note
- [x] Starting `/draft` while one is active → bot prompts to `/done` or `/cancel` first
- [x] `/cancel` exits draft without saving; `/done` saves final draft as personal note
- [x] Draft session inactive >24h → auto-expired; next `/draft` starts fresh
- [x] `/decide payment-provider` returns structured output: options, arguments for/against, evidence with citations, identified gaps
- [x] Draft mode context includes both group messages and requesting user's personal sources
- [x] `/topics` response time <10s; `/draft` per-turn response time <8s

## Risk Assessment
| Risk | Impact | Mitigation |
|------|--------|------------|
| Topic grouping too noisy | Confusing /topics output | Start with simple keyword grouping, iterate on prompts |
| Draft mode context too large for LLM | Truncated/poor summaries | Limit to last 100 relevant messages + top 10 links |
| Multi-turn state lost on Cloud Run restart | Draft session broken | Stored in Supabase, reload on next message |
| Citations inaccurate | User distrust | Include message timestamps + usernames in prompt context for grounding |

## Next Phase
→ [Phase 4: Extended Workflows](phase-04-extended-workflows.md)
