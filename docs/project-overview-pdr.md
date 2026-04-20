# Murmur Bot - Project Overview & PDR

**Project:** Telegram Link Summarizer Agent (Murmur Bot)  
**Phase:** 1 (Foundation) — Completed  
**Version:** 0.1.0  
**Last Updated:** 2026-04-19  

## Executive Summary

Murmur is a Telegram bot that serves as a team's "silent listener," capturing group discussions and summarizing shared links. It combines LangGraph-orchestrated AI with Supabase persistence to create a centralized knowledge repository while maintaining clear boundaries between shared (group messages) and private (user-specific notes) data.

### Core Value Proposition
- **Silent Capture:** Automatically stores all group messages without explicit triggers
- **Link Intelligence:** Summarizes articles, PDFs, tweets, YouTube videos, and LinkedIn posts
- **Team Context:** Future DM commands leverage shared discussion history for personalized insights
- **Privacy by Design:** Shared pool (group messages) vs. private pool (user notes) at schema level

---

## Product Requirements (PDR)

### Phase 1: Foundation ✅ COMPLETED

#### Functional Requirements
1. **Group Message Persistence** — All text messages in groups captured to Supabase with metadata (user, timestamp, chat ID, link flags)
2. **Link Summary Storage** — Extracted content and summaries stored alongside messages
3. **Welcome Command** — `/start` DM provides bot overview and planned command list
4. **Gemini 3 Upgrade** — BAML clients use `gemini-3-flash-preview` (from `gemini-2.5-flash-preview-04-17`)

#### Non-Functional Requirements
- Idempotent message storage (dedup via `UNIQUE (tg_chat_id, tg_msg_id)`)
- URL normalization for link dedup (strip UTM params, lowercase, trailing slashes)
- Singleton Supabase client for connection efficiency
- FastAPI + python-telegram-bot v21+, supports webhook and polling modes

#### Database Schema (Supabase/Postgres)
| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `messages` | Group message capture | `tg_msg_id`, `tg_chat_id`, `tg_user_id`, `text`, `timestamp`, `has_links` |
| `link_summaries` | Extracted & summarized links | `message_id`, `url`, `url_normalized`, `link_type`, `summary` |
| `users` | User metadata | `tg_user_id`, `username`, `timezone`, `reminder_frequency` |
| `user_chat_state` | Per-user per-chat tracking | `tg_user_id`, `tg_chat_id`, `last_catchup_at` |
| `personal_sources` | Private user notes | `tg_user_id`, `source_type`, `url`, `title`, `summary` |
| `exports` | NotebookLM exports (Phase 4) | `topic`, `content_hash`, `export_target`, `notebooklm_source_id` |

---

### Phase 2: DM Commands (Planned)

#### Requirements
- `/catchup` — Brief digest of recent discussions in groups user participates
- `/search <keyword>` — Full-text search across messages + links
- `/topics` — List active discussion threads with latest activity
- `/topic <name>` — Deep dive on specific topic with structured timeline

#### Database Queries
- Leverage `user_chat_state` to determine user's group membership (v1 approximation)
- Query `messages` + `link_summaries` by `tg_chat_id` and timestamp filters
- RLS + app-layer filtering for privacy boundary

---

### Phase 3: AI-Powered Workflows (Planned)

#### Requirements
- `/draft <topic>` — Brainstorm with AI using team context
- `/decide <topic>` — Structured decision framework from discussion threads
- Contextual retrieval from group discussions + user's personal sources

---

### Phase 4: Extended Features (Planned)

#### Requirements
- `/remind` — Smart reminders tied to discussion topics
- `/export` — Generate NotebookLM study materials from curated discussions
- `/note` — Add personal annotations to shared links
- `/sources` — Manage and organize personal source library

---

## Technical Architecture

### Current Stack
- **Language:** Python 3.12+
- **Bot Framework:** python-telegram-bot v21+ (FastAPI wrapper)
- **Orchestration:** LangGraph
- **LLM:** Google Gemini 3 Flash/Pro via BAML
- **Database:** Supabase (Postgres)
- **Web Framework:** FastAPI + Uvicorn
- **Content Extraction:** Playwright, AgentQL, PyMuPDF, Tavily
- **Code Generation:** BAML for structured outputs

### Deployment Modes
- **Polling:** `USE_POLLING=true` — local dev, no HTTPS required
- **Webhook:** FastAPI + ngrok (local) or Cloud Run (production)
- **Docker:** Self-managed servers or Google Cloud Run

