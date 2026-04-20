"""Unit tests for db.py — Supabase client wrapper with mocked Supabase."""

import pytest
from unittest.mock import Mock, MagicMock, patch, call
from datetime import datetime, timezone
import sys

# Mock Supabase before importing db module
sys.modules['supabase'] = MagicMock()

import db
from url_normalize import normalize_url


class TestGetClient:
    """Test singleton Supabase client initialization."""

    def setup_method(self):
        """Reset the global _client before each test."""
        db._client = None

    def test_client_created_on_first_call(self):
        """Client should be created on first get_client() call."""
        with patch('db.create_client') as mock_create:
            mock_client = Mock()
            mock_create.return_value = mock_client

            with patch.dict('db.config.__dict__', {'SUPABASE_URL': 'http://test', 'SUPABASE_KEY': 'key'}):
                client1 = db.get_client()
                assert client1 == mock_client
                mock_create.assert_called_once_with('http://test', 'key')

    def test_client_singleton_reused(self):
        """Subsequent calls should return same client instance."""
        with patch('db.create_client') as mock_create:
            mock_client = Mock()
            mock_create.return_value = mock_client

            with patch.dict('db.config.__dict__', {'SUPABASE_URL': 'http://test', 'SUPABASE_KEY': 'key'}):
                client1 = db.get_client()
                client2 = db.get_client()
                assert client1 is client2
                # Should only call create_client once
                mock_create.assert_called_once()

    def test_raises_error_if_url_missing(self):
        """Should raise RuntimeError if SUPABASE_URL not set."""
        with patch.dict('db.config.__dict__', {'SUPABASE_URL': '', 'SUPABASE_KEY': 'key'}):
            with pytest.raises(RuntimeError, match="SUPABASE_URL and SUPABASE_KEY must be set"):
                db.get_client()

    def test_raises_error_if_key_missing(self):
        """Should raise RuntimeError if SUPABASE_KEY not set."""
        with patch.dict('db.config.__dict__', {'SUPABASE_URL': 'http://test', 'SUPABASE_KEY': ''}):
            with pytest.raises(RuntimeError, match="SUPABASE_URL and SUPABASE_KEY must be set"):
                db.get_client()


class TestStoreMessage:
    """Test store_message function with mocked Supabase."""

    def setup_method(self):
        """Reset client and set up mock for each test."""
        db._client = None

    def test_store_message_success(self):
        """Successfully store a message."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 42}]

        with patch('db.get_client', return_value=mock_client):
            timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
            result = db.store_message(
                tg_msg_id=123,
                tg_chat_id=456,
                tg_user_id=789,
                username="testuser",
                text="Hello world",
                timestamp=timestamp,
                has_links=False
            )

            assert result == 42
            mock_client.table.assert_called_once_with("messages")
            mock_table.upsert.assert_called_once()

    def test_store_message_with_all_fields(self):
        """Store message with all optional fields set."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 100}]

        with patch('db.get_client', return_value=mock_client):
            timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
            result = db.store_message(
                tg_msg_id=123,
                tg_chat_id=456,
                tg_user_id=789,
                username="testuser",
                text="Check this out: https://example.com",
                timestamp=timestamp,
                has_links=True,
                reply_to_tg_msg_id=111,
                forwarded_from="otheruser"
            )

            assert result == 100
            call_args = mock_table.upsert.call_args
            row = call_args[0][0]
            assert row["tg_msg_id"] == 123
            assert row["tg_chat_id"] == 456
            assert row["tg_user_id"] == 789
            assert row["username"] == "testuser"
            assert row["text"] == "Check this out: https://example.com"
            assert row["has_links"] is True
            assert row["reply_to_tg_msg_id"] == 111
            assert row["forwarded_from"] == "otheruser"

    def test_store_message_idempotent_duplicate_returns_none(self):
        """Duplicate message (same tg_chat_id, tg_msg_id) returns None."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        # Empty result means duplicate was ignored
        mock_table.upsert.return_value.execute.return_value.data = []

        with patch('db.get_client', return_value=mock_client):
            timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
            result = db.store_message(
                tg_msg_id=123,
                tg_chat_id=456,
                tg_user_id=789,
                username="testuser",
                text="Hello",
                timestamp=timestamp
            )

            assert result is None

    def test_store_message_uses_correct_conflict_resolution(self):
        """Should use tg_chat_id,tg_msg_id as unique constraint."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
            db.store_message(
                tg_msg_id=123,
                tg_chat_id=456,
                tg_user_id=789,
                username="testuser",
                text="Hello",
                timestamp=timestamp
            )

            call_kwargs = mock_table.upsert.call_args[1]
            assert call_kwargs["on_conflict"] == "tg_chat_id,tg_msg_id"
            assert call_kwargs["ignore_duplicates"] is True

    def test_store_message_handles_exception(self):
        """Should return None on exception and log error."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.side_effect = Exception("DB error")

        with patch('db.get_client', return_value=mock_client):
            with patch('db.logger') as mock_logger:
                timestamp = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
                result = db.store_message(
                    tg_msg_id=123,
                    tg_chat_id=456,
                    tg_user_id=789,
                    username="testuser",
                    text="Hello",
                    timestamp=timestamp
                )

                assert result is None
                mock_logger.error.assert_called()

    def test_store_message_timestamp_iso_format(self):
        """Timestamp should be converted to ISO format."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            timestamp = datetime(2024, 1, 15, 10, 30, 45, 123456, tzinfo=timezone.utc)
            db.store_message(
                tg_msg_id=123,
                tg_chat_id=456,
                tg_user_id=789,
                username="testuser",
                text="Hello",
                timestamp=timestamp
            )

            row = mock_table.upsert.call_args[0][0]
            assert row["timestamp"] == "2024-01-15T10:30:45.123456+00:00"


