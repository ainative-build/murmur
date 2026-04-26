# Codebase Summary

**Last Updated:** 2026-04-19  
**Phase:** 1 Foundation  
**Total Python Files:** 7 (root-level) + 5 (tools/) + 2 (scripting)  
**Total Lines of Code:** ~2,500 (application)  

---

## File Tree & Responsibilities

### AI Provider Layer (NEW — Phase 7)

#### src/providers/ (Multi-provider abstraction)

**Module:** `/src/providers/` (12 files, ~800 LOC)  
**Role:** Environment-driven provider selection for Gemini 3 + MiniMax M2.7

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | — | Exports Feature enum, get_provider() factory |
| `base.py` | ~50 | Abstract Provider interface (text_to_text, text_to_image, etc.) |
| `types.py` | ~40 | Feature enum, TextGenerationConfig, shared types |
| `config.py` | ~60 | Provider-specific config (API keys, base URLs, retry defaults) |
| `factory.py` | ~30 | `get_provider(Feature) -> Provider` with env precedence logic |
| `retry.py` | ~40 | Retry decorator + fallback strategy for transient errors |
| `gemini.py` | ~200 | GeminiProvider implementation (Gemini 3 Flash/Pro) |
| `gemini_client.py` | ~30 | Lazy-loaded Gemini SDK client |
| `gemini_helpers.py` | ~90 | Gemini-specific formatting, token count estimation |
| `minimax.py` | ~200 | MiniMaxProvider implementation (M2.7) |
| `minimax_client.py` | ~40 | MiniMax SDK client wrapper |
| `minimax_stt.py` | ~60 | MiniMax STT polling logic (fixed 2s interval, 30s ceiling) |

**Key Design:** Provider abstraction fully transparent to callers. Env-only switching (no code rebuild).

**Telemetry:** All providers log structured JSON `{"event": "provider_usage", "provider": "...", "feature": "...", "input_tokens": N, "output_tokens": M}` for cost tracking.

---

#### src/ai/prompts/ (Extracted prompt templates)

**Module:** `/src/ai/prompts/` (7 files, ~100 LOC)  
**Role:** Composable prompt builders for text generation

| File | Purpose |
|------|---------|
| `__init__.py` | Package marker |
| `catchup.py` | Build catchup system+user prompts |
| `topics.py` | Build topics clustering prompt |
| `topic_detail.py` | Build topic deep-dive prompt |
| `decide.py` | Build structured decision prompt |
| `draft.py` | Build brainstorm prompt |
| `reminder.py` | Build reminder digest prompt |

**Design:** Extracted from monolithic summarizer.py (401 → 175 LOC). Each module builds a (system_prompt, user_prompt) tuple, called by corresponding summarizer.generate_* function.

---

### Core Application Files (Root)

#### bot.py (291 lines)
**Purpose:** FastAPI server + python-telegram-bot wrapper  
**Key Exports:** `app` (FastAPI), `ptb_app` (PTB Application)

| Function | Lines | Responsibility |
|----------|-------|-----------------|
| `_register_handlers()` | 8 | Register CommandHandler + MessageHandler on PTB Application |
| `group_message_handler()` | 35 | Capture ALL group messages → store_message() → run_agent() if has links |
| `_process_links_and_store()` | 39 | Run agent pipeline → store_link_summary() → reply with summary |
| `_detect_link_type()` | 12 | Heuristic link type detection (tweet, youtube, linkedin, pdf, webpage) |
| `_safe_process_update()` | 7 | Process update with error logging wrapper |
| `lifespan()` | 63 | FastAPI lifespan: PTB init, handler registration, webhook/polling setup, shutdown |
| `webhook()` | 22 | HTTP POST endpoint: validate secret token → parse JSON → dispatch update |
| `health_check()` | 4 | GET /health endpoint |
| Direct execution | 26 | Polling mode entry point (if __name__ == "__main__") |

