"""Unit tests for Phase 2-4 db.py extensions — Catchup, search, personal sources, draft, export."""

import pytest
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timezone, timedelta
import sys

# Mock Supabase before importing db
sys.modules['supabase'] = MagicMock()

import db


class TestGetUserChats:
    """Test get_user_chats — Phase 2."""

    def test_get_user_chats_success(self):
        """Returns list of chats user has been in."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value.data = [
            {"tg_chat_id": 123, "last_catchup_at": "2024-01-15T10:30:00"},
            {"tg_chat_id": 456, "last_catchup_at": None},
        ]

        with patch('db.get_client', return_value=mock_client):
            result = db.get_user_chats(789)

            assert len(result) == 2
            assert result[0]["tg_chat_id"] == 123

    def test_get_user_chats_empty(self):
        """Returns empty list if user in no chats."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value.data = None

        with patch('db.get_client', return_value=mock_client):
            result = db.get_user_chats(999)

            assert result == []

    def test_get_user_chats_error_handling(self):
        """Returns empty list on error."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.side_effect = Exception("DB error")

        with patch('db.get_client', return_value=mock_client):
            result = db.get_user_chats(789)

            assert result == []


class TestGetLastCatchup:
    """Test get_last_catchup — Phase 2."""

    def test_get_last_catchup_success(self):
        """Returns last catchup timestamp."""
        ts = "2024-01-15T10:30:00"
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute.return_value.data = {"last_catchup_at": ts}

        with patch('db.get_client', return_value=mock_client):
            result = db.get_last_catchup(123, 456)

            assert isinstance(result, datetime)
            assert result.year == 2024

    def test_get_last_catchup_none(self):
        """Returns None if never caught up."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute.return_value.data = {"last_catchup_at": None}

        with patch('db.get_client', return_value=mock_client):
            result = db.get_last_catchup(123, 456)

            assert result is None


class TestUpdateLastCatchup:
    """Test update_last_catchup — Phase 2."""

    def test_update_last_catchup_success(self):
        """Updates catchup timestamp."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            db.update_last_catchup(123, 456)

            mock_table.update.assert_called_once()
            update_call = mock_table.update.call_args[0][0]
            assert "last_catchup_at" in update_call

    def test_update_last_catchup_error_handling(self):
        """Handles update errors gracefully."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.side_effect = Exception("Update failed")

        with patch('db.get_client', return_value=mock_client):
            # Should not raise
            db.update_last_catchup(123, 456)


class TestGetMessagesSince:
    """Test get_messages_since — Phase 2."""

    def test_get_messages_since_with_timestamp(self):
        """Gets messages after a given timestamp."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.order.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.gt.return_value = mock_table
        mock_table.execute.return_value.data = [
            {"id": 1, "text": "newer message", "timestamp": "2024-01-15T11:00:00"},
        ]

        with patch('db.get_client', return_value=mock_client):
            since = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
            result = db.get_messages_since(456, since=since)

            assert len(result) == 1
            assert "newer" in result[0]["text"]
            mock_table.gt.assert_called_once()

    def test_get_messages_since_no_timestamp(self):
        """Gets last N messages if no timestamp provided."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.order.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value.data = [
            {"id": 1, "text": "message"},
        ]

        with patch('db.get_client', return_value=mock_client):
            result = db.get_messages_since(456, since=None, limit=50)

            assert len(result) == 1
            # gt() should not be called if no since
            assert not mock_table.gt.called