class TestStoreLinkSummary:
    """Test store_link_summary function."""

    def setup_method(self):
        """Reset client before each test."""
        db._client = None

    def test_store_link_summary_success(self):
        """Successfully store a link summary."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 50}]

        with patch('db.get_client', return_value=mock_client):
            result = db.store_link_summary(
                message_id=42,
                url="https://example.com/article",
                link_type="webpage",
                title="Example Article",
                summary="This is a test summary"
            )

            assert result == 50
            mock_client.table.assert_called_once_with("link_summaries")

    def test_store_link_summary_normalizes_url(self):
        """URL should be normalized for dedup key."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            url = "HTTPS://EXAMPLE.COM/page?utm_source=twitter/"
            db.store_link_summary(
                message_id=42,
                url=url,
                link_type="webpage"
            )

            row = mock_table.upsert.call_args[0][0]
            expected_normalized = normalize_url(url)
            assert row["url_normalized"] == expected_normalized
            assert row["url"] == url  # Original URL preserved

    def test_store_link_summary_with_all_fields(self):
        """Store link summary with all optional fields."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            db.store_link_summary(
                message_id=42,
                url="https://youtube.com/watch?v=ABC123",
                link_type="youtube",
                title="Amazing Video",
                extracted_content="Video transcript here...",
                summary="A summary of the video"
            )

            row = mock_table.upsert.call_args[0][0]
            assert row["message_id"] == 42
            assert row["url"] == "https://youtube.com/watch?v=ABC123"
            assert row["link_type"] == "youtube"
            assert row["title"] == "Amazing Video"
            assert row["extracted_content"] == "Video transcript here..."
            assert row["summary"] == "A summary of the video"

    def test_store_link_summary_idempotent_on_duplicate(self):
        """Duplicate (message_id, url_normalized) should return None."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = []

        with patch('db.get_client', return_value=mock_client):
            result = db.store_link_summary(
                message_id=42,
                url="https://example.com/page",
                link_type="webpage"
            )

            assert result is None

    def test_store_link_summary_uses_correct_conflict_resolution(self):
        """Should use message_id,url_normalized as unique constraint."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            db.store_link_summary(
                message_id=42,
                url="https://example.com/page"
            )

            call_kwargs = mock_table.upsert.call_args[1]
            assert call_kwargs["on_conflict"] == "message_id,url_normalized"
            assert call_kwargs["ignore_duplicates"] is True

    def test_store_link_summary_handles_exception(self):
        """Should return None on exception and log error."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.side_effect = Exception("DB error")

        with patch('db.get_client', return_value=mock_client):
            with patch('db.logger') as mock_logger:
                result = db.store_link_summary(
                    message_id=42,
                    url="https://example.com"
                )

                assert result is None
                mock_logger.error.assert_called()


class TestUpsertUser:
    """Test upsert_user function."""

    def setup_method(self):
        """Reset client before each test."""
        db._client = None

    def test_upsert_user_success(self):
        """Successfully upsert a user."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            db.upsert_user(tg_user_id=789, username="testuser")

            mock_client.table.assert_called_once_with("users")
            call_args = mock_table.upsert.call_args
            row = call_args[0][0]
            assert row["tg_user_id"] == 789
            assert row["username"] == "testuser"

    def test_upsert_user_without_username(self):
        """Upsert user without username (None)."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            db.upsert_user(tg_user_id=789, username=None)

            row = mock_table.upsert.call_args[0][0]
            assert row["tg_user_id"] == 789
            assert row["username"] is None

    def test_upsert_user_uses_correct_conflict_resolution(self):
        """Should use tg_user_id as unique constraint."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            db.upsert_user(tg_user_id=789, username="newname")

            call_kwargs = mock_table.upsert.call_args[1]
            assert call_kwargs["on_conflict"] == "tg_user_id"

    def test_upsert_user_handles_exception(self):
        """Should log error on exception (doesn't raise)."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.side_effect = Exception("DB error")

        with patch('db.get_client', return_value=mock_client):
            with patch('db.logger') as mock_logger:
                # Should not raise
                db.upsert_user(tg_user_id=789)
                mock_logger.error.assert_called()


class TestEnsureUserChatState:
    """Test ensure_user_chat_state function."""

    def setup_method(self):
        """Reset client before each test."""
        db._client = None

    def test_ensure_user_chat_state_success(self):
        """Successfully ensure user_chat_state row exists."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            db.ensure_user_chat_state(tg_user_id=789, tg_chat_id=456)

            mock_client.table.assert_called_once_with("user_chat_state")
            call_args = mock_table.upsert.call_args
            row = call_args[0][0]
            assert row["tg_user_id"] == 789
            assert row["tg_chat_id"] == 456

    def test_ensure_user_chat_state_uses_correct_conflict_resolution(self):
        """Should use (tg_user_id, tg_chat_id) as unique constraint."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            db.ensure_user_chat_state(tg_user_id=789, tg_chat_id=456)

            call_kwargs = mock_table.upsert.call_args[1]
            assert call_kwargs["on_conflict"] == "tg_user_id,tg_chat_id"
            assert call_kwargs["ignore_duplicates"] is True

    def test_ensure_user_chat_state_handles_exception(self):
        """Should log error on exception (doesn't raise)."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value.execute.side_effect = Exception("DB error")

        with patch('db.get_client', return_value=mock_client):
            with patch('db.logger') as mock_logger:
                # Should not raise
                db.ensure_user_chat_state(tg_user_id=789, tg_chat_id=456)
                mock_logger.error.assert_called()
