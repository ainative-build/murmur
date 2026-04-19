# System Architecture

**Last Updated:** 2026-04-19  
**Phase:** 1 Foundation  

## Architecture Overview

Murmur Bot implements a three-tier architecture: Telegram API layer → FastAPI bot handler → Supabase persistence → LLM orchestration.

```
┌─────────────────────────────────────────────────────────────────┐
│                     Telegram (External)                         │
│         Group Messages & DM Commands                            │
└────────┬──────────────────────┬─────────────────────────────────┘
         │                      │
         v                      v
    [Group Message]         [DM Command]
         │                      │
         └──────────┬───────────┘
                    v
         ┌──────────────────────┐
         │   bot.py (FastAPI)   │
         │  ┌────────────────┐  │
         │  │ group_handler  │  │ ← Captures ALL group messages
         │  ├────────────────┤  │
         │  │ start_handler  │  │ ← /start welcome command
         │  └────────────────┘  │
         └────────┬─────────────┘
                  │
    ┌─────────────┼──────────────┐
    │             │              │
    v             v              v
[store_msg]  [run_agent]  [upsert_user]
    │             │              │
    └─────────────┼──────────────┘
                  v
         ┌──────────────────────┐
         │    db.py             │
         │  (Supabase Client)   │
         └────────┬─────────────┘
                  │
         ┌────────v──────────────────┐
         │   Supabase (Postgres)     │
         │  ┌──────────────────────┐ │
         │  │ messages (shared)    │ │
         │  │ link_summaries       │ │
         │  │ users                │ │
         │  │ user_chat_state      │ │
         │  │ personal_sources     │ │
         │  │ exports              │ │
         │  └──────────────────────┘ │
         └──────────────────────────┘
                  │
         ┌────────v──────────────────┐
         │   agent.py (LangGraph)    │
         │  [If message has links]   │
         │  ┌──────────────────────┐ │
         │  │ Route via BAML        │ │
         │  │ Extract (5 tools)     │ │
         │  │ Summarize (Gemini 3)  │ │
         │  │ Reply to group        │ │
         │  └──────────────────────┘ │
         └──────────────────────────┘
```

---

## Module Breakdown

### bot.py — FastAPI + Python-Telegram-Bot Wrapper

**File:** `/bot.py` (291 lines)  
**Role:** HTTP server + Telegram update handler  

#### Responsibilities
- FastAPI lifespan management (startup/shutdown)
- Webhook endpoint for incoming Telegram updates
- Handler registration (commands + message filters)
- Group message capture and link detection
- Health check endpoint

#### Key Functions
| Function | Input | Output | Action |
|----------|-------|--------|--------|
| `group_message_handler` | `Update`, `ContextTypes` | `None` | Capture group message → store_message() → detect links → run_agent() if links found |
| `_process_links_and_store` | `Update`, `urls`, `message_id` | `None` | Run agent → store summary → reply to group (chunked for Telegram 4096 limit) |
| `_detect_link_type` | `url` | `str` | Heuristic type detection (tweet, youtube, linkedin, pdf, webpage) |
| `webhook` | `Request`, `secret_token` | `dict` | Validate token → parse JSON → dispatch update → return 200 |
| `health_check` | — | `dict` | Return `{"status": "ok"}` |

#### Execution Modes
- **Polling:** `USE_POLLING=true` → Long-polling from Telegram servers (dev mode)
- **Webhook:** `USE_POLLING=false` + `WEBHOOK_URL` → FastAPI listens for POST at `/{WEBHOOK_SECRET_PATH}`

---

### config.py — Environment Configuration

**File:** `/config.py` (42 lines)  
**Role:** Centralized env var loading  

#### Variables Managed
| Variable | Source | Used By |
|----------|--------|---------|
| `BOT_TOKEN` | `TELEGRAM_BOT_TOKEN` | bot.py, Application.builder() |
| `WEBHOOK_URL`, `WEBHOOK_SECRET_PATH`, `WEBHOOK_SECRET_TOKEN` | `WEBHOOK_*` env vars | bot.py webhook setup |
| `USE_POLLING` | `USE_POLLING` env var | bot.py lifespan selection |
| `SUPABASE_URL`, `SUPABASE_KEY` | `SUPABASE_*` env vars | db.py client init |
| `GEMINI_API_KEY`, `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION` | Google env vars | BAML clients (via env) |
| `HOST`, `PORT` | `HOST`, `PORT` (defaults: 0.0.0.0, 8080) | uvicorn startup |
| `IS_CLOUD_RUN`, `K_SERVICE`, `K_REVISION`, `K_REGION` | Cloud Run runtime vars | Deployment detection |

