"""Integration-test fixtures.

Provides:
- `test_db_dsn` (session) — DSN for the test Postgres (must be running)
- `test_db` (function) — connection that truncates tables between tests
- `recording_bot` (function) — fresh `RecordingBot` per test
- `bot_app` (function) — FastAPI app with PTB dispatching to recording_bot
- `tg_client` (function) — TestClient with helper to POST webhook payloads
- `dispatcher` (function) — direct `process_update` bypass of HTTP layer
- `mock_llms` (function) — LLMMockConfig for per-test override
- `mock_extractors` (function) — ExtractorMockConfig for per-test override
- `disable_real_http` (autouse) — fail any real HTTP attempt
"""

import os
import sys
from pathlib import Path
from typing import Iterator

# IMPORTANT: This must run BEFORE any `import config` (transitively via `bot`,
# `db`, etc.). `config.py` does `load_dotenv(override=True)` at import time,
# which would otherwise overwrite env vars we set in fixtures. We set them at
# module load and short-circuit dotenv by pointing it at /dev/null.
GROUP_CHAT_ID = -1001234567890
DM_USER_ID = 555_111_222
SECOND_USER_ID = 555_111_223
WEBHOOK_PATH = "test-webhook"
WEBHOOK_SECRET = "test-secret-token-fixture"

os.environ["TELEGRAM_BOT_TOKEN"] = "test:token"
os.environ["WEBHOOK_SECRET_PATH"] = WEBHOOK_PATH
os.environ["TELEGRAM_WEBHOOK_SECRET_TOKEN"] = WEBHOOK_SECRET
os.environ["WEBHOOK_URL"] = ""  # disables webhook setup in lifespan
os.environ["USE_POLLING"] = "false"
os.environ["GEMINI_API_KEY"] = "test-key"
os.environ["SUPABASE_URL"] = "http://localhost:54321"
os.environ["SUPABASE_KEY"] = "test-supabase-key"
os.environ["TINYFISH_API_KEY"] = "test-tinyfish-key"

# Force load_dotenv inside config to be a no-op even though it's called with
# override=True. We point it at a non-existent path so it doesn't overwrite
# our test env vars from the real .env file.
os.environ["DOTENV_PATH"] = "/nonexistent"

import psycopg  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from telegram import Update  # noqa: E402

# Repo root on sys.path so `bot`, `db`, etc. import directly.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Patch dotenv.load_dotenv BEFORE config is imported, so its `override=True`
# doesn't clobber the env vars we just set above.
import dotenv as _dotenv  # noqa: E402

_dotenv.load_dotenv = lambda *a, **kw: True

from tests.integration.recording_bot import RecordingBot  # noqa: E402
from tests.integration.llm_fixtures import LLMMockConfig, install_llm_mocks  # noqa: E402
from tests.integration.extractor_fixtures import ExtractorMockConfig, install_extractor_mocks  # noqa: E402


# --------------------------------------------------------------------------
# Session-scoped: DB DSN
# --------------------------------------------------------------------------


@pytest.fixture(scope="session")
def test_db_dsn() -> str:
    """DSN for the integration test Postgres.

    Defaults to the docker-compose service. Override with MURMUR_TEST_DB_DSN.
    """
    return os.environ.get(
        "MURMUR_TEST_DB_DSN",
        "postgresql://murmur:murmur@localhost:5433/murmur_test",
    )


# --------------------------------------------------------------------------
# Session-scoped: configure the production `db` module to use the test DSN
# --------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _configure_test_environment(test_db_dsn: str):
    """Install the psycopg-backed Supabase shim. (Env vars set at module load.)"""
    from tests.integration.supabase_shim import install_psycopg_shim
    install_psycopg_shim(test_db_dsn)
    yield


# --------------------------------------------------------------------------
# Function-scoped: clean DB between tests
# --------------------------------------------------------------------------