class TestGetLinkSummariesForMessages:
    """Test get_link_summaries_for_messages — Phase 2."""

    def test_get_link_summaries_success(self):
        """Gets link summaries for message IDs."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.in_.return_value = mock_table
        mock_table.execute.return_value.data = [
            {"message_id": 1, "url": "https://example.com", "title": "Example", "summary": "A site"},
        ]

        with patch('db.get_client', return_value=mock_client):
            result = db.get_link_summaries_for_messages([1, 2, 3])

            assert len(result) == 1
            assert result[0]["title"] == "Example"

    def test_get_link_summaries_empty_ids(self):
        """Returns empty list if no IDs provided."""
        result = db.get_link_summaries_for_messages([])
        assert result == []

    def test_get_link_summaries_error_handling(self):
        """Returns empty list on error."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.in_.return_value = mock_table
        mock_table.execute.side_effect = Exception("Query failed")

        with patch('db.get_client', return_value=mock_client):
            result = db.get_link_summaries_for_messages([1, 2])

            assert result == []


class TestSearchAll:
    """Test search_all full-text search — Phase 2."""

    def test_search_all_finds_messages(self):
        """Finds matching messages."""
        mock_client = Mock()

        # search_all calls client.table() 3 times (messages, links, personal)
        # Each returns different mock tables
        mock_msg_table = Mock()
        mock_link_table = Mock()
        mock_personal_table = Mock()

        # Setup chain for messages
        mock_msg_table.select.return_value = mock_msg_table
        mock_msg_table.text_search.return_value = mock_msg_table
        mock_msg_table.limit.return_value = mock_msg_table
        mock_msg_table.execute.return_value.data = [
            {"id": 1, "text": "react", "timestamp": "2024-01-15T10:30:00"},
        ]

        # Setup chain for links
        mock_link_table.select.return_value = mock_link_table
        mock_link_table.text_search.return_value = mock_link_table
        mock_link_table.limit.return_value = mock_link_table
        mock_link_table.execute.return_value.data = []

        # Setup chain for personal sources
        mock_personal_table.select.return_value = mock_personal_table
        mock_personal_table.eq.return_value = mock_personal_table
        mock_personal_table.text_search.return_value = mock_personal_table
        mock_personal_table.limit.return_value = mock_personal_table
        mock_personal_table.execute.return_value.data = []

        # Return different tables for each call to table()
        mock_client.table.side_effect = [mock_msg_table, mock_link_table, mock_personal_table]

        with patch('db.get_client', return_value=mock_client):
            result = db.search_all(789, "react")

            assert isinstance(result, list)
            # Should have at least the message
            assert len(result) > 0

    def test_search_all_privacy_boundary(self):
        """Personal sources filtered by user ID."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.text_search.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value.data = []

        with patch('db.get_client', return_value=mock_client):
            db.search_all(123, "test")

            # Verify eq was called with user ID for personal sources
            # (checking privacy boundary is enforced)
            calls = [str(call) for call in mock_table.eq.call_args_list]
            assert any("123" in str(call) for call in calls)


class TestPersonalSources:
    """Test personal sources CRUD — Phase 2."""

    def test_store_personal_source_success(self):
        """Stores personal source."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.execute.return_value.data = [{"id": 99}]

        with patch('db.get_client', return_value=mock_client):
            result = db.store_personal_source(
                tg_user_id=123,
                source_type="link",
                url="https://example.com",
                title="Example",
            )

            assert result == 99
            mock_table.insert.assert_called_once()

    def test_get_personal_sources_success(self):
        """Gets user's personal sources."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.order.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value.data = [
            {"id": 1, "source_type": "note", "content": "My note"},
        ]

        with patch('db.get_client', return_value=mock_client):
            result = db.get_personal_sources(123)

            assert len(result) == 1
            assert result[0]["source_type"] == "note"

    def test_get_personal_sources_count(self):
        """Gets count of user's personal sources."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value.count = 5

        with patch('db.get_client', return_value=mock_client):
            result = db.get_personal_sources_count(123)

            assert result == 5

    def test_delete_personal_source_ownership_check(self):
        """Delete includes ownership check."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.delete.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            result = db.delete_personal_source(tg_user_id=123, source_id=99)

            # Verify both id and tg_user_id checks
            assert mock_table.eq.call_count >= 2


class TestDraftSessions:
    """Test draft session management — Phase 3."""

    def test_create_draft_session(self):
        """Creates new draft session."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.execute.return_value.data = [{"id": 888}]

        with patch('db.get_client', return_value=mock_client):
            result = db.create_draft_session(
                tg_user_id=123,
                topic="Frontend",
                context_snapshot={"context_text": "..."},
            )

            assert result == 888

    def test_get_active_draft_session(self):
        """Gets active draft session."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.is_.return_value = mock_table
        mock_table.gt.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute.return_value.data = {
            "id": 888,
            "topic": "Frontend",
            "conversation_history": [],
        }

        with patch('db.get_client', return_value=mock_client):
            result = db.get_active_draft_session(123)

            assert result["id"] == 888
            assert result["topic"] == "Frontend"

    def test_get_active_draft_session_expired(self):
        """Returns None for expired sessions."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.is_.return_value = mock_table
        mock_table.gt.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute.side_effect = Exception("Not found")

        with patch('db.get_client', return_value=mock_client):
            result = db.get_active_draft_session(123)

            assert result is None

    def test_append_draft_message(self):
        """Appends message to conversation history."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute.side_effect = [
            Mock(data={"conversation_history": []}),
            Mock(),
        ]
        mock_table.update.return_value = mock_table

        with patch('db.get_client', return_value=mock_client):
            db.append_draft_message(888, "user", "Hello")

            mock_table.update.assert_called_once()
            update_call = mock_table.update.call_args[0][0]
            assert "conversation_history" in update_call

    def test_end_draft_session(self):
        """Marks draft session as ended."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value.data = [{"id": 888}]

        with patch('db.get_client', return_value=mock_client):
            db.end_draft_session(888)

            mock_table.update.assert_called_once()
            update_call = mock_table.update.call_args[0][0]
            assert "ended_at" in update_call

    def test_expire_stale_drafts(self):
        """Expires drafts inactive >24h."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.is_.return_value = mock_table
        mock_table.lt.return_value = mock_table
        mock_table.execute.return_value.data = [{"id": 1}, {"id": 2}]

        with patch('db.get_client', return_value=mock_client):
            result = db.expire_stale_drafts()

            assert result == 2


class TestReminders:
    """Test reminder functions — Phase 4."""

    def test_get_users_with_reminders_due(self):
        """Gets users with active reminders."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.neq.return_value = mock_table
        mock_table.execute.return_value.data = [
            {"tg_user_id": 123, "reminder_frequency": "daily"},
        ]

        with patch('db.get_client', return_value=mock_client):
            result = db.get_users_with_reminders_due()

            assert len(result) == 1
            assert result[0]["reminder_frequency"] == "daily"

    def test_update_user_reminder(self):
        """Updates user reminder frequency."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            db.update_user_reminder(123, "weekly")

            mock_table.update.assert_called_once()
            update_call = mock_table.update.call_args[0][0]
            assert update_call["reminder_frequency"] == "weekly"


class TestExport:
    """Test export functions — Phase 4."""

    def test_store_export(self):
        """Stores export record with dedup."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value = mock_table
        mock_table.execute.return_value.data = [{"id": 777}]

        with patch('db.get_client', return_value=mock_client):
            result = db.store_export(
                topic="Frontend Stack",
                export_target="notebooklm",
                content_hash="abc123",
            )

            assert result == 777
            # Verify upsert with on_conflict
            mock_table.upsert.assert_called_once()
            upsert_call = mock_table.upsert.call_args
            assert "on_conflict" in str(upsert_call)

    def test_export_exists(self):
        """Checks if export with hash exists."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value.data = [{"id": 1}]

        with patch('db.get_client', return_value=mock_client):
            result = db.export_exists("notebooklm", "hash123")

            assert result is True

    def test_export_not_exists(self):
        """Returns False if export not found."""
        mock_client = Mock()
        mock_table = Mock()
        mock_client.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value.data = None

        with patch('db.get_client', return_value=mock_client):
            result = db.export_exists("notebooklm", "hash123")

            assert result is False