---

### db.py — Supabase Client Wrapper

**File:** `/db.py` (127 lines)  
**Role:** Singleton Supabase connection + data persistence  

#### Singleton Pattern
```python
_client: Optional[Client] = None

def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
    return _client
```

#### Core Functions

| Function | Parameters | Returns | DB Operation |
|----------|-----------|---------|--------------|
| `store_message()` | tg_msg_id, tg_chat_id, tg_user_id, username, text, timestamp, has_links, reply_to_tg_msg_id, forwarded_from | `int \| None` (id) | UPSERT into `messages` table (dedup: UNIQUE(tg_chat_id, tg_msg_id)) |
| `store_link_summary()` | message_id, url, link_type, title, extracted_content, summary | `int \| None` (id) | UPSERT into `link_summaries` (dedup: UNIQUE(message_id, url_normalized)) |
| `upsert_user()` | tg_user_id, username | `None` | UPSERT into `users` table |
| `ensure_user_chat_state()` | tg_user_id, tg_chat_id | `None` | UPSERT into `user_chat_state` |

#### Idempotency Strategy
- All UPSERTs use `on_conflict` with `ignore_duplicates=True` to prevent errors on duplicate inserts
- Duplicate inserts return `None` (handled gracefully in bot.py)

---

### commands.py — DM Command Handlers

**File:** `/commands.py` (38 lines)  
**Role:** Telegram command processing  

#### Current Commands
| Command | Handler | Output |
|---------|---------|--------|
| `/start` | `start_handler()` | Welcome message + planned command list (HTML formatted) |

#### Future Commands (Phase 2+)
- `/catchup` — Recent discussion digest
- `/search <keyword>` — Full-text search
- `/topics` — List active threads
- `/topic <name>` — Deep dive view
- `/draft <topic>`, `/decide <topic>` — AI-powered workflows
- `/note`, `/sources`, `/remind`, `/export` — Extended features

---

### url_normalize.py — URL Deduplication

**File:** `/url_normalize.py` (43 lines)  
**Role:** Normalize URLs for reliable dedup  

#### Normalization Pipeline
```
Input URL: https://example.com:443/path/?utm_source=twitter&id=123
↓
1. Parse (scheme, host, port, path, query)
2. Lowercase scheme + host
3. Strip default ports (80 for http, 443 for https)
4. Strip trailing slash from path
5. Parse query string
6. Remove tracking params (utm_*, fbclid, gclid, ref, etc.)
7. Sort remaining params
8. Reconstruct URL
↓
Output: https://example.com/path?id=123
```

#### Tracking Parameters Stripped
- `utm_*` (source, medium, campaign, term, content)
- `fbclid`, `gclid` (Facebook, Google click tracking)
- `ref`, `source`, `mc_cid`, `mc_eid` (referral, mailchimp)

#### Usage
```python
url_norm = normalize_url("https://example.com:443/path?utm_source=twitter")
# → "https://example.com/path"
```

---

### agent.py — LangGraph Orchestration

**File:** `/agent.py` (846 lines)  
**Role:** Multi-step reasoning pipeline for link summarization  

#### Pipeline Architecture
```
Input: Raw message text with URL(s)
  ↓
1. Route Request (BAML + Gemini 3 Flash)
   ├─ Webpage → TavilyAPI
   ├─ PDF → PyMuPDF
   ├─ Twitter → twitterapi.io
   ├─ LinkedIn → AgentQL + Playwright
   ├─ YouTube → AgentQL + Playwright
   └─ Unsupported → Error response
  ↓
2. Extract Content
   ├─ Tool-specific extraction (title, full text, metadata)
   └─ Return structured content
  ↓
3. Summarize (BAML + Gemini 3 Pro)
   ├─ Input: extracted content
   ├─ Output: concise markdown summary
   └─ Format: # Title\n\nSummary text
  ↓
Output: Summary markdown
```

#### Content Extractors (5 Tools)

| Tool | Module | Provider | Input | Output |
|------|--------|----------|-------|--------|
| **Web Search** | `tools/search.py` | Tavily SDK | URL (webpage) | Title, full text, metadata |
| **PDF Handler** | `tools/pdf_handler.py` | PyMuPDF (fitz) | URL (→ file bytes) | Text + metadata |
| **Twitter API** | `tools/twitter_api_tool.py` | twitterapi.io | URL (tweet/thread) | Tweet text + author + replies |
| **YouTube** | `tools/youtube_agentql_scraper.py` | Playwright + AgentQL | URL (youtube.com) | Title, description, transcript hints |
| **LinkedIn** | `tools/linkedin_agentql_scraper.py` | Playwright + AgentQL | URL (linkedin.com) | Post text, author, engagement metrics |

