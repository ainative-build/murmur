# Code Standards & Conventions

**Last Updated:** 2026-04-19  
**Phase:** 1 Foundation  

## Python Code Style

### Naming Conventions

#### Variables & Functions (snake_case)
```python
# Functions
def store_message(tg_msg_id: int, tg_chat_id: int) -> Optional[int]:
    """Store a message in Supabase."""
    pass

def get_client() -> Client:
    """Return singleton Supabase client."""
    pass

# Variables
message_id = 123
has_links = True
tg_user_id = 456
url_normalized = normalize_url(url)
```

#### Classes (PascalCase)
```python
class MessageHandler:
    """Handle Telegram messages."""
    pass

# Telegram types
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler
```

#### Constants (UPPER_SNAKE_CASE)
```python
MAX_TELEGRAM_MSG_LEN = 4096
URL_REGEX = r"(https?:\/\/[^\s]+)"
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "fbclid", "gclid"
})
COMMAND_LIST = """<b>Available Commands</b>..."""
```

#### Private/Internal (Leading Underscore)
```python
# File-scoped
_client: Optional[Client] = None

# Private functions
def _register_handlers(app: Application) -> None:
    """Register all handlers on PTB Application."""
    pass

def _detect_link_type(url: str) -> str:
    """Heuristic to detect link type."""
    pass

def _safe_process_update(update: Update) -> None:
    """Process update with error logging."""
    pass
```

---

### Type Hints (PEP 484)

**Required for all functions.** Use explicit types, not inferred.

```python
# Good
def store_message(
    tg_msg_id: int,
    tg_chat_id: int,
    tg_user_id: int,
    username: Optional[str],
    text: Optional[str],
    timestamp: datetime,
    has_links: bool = False,
    reply_to_tg_msg_id: Optional[int] = None,
) -> Optional[int]:
    """Store a group message. Returns internal id or None if duplicate."""
    pass

# Good (return type annotation)
async def webhook(request: Request, secret_token: str | None = Header(...)) -> dict:
    """Handle incoming Telegram updates."""
    pass

# Python 3.10+ union syntax
response: str | None = None
urls: list[str] = []
config_dict: dict[str, Any] = {}
```

**Optional imports:**
```python
from typing import Optional, Any
from datetime import datetime, timezone
```

---

### Docstrings (Google Style)

**Every function and class must have a docstring.**

```python
def store_message(
    tg_msg_id: int,
    tg_chat_id: int,
    text: Optional[str],
    timestamp: datetime,
    has_links: bool = False,
) -> Optional[int]:
    """Store a group message. Returns internal id or None if duplicate.

    Idempotent via UNIQUE (tg_chat_id, tg_msg_id) — duplicates are ignored.

    Args:
        tg_msg_id: Telegram message ID
        tg_chat_id: Telegram chat ID
        text: Message text content
        timestamp: Message timestamp (UTC)
        has_links: Whether message contains URLs

    Returns:
        Internal message ID if inserted, None if duplicate or error.

    Raises:
        RuntimeError: If Supabase client not initialized.
    """
    client = get_client()
    # Implementation...
```

**Class docstrings:**
```python
class MessageHandler:
    """Telegram message handler for group and DM messages.

    Handles:
    - Group message capture (all text messages)
    - DM command processing (/start, /catchup, etc.)
    - Link detection and agent pipeline dispatch
    """
```

---

### Code Organization

#### Imports (PEP 8)
Order: stdlib → third-party → local

```python
# Standard library (alphabetical)
import asyncio
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

# Third-party (alphabetical)
from fastapi import FastAPI, Request, Response, HTTPException, Header
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.constants import ParseMode
import uvicorn

# Local
import config
import db
from agent import run_agent
from commands import start_handler
```