**Dependencies:** config, db, agent.run_agent, commands.start_handler, fastapi, telegram, uvicorn  
**Execution Modes:** Polling (USE_POLLING=true) or Webhook (WEBHOOK_URL set)

---

#### config.py (42 lines)
**Purpose:** Centralized environment variable loading  
**Key Exports:** BOT_TOKEN, WEBHOOK_URL, SUPABASE_URL, etc.

| Variable | Source | Type | Used By |
|----------|--------|------|---------|
| BOT_TOKEN | TELEGRAM_BOT_TOKEN | str | bot.py |
| WEBHOOK_URL | WEBHOOK_URL | str | bot.py |
| WEBHOOK_SECRET_PATH | WEBHOOK_SECRET_PATH (default: "webhook") | str | bot.py |
| WEBHOOK_SECRET_TOKEN | TELEGRAM_WEBHOOK_SECRET_TOKEN | str | bot.py |
| USE_POLLING | USE_POLLING (default: "false") | bool | bot.py |
| SUPABASE_URL | SUPABASE_URL | str | db.py |
| SUPABASE_KEY | SUPABASE_KEY | str | db.py |
| GEMINI_API_KEY | GEMINI_API_KEY | str | BAML clients (via env) |
| GOOGLE_CLOUD_PROJECT | GOOGLE_CLOUD_PROJECT | str | (reserved) |
| GOOGLE_CLOUD_LOCATION | GOOGLE_CLOUD_LOCATION (default: "us-central1") | str | (reserved) |
| HOST | HOST (default: "0.0.0.0") | str | uvicorn |
| PORT | PORT (default: 8080) | int | uvicorn |
| IS_CLOUD_RUN | K_SERVICE env var presence | bool | Deployment detection |

**Dependencies:** os, dotenv  
**Notes:** Loads .env with override=True; warns if IS_CLOUD_RUN but WEBHOOK_URL not set

---

#### db.py (127 lines)
**Purpose:** Supabase client wrapper + data persistence  
**Key Exports:** `get_client()`, `store_message()`, `store_link_summary()`, `upsert_user()`, `ensure_user_chat_state()`

| Function | Parameters | Returns | DB Action |
|----------|-----------|---------|-----------|
| `get_client()` | — | Client | Singleton Supabase client (lazy init) |
| `store_message()` | tg_msg_id, tg_chat_id, tg_user_id, username, text, timestamp, has_links, reply_to_tg_msg_id, forwarded_from | `int \| None` | UPSERT messages, dedup UNIQUE(tg_chat_id, tg_msg_id) |
| `store_link_summary()` | message_id, url, link_type, title, extracted_content, summary | `int \| None` | UPSERT link_summaries, dedup UNIQUE(message_id, url_normalized) |
| `upsert_user()` | tg_user_id, username | None | UPSERT users |
| `ensure_user_chat_state()` | tg_user_id, tg_chat_id | None | UPSERT user_chat_state |

**Dependencies:** supabase.create_client, config, url_normalize.normalize_url  
**Error Handling:** All functions log exceptions and return None or continue gracefully

---

#### commands.py (38 lines)
**Purpose:** DM command handlers  
**Key Exports:** `start_handler()`, `COMMAND_LIST`

| Handler | Trigger | Output |
|---------|---------|--------|
| `start_handler()` | /start DM | Welcome message (HTML) with planned command list |

**Constants:**
```python
COMMAND_LIST = """<b>Available Commands</b> (use in DM):
/start — Welcome and help
/catchup — Get digest of recent discussions
/search <keyword> — Search messages and links
... (planned commands)
"""
```

**Dependencies:** telegram  
**Notes:** All handlers are async (required by python-telegram-bot v21+)

---

#### url_normalize.py (43 lines)
**Purpose:** URL normalization for dedup  
**Key Exports:** `normalize_url()`

| Function | Input | Output | Algorithm |
|----------|-------|--------|-----------|
| `normalize_url()` | str (URL) | str (normalized) | Lowercase scheme+host → strip port → strip trailing slash → remove tracking params → sort query → reconstruct |

