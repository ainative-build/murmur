"""Unit tests for export_formatter.py — Topic document formatting."""

import pytest
from datetime import datetime, timezone, timedelta

import export_formatter


class TestFormatTopicDocument:
    """Test markdown document formatting for topics."""

    def test_format_topic_document_basic(self):
        """Formats basic topic document with title."""
        doc = export_formatter.format_topic_document(
            topic="Frontend Framework",
            messages=[],
            links=[],
        )

        assert "# Topic: Frontend Framework" in doc
        assert "## Discussion Timeline" in doc

    def test_format_topic_document_with_summary(self):
        """Includes topic summary in output."""
        summary = "Team debated React vs Vue with focus on performance"
        doc = export_formatter.format_topic_document(
            topic="Frameworks",
            messages=[],
            links=[],
            summary=summary,
        )

        assert "## Summary" in doc
        assert summary in doc

    def test_format_topic_document_includes_messages(self):
        """Formats discussion timeline with messages."""
        messages = [
            {
                "username": "alice",
                "text": "React is faster",
                "timestamp": "2024-01-15T10:30:00",
                "tg_user_id": 123,
            },
            {
                "username": "bob",
                "text": "Vue is simpler",
                "timestamp": "2024-01-15T10:31:00",
                "tg_user_id": 456,
            },
        ]

        doc = export_formatter.format_topic_document(
            topic="Frameworks",
            messages=messages,
            links=[],
        )

        assert "alice" in doc
        assert "React is faster" in doc
        assert "bob" in doc
        assert "Vue is simpler" in doc

    def test_format_topic_document_includes_links(self):
        """Formats key links section."""
        links = [
            {
                "url": "https://example.com/react",
                "title": "React Performance Guide",
                "summary": "Best practices for React optimization",
            },
            {
                "url": "https://example.com/vue",
                "title": None,  # Should fallback to URL
                "summary": "Vue framework docs",
            },
        ]

        doc = export_formatter.format_topic_document(
            topic="Frameworks",
            messages=[],
            links=links,
        )

        assert "## Key Links" in doc
        assert "React Performance Guide" in doc
        assert "https://example.com/react" in doc
        assert "Vue framework docs" in doc

    def test_format_topic_document_status_active(self):
        """Marks topic as active if recent messages."""
        now = datetime.now(timezone.utc)
        messages = [
            {
                "username": "alice",
                "text": "test",
                "timestamp": now.isoformat(),
                "tg_user_id": 123,
            }
        ]

        doc = export_formatter.format_topic_document(
            topic="Recent Topic",
            messages=messages,
            links=[],
        )

        assert "## Status: Active" in doc

    def test_format_topic_document_status_stale(self):
        """Marks topic as stale if no recent messages."""
        stale_time = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
        messages = [
            {
                "username": "alice",
                "text": "old message",
                "timestamp": stale_time,
                "tg_user_id": 123,
            }
        ]

        doc = export_formatter.format_topic_document(
            topic="Old Topic",
            messages=messages,
            links=[],
        )

        assert "## Status: Stale" in doc

    def test_format_topic_document_no_messages_unknown_status(self):
        """Status is unknown if no messages."""
        doc = export_formatter.format_topic_document(
            topic="Empty Topic",
            messages=[],
            links=[],
        )

        assert "## Status: Unknown" in doc

    def test_format_topic_document_handles_missing_username(self):
        """Falls back to user ID if no username."""
        messages = [
            {
                "username": None,
                "text": "Anonymous message",
                "timestamp": "2024-01-15T10:30:00",
                "tg_user_id": 789,
            }
        ]

        doc = export_formatter.format_topic_document(
            topic="Anonymous",
            messages=messages,
            links=[],
        )

        assert "user_789" in doc or "789" in doc

    def test_format_topic_document_handles_missing_timestamp(self):
        """Handles missing timestamp gracefully."""
        messages = [
            {
                "username": "alice",
                "text": "message",
                "timestamp": None,
                "tg_user_id": 123,
            }
        ]

        doc = export_formatter.format_topic_document(
            topic="Test",
            messages=messages,
            links=[],
        )

        assert "alice" in doc
        assert "message" in doc

    def test_format_topic_document_link_summary_truncated(self):
        """Link summary is truncated to 200 chars."""
        long_summary = "A" * 500
        links = [
            {
                "url": "https://example.com",
                "title": "Test",
                "summary": long_summary,
            }
        ]

        doc = export_formatter.format_topic_document(
            topic="Test",
            messages=[],
            links=links,
        )

        # Should contain truncated version
        assert "AAA" in doc
        assert long_summary not in doc  # Full text should not be there

    def test_format_topic_document_empty_lists(self):
        """Handles empty messages and links gracefully."""
        doc = export_formatter.format_topic_document(
            topic="Empty",
            messages=[],
            links=[],
            summary="",
        )

        assert "# Topic: Empty" in doc
        assert "## Discussion Timeline" in doc
        assert "## Status:" in doc


class TestContentHash:
    """Test content hashing for dedup."""

    def test_content_hash_consistent(self):
        """Same content produces same hash."""
        content = "Test document content for hashing"
        hash1 = export_formatter.content_hash(content)
        hash2 = export_formatter.content_hash(content)

        assert hash1 == hash2

    def test_content_hash_different_content(self):
        """Different content produces different hashes."""
        hash1 = export_formatter.content_hash("Content A")
        hash2 = export_formatter.content_hash("Content B")

        assert hash1 != hash2

    def test_content_hash_is_hex_string(self):
        """Hash is a valid hex string (SHA256 = 64 chars)."""
        content = "Test content"
        hash_val = export_formatter.content_hash(content)

        assert isinstance(hash_val, str)
        assert len(hash_val) == 64  # SHA256 hex = 64 characters
        # Verify it's hex
        try:
            int(hash_val, 16)
        except ValueError:
            pytest.fail(f"Hash is not valid hex: {hash_val}")

    def test_content_hash_whitespace_matters(self):
        """Whitespace differences produce different hashes."""
        hash1 = export_formatter.content_hash("Content")
        hash2 = export_formatter.content_hash("Content\n")
        hash3 = export_formatter.content_hash("Content ")

        assert hash1 != hash2
        assert hash1 != hash3

    def test_content_hash_case_sensitive(self):
        """Content hash is case-sensitive."""
        hash1 = export_formatter.content_hash("Content")
        hash2 = export_formatter.content_hash("content")

        assert hash1 != hash2

    def test_content_hash_unicode(self):
        """Handles unicode content."""
        content = "测试内容 🚀 café"
        hash_val = export_formatter.content_hash(content)

        assert len(hash_val) == 64

    def test_content_hash_empty_string(self):
        """Can hash empty string."""
        hash_val = export_formatter.content_hash("")
        assert len(hash_val) == 64

    def test_content_hash_large_content(self):
        """Can hash large content."""
        large_content = "A" * 10000
        hash_val = export_formatter.content_hash(large_content)
        assert len(hash_val) == 64