#### Module Structure (bot.py Example)
```python
"""Murmur Bot — Telegram bot with group message capture, link summarization, and DM commands.

FastAPI + python-telegram-bot v21+. Supports webhook (production) and polling (local dev).
"""

# 1. Imports
import logging
# ...

# 2. Logging configuration
logging.basicConfig(...)
logger = logging.getLogger(__name__)

# 3. Constants
URL_REGEX = r"..."
MAX_TELEGRAM_MSG_LEN = 4096

# 4. Global state (with docstring)
ptb_app: Optional[Application] = None  # PTB app constructed lazily in lifespan

# 5. Helper functions
def _register_handlers(app: Application) -> None:
    """Register all handlers on a PTB Application."""
    pass

# 6. Handler functions
async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture ALL group messages into Supabase."""
    pass

# 7. Lifespan and app setup
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown lifecycle management."""
    yield

app = FastAPI(lifespan=lifespan)

# 8. Endpoints
@app.post(f"/{config.WEBHOOK_SECRET_PATH}")
async def webhook(request: Request, ...) -> dict:
    """Handle incoming Telegram updates via webhook."""
    pass

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    pass

# 9. Direct execution (if __name__ == "__main__")
if __name__ == "__main__":
    # Direct execution logic
    pass
```

---

### Error Handling

**Use try-except with specific exceptions. Log errors with context.**

```python
# Good: Specific exception, log with context
def store_message(...) -> Optional[int]:
    """Store a group message."""
    client = get_client()
    row = {...}
    try:
        result = client.table("messages").upsert(row, ...).execute()
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Failed to store message: {e}")
        return None

# Good: Async with error logging
async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture group messages."""
    try:
        message = update.effective_message
        if not message or not message.text:
            return
        # Process message
    except Exception as e:
        logger.error(f"Update processing failed: {e}", exc_info=True)

# Good: Graceful fallback
async def _process_links_and_store(message, text: str, urls: list[str], message_id: int) -> None:
    """Run agent pipeline on link message."""
    try:
        agent_result = await run_agent(text)
        if isinstance(agent_result, str) and not agent_result.startswith("Error:"):
            # Process successful result
            pass
        elif isinstance(agent_result, str):
            logger.error(f"Agent error for {urls[0]}: {agent_result}")
        else:
            logger.error(f"Agent returned {type(agent_result)} for {urls[0]}")
    except Exception as e:
        logger.error(f"Error processing links: {e}", exc_info=True)
```

---

### Logging

**Use module-scoped logger for all logging.**

```python
import logging

logger = logging.getLogger(__name__)

# Log levels
logger.debug("Detailed info for diagnosis")
logger.info("Informational message (bot startup, successful operations)")
logger.warning("Warning without preventing operation")
logger.error("Error condition (but bot continues)")
logger.critical("Critical failure (shutdown required)")

# Include context
logger.info(f"Storing message {tg_msg_id} in chat {tg_chat_id}")
logger.error(f"Failed to store message: {e}")
logger.error(f"Update processing failed: {e}", exc_info=True)  # Include traceback
```

**Logging Configuration (bot.py):**
```python
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)  # Suppress noisy libraries
```

---

### Async/Await

**Use async for all I/O-bound operations (Telegram, Supabase, HTTP).**

```python
# Good: Async handler for Telegram message
async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Async handler required by python-telegram-bot."""
    message = update.effective_message
    # Sync DB calls are OK (blocking but short)
    message_id = db.store_message(...)
    # Async for agent + reply
    if has_links and message_id:
        await _process_links_and_store(message, text, urls, message_id)

# Good: Async with asyncio.create_task for non-blocking dispatch
@app.post(f"/{config.WEBHOOK_SECRET_PATH}")
async def webhook(request: Request, ...) -> dict:
    """Handle webhook asynchronously."""
    update = Update.de_json(update_data, ptb_app.bot)
    asyncio.create_task(_safe_process_update(update))  # Non-blocking
    return {"ok": True}

# Good: Sleep for rate limiting
if i + MAX_TELEGRAM_MSG_LEN < len(agent_result):
    await asyncio.sleep(0.5)  # Avoid Telegram rate limits
```

---

## Database Conventions

### Column Naming

#### Telegram ID Fields (BIGINT)
```sql
tg_msg_id      -- Telegram message ID
tg_chat_id     -- Telegram chat ID (negative for groups)
tg_user_id     -- Telegram user ID (always positive)
```