#### BAML Integration
- **Router Function:** Classifies URL type → selects extraction tool
- **Summarizer Function:** Transforms extracted content → markdown summary
- **Clients:** Gemini 3 Flash (routing) + Pro (summarization), with DeepSeek fallback

---

### baml_src/ — BAML Definitions

**Files:**
- `clients.baml` — LLM providers + retry policies
- `router.baml` — RouteRequest function
- `summarize.baml` — SummarizeContent function
- `generators.baml` — Additional generators (future)

#### clients.baml Configuration

```baml
client<llm> Gemini3Flash {
  provider google-ai
  options {
    model gemini-3-flash-preview
    api_key env.GEMINI_API_KEY
  }
}

client<llm> Gemini3Pro {
  provider google-ai
  options {
    model gemini-3.1-pro-preview
    api_key env.GEMINI_API_KEY
  }
}

client<llm> LLMFallback {
  provider fallback
  options {
    strategy [Gemini3Flash, DeepSeekV3]
  }
}
```

#### Retry Policies
- **Constant:** 3 retries, 200ms delay
- **Exponential:** 2 retries, 300ms → max 10s

---

## Data Model

### Database Schema (Supabase/Postgres)

#### messages (Group Message Capture)
```sql
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
```

**Indexes:** `(tg_chat_id, timestamp)`, `(tg_user_id)`

#### link_summaries (Extracted & Summarized Links)
```sql
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
```

**Indexes:** `(message_id)`, `(url_normalized)`

#### users (User Metadata)
```sql
CREATE TABLE users (
    tg_user_id BIGINT PRIMARY KEY,
    username TEXT,
    reminder_frequency TEXT DEFAULT 'off',
    timezone TEXT DEFAULT 'UTC',
    reminder_time TEXT DEFAULT '09:00',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

#### user_chat_state (Per-User Per-Chat Tracking)
```sql
CREATE TABLE user_chat_state (
    tg_user_id BIGINT NOT NULL,
    tg_chat_id BIGINT NOT NULL,
    last_catchup_at TIMESTAMPTZ,
    PRIMARY KEY (tg_user_id, tg_chat_id)
);
```

#### personal_sources (Private User Notes) — Phase 2+
```sql
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
);
-- RLS policy: tg_user_id = current_setting('app.current_user_id')
```

#### exports (NotebookLM Exports) — Phase 4+
```sql
CREATE TABLE exports (
    id BIGSERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    export_target TEXT DEFAULT 'notebooklm',
    content_hash TEXT NOT NULL,
    notebooklm_source_id TEXT,
    exported_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (export_target, content_hash)
);
```

---

## Request/Response Flow

### Scenario 1: Group Message with Link

```
1. User sends: "Check this out: https://example.com"
   ↓
2. Telegram → webhook POST /{WEBHOOK_SECRET_PATH}
   ├─ Validate secret_token
   ├─ Parse JSON → Update object
   ↓
3. bot.group_message_handler(Update, ContextTypes)
   ├─ Extract: tg_msg_id, tg_chat_id, tg_user_id, text, timestamp
   ├─ Regex match: find URLs
   ├─ has_links = true (1 URL found)
   ↓
4. db.store_message(...)
   ├─ INSERT INTO messages VALUES(...)
   ├─ ON CONFLICT DO NOTHING (idempotent)
   └─ Return message_id
   ↓
5. db.upsert_user(...) / db.ensure_user_chat_state(...)
   ├─ Create or update user record
   ├─ Ensure user_chat_state row exists
   ↓
6. if has_links and message_id:
   ├─ await _process_links_and_store(message, text, urls, message_id)
   ↓
7. run_agent(text)
   ├─ Call LangGraph + agent.py pipeline
   ├─ Route URL → Extract → Summarize
   ├─ Return summary markdown
   ↓
8. db.store_link_summary(message_id, url, link_type, title, summary)
   ├─ INSERT INTO link_summaries
   ├─ ON CONFLICT (message_id, url_normalized) DO NOTHING
   ↓
9. message.reply_text(summary)
   ├─ Chunk by 4096 chars (Telegram limit)
   ├─ HTML escape each chunk
   ├─ Send replies (500ms delay between chunks)
   ↓