@pytest.fixture
def test_db(test_db_dsn: str) -> Iterator[psycopg.Connection]:
    """Truncate user tables before each test, yield a psycopg connection."""
    conn = psycopg.connect(test_db_dsn, autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute("""
                TRUNCATE TABLE
                    feedback,
                    scheduled_deletions,
                    exports,
                    draft_sessions,
                    personal_sources,
                    link_summaries,
                    messages,
                    user_chat_state,
                    users
                RESTART IDENTITY CASCADE;
            """)
        yield conn
    finally:
        conn.close()


# --------------------------------------------------------------------------
# Function-scoped: recording bot
# --------------------------------------------------------------------------


@pytest.fixture
def recording_bot() -> RecordingBot:
    return RecordingBot()


# --------------------------------------------------------------------------
# Function-scoped: FastAPI app with PTB wired to recording_bot
# --------------------------------------------------------------------------


@pytest.fixture
def bot_app(recording_bot: RecordingBot, test_db):
    """Build the FastAPI app with PTB dispatched through `recording_bot`."""
    # Reset bot's in-memory dedup set between tests.
    import bot as bot_module
    bot_module._processing_messages.clear()
    from commands import _processing_dm
    _processing_dm.clear()

    # Build a PTB Application bound to our RecordingBot
    ptb_app = bot_module._build_ptb_app(bot=recording_bot)

    # Inject so lifespan reuses ours
    bot_module.app.state.ptb_app = ptb_app

    return bot_module.app


@pytest.fixture
def tg_client(bot_app, recording_bot: RecordingBot):
    """TestClient + helper to POST update payloads to the webhook."""

    class _Client:
        def __init__(self, app, webhook_path: str, secret: str):
            self._client = TestClient(app)
            self._webhook_path = webhook_path
            self._secret = secret

        def post_update(self, payload: dict, *, secret: str | None = None):
            return self._client.post(
                f"/{self._webhook_path}",
                json=payload,
                headers={"X-Telegram-Bot-Api-Secret-Token": secret or self._secret},
            )

        def __enter__(self):
            self._client.__enter__()
            return self

        def __exit__(self, *exc):
            self._client.__exit__(*exc)

    with _Client(bot_app, WEBHOOK_PATH, WEBHOOK_SECRET) as c:
        yield c


@pytest.fixture
def dispatcher(bot_app, recording_bot: RecordingBot):
    """Direct dispatch helper — bypasses HTTP, calls `process_update` directly.

    Use for tests that don't need the webhook layer (most handler-level tests).
    The TestClient lifespan would also work but adds startup cost; this fixture
    is faster.
    """
    import bot as bot_module
    ptb_app = bot_module.app.state.ptb_app

    async def _dispatch(payload: dict):
        update = Update.de_json(payload, recording_bot)
        await ptb_app.process_update(update)

    # Initialize once for the test
    import asyncio

    async def _init():
        if not ptb_app.initialized:
            await ptb_app.initialize()
            await ptb_app.start()

    asyncio.get_event_loop().run_until_complete(_init())

    return _dispatch


# --------------------------------------------------------------------------
# Function-scoped: LLM and extractor mocks
# --------------------------------------------------------------------------


@pytest.fixture
def mock_llms() -> Iterator[LLMMockConfig]:
    config = LLMMockConfig()
    patches = install_llm_mocks(config)
    try:
        yield config
    finally:
        for p in patches:
            p.stop()


@pytest.fixture
def mock_extractors() -> Iterator[ExtractorMockConfig]:
    config = ExtractorMockConfig()
    patches = install_extractor_mocks(config)
    try:
        yield config
    finally:
        for p in patches:
            p.stop()


# --------------------------------------------------------------------------
# Autouse: fail real HTTP attempts
# --------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def disable_real_http(monkeypatch):
    """Backstop: any test that makes a real HTTP call should fail loudly."""
    import httpx

    async def _no_async_send(self, request, **kwargs):
        raise RuntimeError(
            f"Real HTTP attempted in test: {request.method} {request.url}. "
            "Mock the extractor/LLM at its boundary."
        )

    monkeypatch.setattr(httpx.AsyncClient, "send", _no_async_send)