#### Internal Surrogate Keys
```sql
id             -- Auto-increment BIGSERIAL PRIMARY KEY
```

#### Timestamps
```sql
timestamp      -- Original Telegram timestamp (UTC)
created_at     -- Database record creation time (UTC)
last_catchup_at -- User-specific tracking timestamp
```

#### Booleans
```sql
has_links      -- Boolean flag for message content type
```

#### Text Fields
```sql
text           -- Raw message text
username       -- Telegram username (@handle)
title          -- Link or content title
summary        -- Generated summary or snippet
url            -- Original URL (as-is)
url_normalized -- Normalized URL (for dedup)
```

---

### Table Constraints & Indexes

#### Unique Constraints (Prevent Duplicates)
```sql
-- messages: dedup by Telegram source ID
UNIQUE (tg_chat_id, tg_msg_id)

-- link_summaries: dedup by normalized URL per message
UNIQUE (message_id, url_normalized)

-- exports: dedup by content hash per target
UNIQUE (export_target, content_hash)
```

#### Primary Keys
```sql
-- Surrogate keys for referential integrity
id BIGSERIAL PRIMARY KEY

-- Composite primary keys for intersection tables
PRIMARY KEY (tg_user_id, tg_chat_id)
```

#### Indexes (Query Performance)
```sql
-- messages
CREATE INDEX idx_messages_chat_timestamp ON messages(tg_chat_id, timestamp);
CREATE INDEX idx_messages_user ON messages(tg_user_id);

-- link_summaries
CREATE INDEX idx_links_message ON link_summaries(message_id);
CREATE INDEX idx_links_url_normalized ON link_summaries(url_normalized);

-- personal_sources
CREATE INDEX idx_personal_user ON personal_sources(tg_user_id, created_at);
CREATE INDEX idx_personal_url ON personal_sources(tg_user_id, url_normalized);
```

---

### Data Types

| Field | Type | Rationale |
|-------|------|-----------|
| `id` | BIGSERIAL | Auto-increment surrogate key |
| `tg_*_id` | BIGINT | Telegram's native IDs are 64-bit |
| `timestamp` | TIMESTAMPTZ | UTC with timezone awareness |
| `created_at` | TIMESTAMPTZ | Database insert time |
| `text`, `title`, `summary` | TEXT | Unbounded string content |
| `url`, `url_normalized` | TEXT | URLs (no length limit assumed) |
| `has_links` | BOOLEAN | Link presence flag |
| `link_type` | TEXT | Enum-like (webpage, pdf, tweet, youtube, linkedin) |
| `content_hash` | TEXT | SHA256 hex string (64 chars) |

---

### SQL Style

```sql
-- Keywords UPPERCASE, identifiers lowercase_with_underscores
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

-- Comments for schema clarity
CREATE TABLE user_chat_state (
    tg_user_id BIGINT NOT NULL,
    tg_chat_id BIGINT NOT NULL,
    last_catchup_at TIMESTAMPTZ,
    PRIMARY KEY (tg_user_id, tg_chat_id)
);
```

---

## AI Provider Integration

**Rule:** All LLM calls go through `src/providers/`. No direct `google.genai` or MiniMax imports outside `src/providers/`.

```python
# Correct: via provider abstraction
from src.providers import Feature, get_provider
provider = get_provider(Feature.TEXT)
result = await provider.text_to_text(system_prompt=..., user_input=...)

# Wrong: violates abstraction
import google.genai
genai.configure(...)  # Forbid in app code
```

**Exception:** BAML clients hardcode Gemini (acceptable; tracked for future migration).

---

## BAML Code Conventions

### File Organization

#### clients.baml
```baml
// LLM client definitions only
client<llm> Gemini3Flash { ... }
client<llm> Gemini3Pro { ... }
retry_policy Constant { ... }
```

#### router.baml
```baml
// RouteRequest function + supporting types
enum LinkType { ... }
function RouteRequest(input_text: string) -> LinkType { ... }
```