### Data Flow
```
Telegram Group Message
  ↓
bot.py: group_message_handler
  ↓
db.store_message() → Supabase messages table
  ↓
[If has_links]
  ↓
run_agent() → LangGraph + BAML
  ↓
Content extraction (5 tools) → Router → Summarizer
  ↓
db.store_link_summary() → Supabase link_summaries table
  ↓
Reply to group with summary
```

---

## Privacy & Boundaries

### Shared vs. Private Data
- **Shared Pool:** `messages`, `link_summaries` — accessible to all group members
- **Private Pool:** `personal_sources` — filtered by `tg_user_id` at query + RLS layers

### Privacy Controls
1. **App-Layer Filtering (Primary):** Every query for personal data includes `WHERE tg_user_id = current_user_id`
2. **Row-Level Security (Secondary):** RLS policy on `personal_sources` table enforces user isolation
3. **Membership Approximation:** `user_chat_state` confirms user *has participated* in group (not live verification)

### Sensitive Data Handling
- Bot tokens, API keys stored in environment variables (never in code/DB)
- URLs normalized and stored without PII stripping (assumption: links are not private by default)
- User DM content not stored (commands are stateless or use public group context)

---

## Development Roadmap

### Current Status: Phase 1 Complete
- ✅ Supabase schema created (6 tables)
- ✅ Group message capture implemented
- ✅ Link summarization with Gemini 3
- ✅ `/start` command
- ✅ URL normalization for dedup
- ✅ Config centralization

### Timeline (Provisional)
| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Foundation: Message capture, link summaries, Gemini 3 | ✅ DONE |
| 2 | DM Commands: /catchup, /search, /topics, /topic | 🔄 PLANNED |
| 3 | AI Workflows: /draft, /decide with context | 🔄 PLANNED |
| 4 | Extended: /remind, /export, /note, /sources | 🔄 PLANNED |

---

## Success Metrics

### Phase 1 Validation
- [x] 100% of group messages captured (no duplicates)
- [x] Links identified and summarized successfully
- [x] Gemini 3 routing + summarization produces accurate outputs
- [x] `UNIQUE (tg_chat_id, tg_msg_id)` prevents duplicate inserts
- [x] `/start` command displays correctly in DM

### Phase 2+ Metrics (TBD)
- Query response time < 1s for `/catchup` (recent messages)
- Search results relevant (precision > 0.8)
- Topic identification accuracy > 0.7

---

## Known Constraints & Future Considerations

### Constraints
- Membership verification (Phase 2) uses `user_chat_state` (v1 approximation — doesn't confirm live membership)
- No message editing/deletion sync from Telegram
- No thread-aware message grouping (messages are flat in initial phase)
- Supabase outages affect group message capture (no local queue)

### Future Improvements
- Live membership verification via `getChatMember` API (latency trade-off)
- Message edit tracking and history
- Thread-aware grouping for better topic clustering
- Offline queue for Supabase failures
- Full-text search optimization (current: simple LIKE queries)

---

## Dependencies & Integration Points

### External Services
1. **Telegram** — Bot API (groups, DMs, webhooks)
2. **Supabase** — Postgres database + auth
3. **Google Cloud** — Gemini 3 API (via BAML + google-ai provider)
4. **Tavily** — Web search and content extraction
5. **Twitter API (twitterapi.io)** — Tweet scraping
6. **AgentQL** — Playwright-based web automation
7. **NotebookLM** — Future export target (Phase 4)

### Internal Modules
- `agent.py` — LangGraph pipeline (unchanged in Phase 1)
- `config.py` — Environment configuration
- `db.py` — Supabase wrapper
- `commands.py` — DM command handlers
- `url_normalize.py` — URL dedup utilities
- `baml_src/` — BAML definitions (router, summarizer, clients)

---

## Glossary

| Term | Definition |
|------|-----------|
| **Murmur** | Project name; bot identity |
| **Shared Pool** | `messages` + `link_summaries` — accessible to all group members |
| **Private Pool** | `personal_sources` — per-user, not shared |
| **Link Type** | Categorization (webpage, PDF, tweet, youtube, linkedin) |
| **URL Normalized** | Cleaned URL (lowercase, no tracking params) for dedup |
| **user_chat_state** | Tracks per-user per-chat membership and catchup timestamp |
| **BAML** | Boundary ML framework for structured LLM outputs |
| **LangGraph** | Agentic workflow orchestration |