**Tracked Parameters Stripped:**
```python
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "mc_cid", "mc_eid"
})
```

**Example:**
```
Input:  https://example.com:443/path/?utm_source=twitter&id=123
Output: https://example.com/path?id=123
```

**Dependencies:** urllib.parse  
**Error Handling:** Fallback to lowercased URL if parsing fails

---

#### summarizer.py (175 lines)
**Purpose:** Thin orchestration layer — delegates to AI provider  
**Key Exports:** `generate_catchup()`, `generate_topics()`, `generate_topic_detail()`, `generate_decision_view()`, `generate_draft_response()`, `generate_reminder_digest()`, `get_genai_client()` (backward compat), `config`

**Design:** All direct Gemini calls removed. Functions now use `get_provider(Feature.TEXT)` internally. Public API unchanged — existing callers (commands.py, agent.py, tests) require no modifications.

**Dependencies:** src/providers, src/ai/prompts, config (for backward compat)

---

#### agent.py (846 lines)
**Purpose:** LangGraph orchestration + link summarization  
**Key Exports:** `run_agent()`

| Component | Responsibility | Models |
|-----------|-----------------|--------|
| LangGraph State | Manage agent workflow state (content, link_type, summary) | — |
| RouteRequest | Classify link type (Webpage, PDF, Twitter, LinkedIn, YouTube, Unsupported) | Gemini 3 Flash |
| Content Extractors (5 tools) | Extract raw content from URLs | Tavily, PyMuPDF, twitterapi.io, AgentQL+Playwright |
| SummarizeContent | Generate markdown summary from extracted content | Gemini 3 Pro |
| run_agent() | Orchestrate entire pipeline | LangGraph executor |

**Tool Integration:**
- **tools/search.py** — Tavily API for web pages
- **tools/pdf_handler.py** — PyMuPDF for PDFs
- **tools/twitter_api_tool.py** — twitterapi.io for tweets
- **tools/youtube_agentql_scraper.py** — Playwright + AgentQL for YouTube
- **tools/linkedin_agentql_scraper.py** — Playwright + AgentQL for LinkedIn

**BAML Functions:**
- **router.baml** — RouteRequest(text) → LinkType enum
- **summarize.baml** — SummarizeContent(extracted_text) → markdown string
- **clients.baml** — Gemini 3 Flash/Pro clients + fallback + retry policies

**Error Handling:** Returns `"Error: ..."` string on failure  
**Latency:** 3–10s per link (varies by tool)

---

### Tools Subdirectory (5 files)

#### tools/__init__.py (minimal)
**Purpose:** Package marker  

---

#### tools/search.py
**Purpose:** Web page content extraction via Tavily  
**Key Function:** Tool that takes URL → returns title, full text, metadata  
**Dependencies:** tavily-python, requests

---

#### tools/pdf_handler.py
**Purpose:** PDF content extraction  
**Key Function:** Download PDF from URL → extract text via PyMuPDF  
**Dependencies:** fitz (PyMuPDF), requests

---

#### tools/twitter_api_tool.py
**Purpose:** Twitter/X tweet scraping  
**Key Function:** Fetch tweet text + author + replies via twitterapi.io  
**Dependencies:** requests, os.getenv (TWITTER_API_IO_KEY)

---

#### tools/youtube_agentql_scraper.py
**Purpose:** YouTube video title + description extraction  
**Key Function:** Use Playwright + AgentQL to scrape video metadata  
**Dependencies:** playwright, agentql

---

#### tools/linkedin_agentql_scraper.py
**Purpose:** LinkedIn post content extraction  
**Key Function:** Use Playwright + AgentQL to scrape post text + author  
**Dependencies:** playwright, agentql

---

### BAML Subdirectory (4 files)

#### baml_src/clients.baml
**Purpose:** LLM provider definitions + retry policies  

