# Murmur Bot - Testing Guide

## Quick Start

```bash
make test-unit          # Fast — no DB, no docker. ~5s.
make test-db-up         # Bring up Postgres on :5433 + apply migrations.
make test-integration   # Run integration suite against real Postgres.
make test-all           # Both, in order.
make test-db-down       # Tear down test Postgres.
```

Run with coverage:
```bash
uv run python -m pytest tests/ --cov=. --cov-report=html
```

## Test Tiers

| Tier | Marker | Mocks | Real | Where | When |
|------|--------|-------|------|-------|------|
| Unit | (default) | Supabase, Telegram, all tools | nothing | `tests/test_*.py` | Always (PR + push) |
| Integration | `@pytest.mark.integration` | LLMs, extractors, Telegram outbound | Postgres, FastAPI app, PTB dispatch | `tests/integration/` | PR + push (with services) |

The `addopts` in `pytest.ini` deselects `-m integration` by default, so a bare `pytest tests/` runs unit only. Integration tests opt in via `make test-integration` or pytest's `-m integration` flag.

View coverage report:
```bash
open htmlcov/index.html
```

## Test Structure

```
tests/
├── __init__.py              # Test package
├── conftest.py              # Shared fixtures & config
├── test_url_normalize.py    # URL dedup normalization (33 tests)
├── test_db.py               # Supabase wrapper (23 tests)
├── test_commands.py         # Telegram handlers (12 tests)
├── test_bot.py              # Message handlers & link detection (29 tests)
└── test_config.py           # Environment config (27 tests)
```

## Running Specific Tests

```bash
# Single test module
uv run python -m pytest tests/test_url_normalize.py -v

# Single test class
uv run python -m pytest tests/test_db.py::TestStoreMessage -v

# Single test function
uv run python -m pytest tests/test_url_normalize.py::TestBasicNormalization::test_lowercase_scheme -v

# Async tests only
uv run python -m pytest tests/ -m asyncio -v

# Tests matching a pattern
uv run python -m pytest tests/ -k "link" -v
```

## Coverage Targets

**Phase 1 Modules (100% target):**
- `config.py` — 100% ✓
- `db.py` — 100% ✓
- `commands.py` — 100% ✓
- `url_normalize.py` — 88% (error path not fully testable)
- `bot.py` handlers — 100% ✓

**Excluded from Phase 1:**
- `agent.py` — Phase 2+ (langgraph)
- `tools/*` — Phase 2+ (link extraction)
- FastAPI lifespan/webhook — Integration tests Phase 2

## Key Testing Patterns

### Mocking Supabase
```python
from unittest.mock import Mock, patch

with patch('db.get_client') as mock_client:
    mock_table = Mock()
    mock_client.return_value.table.return_value = mock_table
    mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]
    # ... test code
```

### Mocking Telegram Updates
```python
from unittest.mock import Mock, AsyncMock

mock_message = Mock()
mock_message.from_user = Mock(id=789, username="testuser")
mock_message.text = "Test message"
mock_message.reply_text = AsyncMock()

mock_update = Mock()
mock_update.effective_message = mock_message
```

### Testing Async Handlers
```python
import pytest

@pytest.mark.asyncio
async def test_handler():
    mock_update = Mock()
    mock_context = Mock()
    
    await start_handler(mock_update, mock_context)
    
    # assertions
```

## Common Test Issues

### "Cannot spec a Mock object" Error
- Don't use `Mock(spec=SomeClass)` when the class is already mocked
- Use `Mock()` without spec

### Async Test Not Running
- Add `@pytest.mark.asyncio` decorator
- Use `AsyncMock()` for async methods
- Install: `uv add --dev pytest-asyncio`

### Import Errors
- Ensure `.venv/bin/python3` is being used by `uv`
- Run: `uv run python -c "import db"` to verify imports

## Test Fixtures (conftest.py)

Available fixtures for use in tests:

| Fixture | Purpose |
|---------|---------|
| `mock_supabase_client` | Pre-configured Supabase mock |
| `mock_telegram_user` | Telegram User mock |
| `mock_telegram_message` | Telegram Message mock |
| `mock_telegram_update` | Telegram Update mock |
| `mock_telegram_context` | Telegram Context mock |
| `sample_urls` | Dict of URL test cases |
| `sample_messages` | Dict of message payloads |
| `async_mock` | AsyncMock helper |
| `setup_test_env` | Environment setup |
| `reset_db_client` | DB client cleanup (auto) |

## Performance

- Total execution: ~1.4 seconds
- Average per test: ~11ms
- No slow tests (all <50ms)

## Coverage Report Location

- Terminal: `pytest --cov=. --cov-report=term-missing`
- HTML: `htmlcov/index.html` (open in browser)
- JSON: `coverage.json` (for CI/CD integration)

## Integration Tests

Integration tests drive the bot through synthetic Telegram webhook payloads
against a real Postgres + the FastAPI app + PTB dispatch. External services
(LLMs, extractors, Telegram outbound) are mocked at the import boundary.

### Layout
```
tests/integration/
  conftest.py             # fixtures: test_db, tg_client, recording_bot, mock_llms, mock_extractors
  recording_bot.py        # Bot subclass that records calls, never hits the network
  factories.py            # synthetic Telegram update payload builders
  llm_fixtures.py         # canned BAML / Gemini responses
  extractor_fixtures.py   # canned Tavily / TinyFish / AgentQL / etc. content
  supabase_shim.py        # psycopg-backed shim for the supabase-py client surface used in db.py
  test_smoke.py           # Phase 1 smoke — health, webhook auth, real-HTTP backstop, RecordingBot
  # phase 2+ tests added incrementally
```

### Key fixtures

| Fixture | Scope | Purpose |
|---------|-------|---------|
| `test_db_dsn` | session | DSN for test Postgres |
| `test_db` | function | psycopg connection that truncates user tables before each test |
| `recording_bot` | function | fresh `RecordingBot` instance |
| `bot_app` | function | FastAPI app with PTB wired to `recording_bot` |
| `tg_client` | function | TestClient + `post_update(payload)` helper that sets the secret header |
| `dispatcher` | function | direct `process_update` bypass of HTTP layer (faster) |
| `mock_llms` | function | `LLMMockConfig` — set `.summary`, `.route`, `.catchup`, etc. per-test |
| `mock_extractors` | function | `ExtractorMockConfig` — set `.tavily_results`, `.tinyfish_content`, etc. per-test |
| `disable_real_http` | autouse | raises if any test attempts a real `httpx` call |

### Test fixtures matrix

Every test pins down its inputs (URL / file / voice / image) by stable fixture
ID. See [plans/260425-2118-integration-test-infrastructure/test-fixtures-matrix.md](plans/260425-2118-integration-test-infrastructure/test-fixtures-matrix.md)
for the full catalog (link types, file formats, voice variants, image variants,
DM seeded state, mocked LLM responses).

### Local prerequisites
- Docker Desktop running
- Port 5433 free (override with `MURMUR_TEST_DB_PORT`)
- `uv sync` to install `psycopg[binary]`

### Plan
- See [plans/260425-2118-integration-test-infrastructure/plan.md](plans/260425-2118-integration-test-infrastructure/plan.md) for the
  full integration-test rollout: Phase 1 (this — infra), Phase 2 (group flows),
  Phase 3 (DM flows), Phase 4 (dedup + cross-cutting), Phase 5 (CI).

---

**Test Suite:** Phase 1 Foundation  
**Created:** 2026-04-19  
**Status:** All 124 tests passing ✓
