# Murmur Bot - Testing Guide

## Quick Start

Run all tests:
```bash
uv run python -m pytest tests/ -v
```

Run with coverage:
```bash
uv run python -m pytest tests/ --cov=. --cov-report=html
```

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

## Next Phase Testing

### Phase 2 (Catchup & Search)
- Integration tests with `TestClient`
- Webhook endpoint tests
- Database query tests
- Agent (langgraph) tests

### Phase 3+ (Export, Topics, Decision)
- New handler function tests
- Complex query scenario tests
- Performance benchmarks

---

**Test Suite:** Phase 1 Foundation  
**Created:** 2026-04-19  
**Status:** All 124 tests passing ✓