#### summarize.baml
```baml
// SummarizeContent function + supporting types
function SummarizeContent(extracted_text: string) -> string { ... }
```

### Model Selection

| Task | Model | Rationale |
|------|-------|-----------|
| Routing (link type) | Gemini 3 Flash | Fast inference, lower cost, sufficient accuracy |
| Summarization | Gemini 3 Pro | Better quality for longer summaries |
| Fallback | DeepSeek V3 | Open alternative, cost-effective |

### Retry Strategy
- **Routing:** Constant (3 retries, 200ms delay) — quick failure detection
- **Summarization:** Exponential (2 retries, 300–10000ms) — graceful backoff

---

## Testing Conventions (Phase 2+)

### Test File Naming
```python
# Unit tests: test_{module}.py
test_url_normalize.py  # Tests for url_normalize.py
test_db.py             # Tests for db.py
test_commands.py       # Tests for commands.py

# Integration tests: test_{feature}_integration.py
test_webhook_integration.py
test_agent_integration.py
```

### Test Structure
Use pytest with AsyncMock for async handlers. Arrange-Act-Assert pattern.
```python
@pytest.mark.asyncio
async def test_group_message_handler_stores_message():
    """Test message storage."""
    mock_update = AsyncMock()
    mock_update.effective_message = AsyncMock()
    await group_message_handler(mock_update, AsyncMock())
    # Verify db.store_message called
```

---

## File Structure

### Root Level Files (Flat Structure)
```
/bot.py                 # FastAPI + PTB wrapper
/config.py              # Environment configuration
/db.py                  # Supabase client
/commands.py            # DM command handlers
/url_normalize.py       # URL dedup utilities
/agent.py               # LangGraph orchestration
/agent_viz.py           # Visualization script (dev)
```

### Subdirectories
```
/baml_src/
  ├── clients.baml      # LLM client definitions
  ├── router.baml       # RouteRequest function
  ├── summarize.baml    # SummarizeContent function
  └── generators.baml   # Future generators

/tools/
  ├── __init__.py
  ├── pdf_handler.py    # PyMuPDF PDF extraction
  ├── search.py         # Tavily web search
  ├── twitter_api_tool.py       # twitterapi.io integration
  ├── youtube_agentql_scraper.py  # Playwright YouTube scraping
  └── linkedin_agentql_scraper.py # Playwright LinkedIn scraping

/docs/
  ├── project-overview-pdr.md
  ├── system-architecture.md
  ├── code-standards.md
  ├── codebase-summary.md
  └── development-roadmap.md

/scripts/
  ├── run_local.sh      # Local webhook mode
  ├── run_docker.sh     # Docker testing
  ├── deploy_server.sh  # Self-managed server
  └── deploy_cloud_run.sh  # Google Cloud Run

/supabase/
  └── migrations/
      └── 001_init_schema.sql  # Database schema
```

---

## File Naming Conventions

### Python Files (kebab-case)
```
url_normalize.py     ✓ Descriptive, self-documenting
twitter_api_tool.py  ✓ Matches module responsibility
pdf_handler.py       ✓ Clear handler pattern
```

### Bash Scripts (kebab-case)
```
run_local.sh         ✓ Clear, executable name
deploy_server.sh     ✓ Action-oriented name
```

### SQL Migrations (numbered, descriptive)
```
001_init_schema.sql       ✓ Schema creation (must run first)
002_add_rls_policies.sql  ✓ Security policies
003_create_indexes.sql    ✓ Performance optimization
```

---

## Constants & Magic Numbers

**Avoid magic numbers. Define as constants with clear names.**