10. Return {"ok": True} to webhook endpoint
```

### Scenario 2: DM /start Command

```
1. User sends: "/start" in DM
   ↓
2. Telegram → webhook POST /{WEBHOOK_SECRET_PATH}
   ├─ Parse Update with message.chat_id < 0 (DM)
   ↓
3. bot.py dispatches to CommandHandler("start", ...)
   ↓
4. commands.start_handler(Update, ContextTypes)
   ├─ Extract user.first_name, user.id
   ├─ Build welcome message (HTML)
   ├─ Include COMMAND_LIST
   ↓
5. update.message.reply_text(welcome, parse_mode="HTML")
   ├─ Send formatted message
   ↓
6. Return {"ok": True}
```

---

## Error Handling

### Message Storage Failures
- **Problem:** Supabase outage or constraint violation
- **Handling:** Log error, return `None`, continue (message lost but bot doesn't crash)
- **Improvement (Phase 2):** Local queue + retry

### Link Extraction Failures
- **Problem:** URL unreachable, extraction tool fails
- **Handling:** `run_agent()` returns `"Error: ..."` string
- **Response:** Log error, don't reply to group (silent failure)

### Webhook Token Mismatch
- **Problem:** Invalid or missing secret token
- **Response:** HTTP 403, log and ignore

### Bot Not Initialized
- **Problem:** Webhook received before lifespan startup complete
- **Response:** HTTP 503 Service Unavailable

---

## Configuration & Deployment

### Environment Variables
| Variable | Example | Required | Used By |
|----------|---------|----------|---------|
| `TELEGRAM_BOT_TOKEN` | `123:ABC...` | Yes | bot.py |
| `WEBHOOK_URL` | `https://example.com` | Yes (webhook mode) | bot.py |
| `WEBHOOK_SECRET_PATH` | `webhook_abc123` | No (default: webhook) | bot.py |
| `TELEGRAM_WEBHOOK_SECRET_TOKEN` | `secret_token_xyz` | Yes (webhook mode) | bot.py |
| `USE_POLLING` | `true` or `false` | No (default: false) | bot.py |
| `SUPABASE_URL` | `https://*.supabase.co` | Yes | db.py |
| `SUPABASE_KEY` | `eyJhb...` | Yes | db.py |
| `GEMINI_API_KEY` | `AIzaSy...` | Yes | BAML clients |
| `HOST` | `0.0.0.0` | No (default) | uvicorn |
| `PORT` | `8080` | No (default) | uvicorn |

### Deployment Modes

| Mode | Command | Use Case |
|------|---------|----------|
| **Polling (Dev)** | `USE_POLLING=true python bot.py` | Local dev, testing |
| **Webhook Local** | `./scripts/run_local.sh` + ngrok | Local dev with real Telegram |
| **Docker Local** | `./scripts/run_docker.sh` | Test Docker image locally |
| **Self-Managed Server** | `./scripts/deploy_server.sh` | Own VPS/dedicated server |
| **Google Cloud Run** | `./scripts/deploy_cloud_run.sh` | Managed serverless (production) |

---

## Performance Characteristics

### Latency
- **Message Capture:** ~100ms (Supabase insert)
- **Link Detection:** ~50ms (regex match)
- **Agent Pipeline:** 3–10s (extraction varies by tool)
  - PDF extraction: 2–5s
  - YouTube: 3–8s
  - Twitter: 1–2s
  - Web scrape: 2–5s
- **Reply Send:** 500ms per chunk (rate limit to avoid Telegram rate limits)

### Throughput
- **Concurrent Groups:** Limited by Telegram rate limits (~30 msgs/sec per bot)
- **Link Processing:** Sequential per message (one agent run at a time)
- **Database:** Supabase scales horizontally (standard tier: ~1000 concurrent connections)

### Storage
- Average message: ~500 bytes
- Average summary: ~1KB
- Example: 1,000 messages/day × 30 days = 30,000 messages ≈ 45MB

---

## Testing & Validation

### Unit Tests (Missing — Phase 2)
- `test_url_normalize.py` — URL dedup logic
- `test_db.py` — Store/retrieve messages
- `test_commands.py` — Command handlers

### Integration Tests (Missing — Phase 2)
- End-to-end webhook processing
- Agent pipeline with real links
- Supabase persistence validation

### Manual Testing
- Local polling mode: `USE_POLLING=true python bot.py`
- Send message with link to bot in test group
- Verify message appears in Supabase
- Verify summary is generated and returned

