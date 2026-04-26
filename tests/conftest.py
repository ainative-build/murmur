"""Pytest configuration and fixtures for Murmur Bot tests."""

import pytest
import os
import sys
from unittest.mock import Mock, MagicMock, patch


# Configure test environment
@pytest.fixture(scope="session", autouse=True)
def setup_test_env():
    """Set up test environment variables."""
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_token_123")
    os.environ.setdefault("SUPABASE_URL", "http://localhost:54321")
    os.environ.setdefault("SUPABASE_KEY", "test_key_123")
    os.environ.setdefault("GEMINI_API_KEY", "test_gemini_key")
    os.environ.setdefault("USE_POLLING", "false")


@pytest.fixture
def mock_supabase_client():
    """Mock Supabase client for testing."""
    client = MagicMock()

    # Setup mock table methods
    mock_table = MagicMock()
    mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]
    client.table.return_value = mock_table

    return client


@pytest.fixture
def mock_telegram_user():
    """Mock Telegram User object."""
    user = Mock()
    user.id = 789
    user.username = "testuser"
    user.first_name = "Test"
    user.last_name = "User"
    user.is_bot = False
    return user


@pytest.fixture
def mock_telegram_message(mock_telegram_user):
    """Mock Telegram Message object."""
    from datetime import datetime, timezone

    message = Mock()
    message.message_id = 123
    message.from_user = mock_telegram_user
    message.chat_id = 456
    message.chat = Mock()
    message.chat.id = 456
    message.chat.type = "group"
    message.text = "Test message"
    message.date = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
    message.reply_to_message = None
    message.forward_origin = None
    message.reply_text = Mock()

    return message


@pytest.fixture
def mock_telegram_update(mock_telegram_message):
    """Mock Telegram Update object."""
    from telegram import Update

    update = Mock(spec=Update)
    update.effective_message = mock_telegram_message
    update.effective_user = mock_telegram_message.from_user
    update.message = mock_telegram_message

    return update


@pytest.fixture
def mock_telegram_context():
    """Mock Telegram ContextTypes object."""
    from telegram.ext import ContextTypes

    context = Mock(spec=ContextTypes.DEFAULT_TYPE)
    context.bot_data = {}
    context.user_data = {}
    context.chat_data = {}

    return context


@pytest.fixture(autouse=True)
def reset_db_client():
    """Reset db._client before each test to ensure clean state."""
    import db
    db._client = None
    yield
    db._client = None


@pytest.fixture(autouse=True)
def reset_provider_factory():
    """Reset provider factory singleton before each test to ensure clean state."""
    from src.providers.factory import _reset_for_tests
    _reset_for_tests()
    yield
    _reset_for_tests()


@pytest.fixture
def sample_urls():
    """Sample URLs for testing URL normalization."""
    return {
        "twitter": "https://twitter.com/user/status/123456",
        "youtube": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "linkedin": "https://linkedin.com/in/username",
        "pdf": "https://example.com/document.pdf",
        "webpage": "https://example.com/article",
        "with_tracking": "https://example.com?utm_source=google&fbclid=123&id=456",
        "with_trailing_slash": "https://example.com/page/",
    }


@pytest.fixture
def sample_messages():
    """Sample message payloads for testing."""
    from datetime import datetime, timezone

    return {
        "simple": {
            "tg_msg_id": 100,
            "tg_chat_id": 200,
            "tg_user_id": 300,
            "username": "user1",
            "text": "Hello world",
            "timestamp": datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc),
        },
        "with_link": {
            "tg_msg_id": 101,
            "tg_chat_id": 200,
            "tg_user_id": 300,
            "username": "user2",
            "text": "Check this: https://example.com",
            "timestamp": datetime(2024, 1, 15, 10, 31, 0, tzinfo=timezone.utc),
            "has_links": True,
        },
        "with_reply": {
            "tg_msg_id": 102,
            "tg_chat_id": 200,
            "tg_user_id": 400,
            "username": "user3",
            "text": "Good point!",
            "timestamp": datetime(2024, 1, 15, 10, 32, 0, tzinfo=timezone.utc),
            "reply_to_tg_msg_id": 100,
        },
    }


@pytest.fixture
def async_mock():
    """Helper to create AsyncMock (for older Python versions)."""
    from unittest.mock import AsyncMock
    return AsyncMock