```python
# Good
MAX_TELEGRAM_MSG_LEN = 4096  # Telegram API limit per message
CHUNK_SLEEP_MS = 0.5          # Sleep between message replies (avoid rate limits)
URL_REGEX = r"(https?:\/\/[^\s]+)"  # Regex pattern for URL detection

# BAML retry policies
RETRY_CONSTANT_RETRIES = 3
RETRY_CONSTANT_DELAY_MS = 200

RETRY_EXPONENTIAL_RETRIES = 2
RETRY_EXPONENTIAL_INITIAL_MS = 300
RETRY_EXPONENTIAL_MULTIPLIER = 1.5
RETRY_EXPONENTIAL_MAX_MS = 10000

# Bad: Magic numbers in code
await asyncio.sleep(0.5)        # What is 0.5? Why?
for i in range(0, len(x), 4096):  # What is 4096?
```

---

## Comments & Documentation

### When to Comment
```python
# Good: Explains "why", not "what"
# Use UNIQUE(tg_chat_id, tg_msg_id) for idempotency.
# Duplicates are silently ignored via Supabase conflict handling.
UNIQUE (tg_chat_id, tg_msg_id)

# Good: Complex logic
# Strip trailing slash but preserve "/" for root path
path = parsed.path.rstrip("/") or "/"

# Good: Non-obvious behavior
# LLM membership verification uses user_chat_state (v1 approximation).
# Does NOT confirm live Telegram membership — only that user has posted.
db.ensure_user_chat_state(tg_user_id, tg_chat_id)

# Bad: Obvious comments
x = 5  # Set x to 5
url = normalize_url(url)  # Normalize the URL
```

### Docstring for Complex Algorithms
```python
def normalize_url(url: str) -> str:
    """Normalize a URL for dedup comparison.

    Normalization pipeline:
    1. Lowercase scheme + host
    2. Strip trailing slash from path (except root "/")
    3. Remove common tracking query params (utm_*, fbclid, gclid, etc.)
    4. Sort remaining query params for stable comparison
    5. Reconstruct URL

    Example:
        Input:  https://example.com:443/path/?utm_source=twitter&id=123
        Output: https://example.com/path?id=123
    """
```

---

## Security Practices

### Secrets & Credentials
```python
# Good: Load from env variables
BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

# Never:
# - Log secrets
# - Include in error messages
# - Commit to git
```

### Input Validation
```python
# Good: Type hints + defensive checks
async def webhook(request: Request, secret_token: str | None = Header(None)) -> dict:
    """Validate secret token before processing."""
    if config.WEBHOOK_SECRET_TOKEN and secret_token != config.WEBHOOK_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid secret token")
    # ...

# Good: Validate Telegram updates
if not config.BOT_TOKEN:
    logger.critical("TELEGRAM_BOT_TOKEN not set. Cannot start.")
    raise RuntimeError("TELEGRAM_BOT_TOKEN required")
```

### SQL Injection Prevention
```python
# Good: Use Supabase SDK (parameterized queries)
result = client.table("messages").upsert(row, on_conflict=...).execute()

# Never: String concatenation for SQL
# query = f"SELECT * FROM messages WHERE tg_user_id = {user_id}"  # VULNERABLE
```

---

## Dependencies Management

### pyproject.toml Standards
```toml
[project]
name = "telegram-link-summarizer-agent"
version = "0.1.0"
description = "An agentic Telegram bot to summarize links and papers."
requires-python = ">=3.12"

dependencies = [
    "baml-py>=0.88.0",
    "langgraph>=0.0.57",
    "langchain>=0.2.0",
    "python-telegram-bot[ext]>=21.0",
    "supabase>=2.0.0",
    "google-genai>=0.1.0",
    "fastapi>=0.115.12",
    "uvicorn>=0.34.2",
    # ... more dependencies
]
```

### Installation
```bash
# Development (editable mode with tools)
uv pip install -e ".[dev]"

# Production
uv pip install -e .

# Playwright browsers (required for extractors)
playwright install
```

---

## Deployment Checklist

**Before Commit:** Type hints + docstrings ✓ | No secrets in code ✓ | Logging errors ✓ | Tests pass ✓ | Conventions ✓ | No unused imports ✓

**Before Deploy:** `.env` NOT committed ✓ | Env vars documented ✓ | DB migration applied ✓ | Webhook secret strong ✓ | Prod token correct ✓ | Cloud Run perms OK ✓ | Monitoring configured ✓