**Clients:**
```baml
client<llm> Gemini3Flash {
  provider google-ai
  options { model gemini-3-flash-preview, api_key env.GEMINI_API_KEY }
}

client<llm> Gemini3Pro {
  provider google-ai
  options { model gemini-3.1-pro-preview, api_key env.GEMINI_API_KEY }
}

client<llm> DeepSeekV3 {
  provider "openai"
  options { api_key env.DEEPSEEK_API_KEY, base_url "https://api.deepseek.com" }
}

client<llm> LLMFallback {
  provider fallback
  options { strategy [Gemini3Flash, DeepSeekV3] }
}
```

**Retry Policies:**
- Constant: 3 retries, 200ms delay
- Exponential: 2 retries, 300–10000ms backoff

---

#### baml_src/router.baml
**Purpose:** Link type classification  
**Function:** `RouteRequest(input_text: string) -> LinkType`  
**Output Types:** Webpage, PDF, Twitter, LinkedIn, YouTube, Unsupported  
**Model:** Gemini 3 Flash

---

#### baml_src/summarize.baml
**Purpose:** Content summarization  
**Function:** `SummarizeContent(extracted_text: string) -> string`  
**Output Format:** Markdown (# Title\n\nSummary text)  
**Model:** Gemini 3 Pro

---

#### baml_src/generators.baml
**Purpose:** Reserved for future generators  
**Status:** Placeholder (not used in Phase 1)

---

### Scripts Subdirectory (4+ files)

#### scripts/run_local.sh
**Purpose:** Local webhook mode with Uvicorn  
**Usage:** `./scripts/run_local.sh`  
**Requires:** WEBHOOK_URL, WEBHOOK_SECRET_PATH, TELEGRAM_WEBHOOK_SECRET_TOKEN in .env

---

#### scripts/run_docker.sh
**Purpose:** Build and run Docker container locally  
**Usage:** `./scripts/run_docker.sh`  
**Loads:** .env file for container environment

---

#### scripts/deploy_server.sh
**Purpose:** Deploy to self-managed server via Docker  
**Usage:** `./scripts/deploy_server.sh`  
**Docker Port:** 8080

---

#### scripts/deploy_cloud_run.sh
**Purpose:** Deploy to Google Cloud Run with secrets  
**Usage:** `./scripts/deploy_cloud_run.sh`  
**Secrets Mapping:** Maps env vars to Cloud Run secret manager

---

### Database Files

#### supabase/migrations/001_init_schema.sql
**Purpose:** Initial database schema  
**Tables Created:**
1. `messages` — Group message capture
2. `link_summaries` — Extracted & summarized links
3. `users` — User metadata
4. `user_chat_state` — Per-user per-chat tracking
5. `personal_sources` — Private user notes (future)
6. `exports` — NotebookLM exports (future)

**Indexes:** 5 total for query optimization  
**RLS Policy:** personal_sources user isolation (defense-in-depth)

---

### Documentation Files

#### docs/project-overview-pdr.md
**Purpose:** Product overview + requirements (this document)  
**Sections:** Executive summary, PDR, technical stack, privacy, roadmap, metrics

---

#### docs/system-architecture.md
**Purpose:** Technical architecture + module breakdown  
**Sections:** Architecture overview, module details, data model, request flows, error handling, performance

---

#### docs/code-standards.md
**Purpose:** Coding conventions + best practices  
**Sections:** Naming, type hints, docstrings, organization, error handling, logging, database conventions

---

#### docs/codebase-summary.md
**Purpose:** This file — quick reference guide  
**Sections:** File tree, responsibilities, key functions, dependencies

---

## Key Dependencies (pyproject.toml)

### Core Framework
- **python-telegram-bot[ext] >=21.0** — Telegram bot framework
- **fastapi >=0.115.12** — Web server
- **uvicorn >=0.34.2** — ASGI server

### Orchestration & LLM
- **baml-py >=0.88.0** — Structured LLM outputs
- **langgraph >=0.0.57** — Agentic workflow orchestration
- **langchain >=0.2.0** — LLM abstractions
- **langchain-community >=0.3.22** — Community integrations
- **langchain-openai >=0.1.7** — OpenAI integration (for fallback)

### Data & Storage
- **supabase >=2.0.0** — Postgres client
- **langgraph-checkpoint-sqlite >=2.0.6** — Checkpoint storage

### Content Extraction
- **tavily-python >=0.3.3** — Web search/extraction
- **pypdf >=4.2.0** — PDF reading
- **playwright** — Browser automation (YouTube, LinkedIn)

### Configuration & Utilities
- **python-dotenv >=1.0.1** — .env loading
- **requests >=2.31.0** — HTTP client
- **rich >=14.0.0** — Rich terminal output
- **loguru >=0.7.3** — Advanced logging

### AI Provider SDKs
- **google-genai >=0.1.0** — Google Gemini 3 direct SDK (Phase 7: via src/providers)
- **minimax-api >=0.2.0** — MiniMax M2.7 client (Phase 7: via src/providers)

### Development
- **marimo >=0.13.2** — Interactive notebooks
- **langgraph-cli[inmem] >=0.2.7** — CLI tools

---

## Execution Flows

### Sequence 1: Group Message with Link

```
User sends: "Check this: https://example.com"
  ↓
Telegram Webhook → bot.py:webhook()
  ↓
bot.py:group_message_handler()
  ├─ Extract: tg_msg_id, tg_chat_id, tg_user_id, text, timestamp
  ├─ Regex: find URLs (has_links = true)
  ↓
db.store_message(...) → UPSERT messages table
  ↓
db.upsert_user(...) → UPSERT users table
  ↓
db.ensure_user_chat_state(...) → UPSERT user_chat_state
  ↓
bot.py:_process_links_and_store(...) [async]
  ├─ agent.run_agent(text)
  │   ├─ BAML:RouteRequest → Gemini 3 Flash → "webpage"
  │   ├─ tools/search.py → Tavily → extract content
  │   ├─ BAML:SummarizeContent → Gemini 3 Pro → markdown summary
  ├─ db.store_link_summary(...)
  │   └─ UPSERT link_summaries table
  ├─ message.reply_text(summary)
  │   └─ Chunk by 4096 chars, send with 500ms delay
  ↓
HTTP Response: {"ok": True}
```

### Sequence 2: DM /start Command

```
User sends: "/start" in DM
  ↓
Telegram Webhook → bot.py:webhook()
  ↓
bot.py dispatches to CommandHandler("start", ...)
  ↓
commands.start_handler(Update, ContextTypes)
  ├─ Extract: user.first_name, user.id
  ├─ Build welcome message (HTML)
  ├─ Include COMMAND_LIST
  ↓
update.message.reply_text(welcome, parse_mode="HTML")
  ↓
HTTP Response: {"ok": True}
```

---

## Data Flow

### Group Messages (Shared Pool)
```
Telegram Group
  ↓ (message event)
bot.py (capture)
  ↓
Supabase messages table
  ↓
Phase 2+ commands (/catchup, /search, /topics)
  ├─ Query messages by tg_chat_id, timestamp
  ├─ JOIN with link_summaries
  ├─ Return to user
```

### Link Summaries (Shared Pool)
```
Group message with URLs
  ↓
agent.py (extract + summarize)
  ↓
Supabase link_summaries table
  ├─ url_normalized for dedup
  ├─ Indexed on message_id + url_normalized
  ↓
Group reply (user sees summary)
  ↓
Phase 2+ /search, /export
  ├─ Query by keyword, date range
  ├─ Return to user
```

### User State (Per-Chat Tracking)
```
First group message from user
  ↓
db.ensure_user_chat_state(tg_user_id, tg_chat_id)
  ↓
Supabase user_chat_state table
  ├─ PK: (tg_user_id, tg_chat_id)
  ├─ last_catchup_at tracking
  ↓
Phase 2+ /catchup
  ├─ Use last_catchup_at to filter new messages
  ├─ Update last_catchup_at on each /catchup call
```

---

## Configuration Checklist

### Required Environment Variables
```env
# Telegram
TELEGRAM_BOT_TOKEN=123:ABC...

# Supabase
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_KEY=eyJhb...

# Google Gemini
GEMINI_API_KEY=AIzaSy...

# Webhook (if not using polling)
WEBHOOK_URL=https://example.com or http://localhost:8080
WEBHOOK_SECRET_PATH=webhook_abc123
TELEGRAM_WEBHOOK_SECRET_TOKEN=strong_random_token

# Optional
USE_POLLING=true                    # For local dev
HOST=0.0.0.0                       # Default
PORT=8080                          # Default
GOOGLE_CLOUD_PROJECT=my-project    # Optional
GOOGLE_CLOUD_LOCATION=us-central1  # Default
```

### Initialization Steps (First Time)
1. Create Supabase project
2. Run migration: `supabase/migrations/001_init_schema.sql`
3. Create Telegram bot via @BotFather
4. Set environment variables in `.env`
5. Install dependencies: `uv pip install -e .`
6. Install Playwright browsers: `playwright install`
7. Run locally: `python bot.py` (polling mode)
8. Test: Send message with link to bot in test group

---

## Testing (Phase 2+)

### Missing Test Coverage
- [ ] `test_url_normalize.py` — URL dedup logic
- [ ] `test_db.py` — Store/retrieve operations
- [ ] `test_commands.py` — Handler behavior
- [ ] `test_bot_webhook.py` — Webhook endpoint
- [ ] `test_agent_integration.py` — End-to-end link summarization

### Manual Testing Checklist
- [ ] Group message captured to Supabase
- [ ] URL extracted from message text
- [ ] Link summary generated
- [ ] Reply sent to group within 10s
- [ ] Duplicate message ignored (idempotency)
- [ ] Duplicate URL in same message ignored
- [ ] `/start` DM returns welcome message
- [ ] Webhook secret token validation works

---

## Performance Metrics

| Operation | Latency | Throughput | Notes |
|-----------|---------|-----------|-------|
| Message capture | ~100ms | 30 msgs/sec (Telegram limit) | Supabase insert |
| URL detection | ~50ms | Per message | Regex match |
| Link extraction | 2–10s | 1 per message | Tool-dependent (PDF slower) |
| Summary generation | 1–3s | 1 per extraction | Gemini 3 Pro |
| Group reply | 100–500ms | Per chunk | 4096 char chunks, 500ms delay |
| Database query | 10–100ms | Indexed lookups | With proper indexes |

---

## Future Phases

### Phase 2: DM Commands
- `/catchup` — Digest of recent discussions
- `/search <keyword>` — Full-text search
- `/topics` — List active threads
- `/topic <name>` — Deep dive view
- New DB queries + caching strategy

### Phase 3: AI Workflows
- `/draft <topic>` — Brainstorm with context
- `/decide <topic>` — Decision framework
- Context retrieval from group + personal sources

### Phase 4: Extended Features
- `/remind` — Smart reminders
- `/export` — NotebookLM integration
- `/note` — Personal annotations
- `/sources` — Manage source library
- Exports table + NotebookLM API integration

---

## Glossary

| Term | Definition |
|------|-----------|
| **Murmur** | Project name; bot identity as "team's silent listener" |
| **Link Type** | Classification: webpage, PDF, tweet, youtube, linkedin |
| **URL Normalized** | Cleaned URL (lowercase, no tracking params, consistent) |
| **Dedup** | Duplicate detection; prevents storing same link twice |
| **Shared Pool** | messages + link_summaries; accessible to all group members |
| **Private Pool** | personal_sources; per-user, never shared |
| **user_chat_state** | Tracks user's presence in group + /catchup timestamp |
| **RLS** | Row-Level Security; database-layer access control |
| **Idempotent** | Operation can be repeated safely; same result |
| **BAML** | Boundary ML; structured LLM output framework |
| **LangGraph** | Agentic workflow orchestration framework |
| **Tavily** | Web search and content extraction service |
| **AgentQL** | Browser automation query language (Playwright-based) |

