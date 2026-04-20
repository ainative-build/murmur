"""Unit tests for personal.py — DM link/note/forward handling."""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime, timezone

import personal


class TestDetectUrls:
    """Test URL extraction from text."""

    def test_detect_single_url(self):
        """Extract a single URL from text."""
        text = "Check this: https://example.com/article"
        urls = personal.detect_urls(text)
        assert len(urls) == 1
        assert "https://example.com/article" in urls[0]

    def test_detect_multiple_urls(self):
        """Extract multiple URLs from text."""
        text = "See https://example.com and https://other.com"
        urls = personal.detect_urls(text)
        assert len(urls) == 2

    def test_detect_http_and_https(self):
        """Detect both http and https URLs."""
        text = "http://old.com and https://new.com"
        urls = personal.detect_urls(text)
        assert len(urls) == 2

    def test_detect_url_with_query_params(self):
        """Detect URLs with query parameters."""
        text = "Check https://example.com/path?key=value&foo=bar"
        urls = personal.detect_urls(text)
        assert len(urls) == 1
        assert "key=value" in urls[0]

    def test_detect_url_stops_at_whitespace(self):
        """URL detection stops at whitespace."""
        text = "https://example.com/article next text"
        urls = personal.detect_urls(text)
        assert len(urls) == 1
        assert urls[0].endswith("article")

    def test_no_urls_in_text(self):
        """Returns empty list if no URLs found."""
        text = "Just a regular message with no links"
        urls = personal.detect_urls(text)
        assert urls == []

    def test_url_at_end_of_text(self):
        """Detect URL at end of text."""
        text = "Final link: https://example.com"
        urls = personal.detect_urls(text)
        assert len(urls) == 1


class TestHandleDmLink:
    """Test DM link processing."""

    @pytest.mark.asyncio
    async def test_handle_dm_link_success(self):
        """Successfully process a DM link through agent pipeline."""
        mock_agent_result = "# Example Article\n\nSummary of the article content"

        with patch('personal.run_agent', new_callable=AsyncMock, return_value=mock_agent_result):
            with patch('personal.db.store_personal_source') as mock_store:
                mock_store.return_value = 42

                result = await personal.handle_dm_link(
                    tg_user_id=123,
                    url="https://example.com/article",
                    original_text="Check this link https://example.com/article"
                )

                assert result == 42
                mock_store.assert_called_once()
                call_kwargs = mock_store.call_args[1]
                assert call_kwargs["tg_user_id"] == 123
                assert call_kwargs["source_type"] == "link"
                assert call_kwargs["url"] == "https://example.com/article"
                assert "Example Article" in call_kwargs["title"]

    @pytest.mark.asyncio
    async def test_handle_dm_link_extracts_title_from_agent(self):
        """Extracts title from agent markdown response."""
        mock_agent_result = "# Breaking News: Tech Industry Update\n\nDetailed summary here"

        with patch('personal.run_agent', new_callable=AsyncMock, return_value=mock_agent_result):
            with patch('personal.db.store_personal_source') as mock_store:
                mock_store.return_value = 1

                await personal.handle_dm_link(123, "https://example.com", "text")

                call_kwargs = mock_store.call_args[1]
                assert call_kwargs["title"] == "Breaking News: Tech Industry Update"

    @pytest.mark.asyncio
    async def test_handle_dm_link_agent_error(self):
        """Handles agent pipeline errors gracefully."""
        with patch('personal.run_agent', new_callable=AsyncMock, return_value="Error: Failed to fetch"):
            with patch('personal.db.store_personal_source') as mock_store:
                mock_store.return_value = None

                result = await personal.handle_dm_link(123, "https://example.com", "text")
                # Should still attempt to store
                assert mock_store.called

    @pytest.mark.asyncio
    async def test_handle_dm_link_exception_handling(self):
        """Returns None on exception."""
        with patch('personal.run_agent', new_callable=AsyncMock, side_effect=Exception("Network error")):
            result = await personal.handle_dm_link(123, "https://example.com", "text")
            assert result is None

    @pytest.mark.asyncio
    async def test_handle_dm_link_stores_summary(self):
        """Stores agent response as summary."""
        mock_response = "# Title\n\nThis is a detailed summary"

        with patch('personal.run_agent', new_callable=AsyncMock, return_value=mock_response):
            with patch('personal.db.store_personal_source') as mock_store:
                mock_store.return_value = 1

                await personal.handle_dm_link(123, "https://example.com", "text")

                call_kwargs = mock_store.call_args[1]
                assert call_kwargs["summary"] == mock_response
                assert call_kwargs["content"] == mock_response


class TestHandleDmForward:
    """Test DM forwarded message handling."""

    def test_handle_dm_forward_basic(self):
        """Store a forwarded message as personal source."""
        with patch('personal.db.store_personal_source') as mock_store:
            mock_store.return_value = 42

            result = personal.handle_dm_forward(
                tg_user_id=123,
                text="Important message forwarded here",
            )

            assert result == 42
            call_kwargs = mock_store.call_args[1]
            assert call_kwargs["tg_user_id"] == 123
            assert call_kwargs["source_type"] == "forwarded_message"
            assert call_kwargs["content"] == "Important message forwarded here"

    def test_handle_dm_forward_with_source(self):
        """Includes forwarded source in title."""
        with patch('personal.db.store_personal_source') as mock_store:
            mock_store.return_value = 1

            personal.handle_dm_forward(
                tg_user_id=123,
                text="Message",
                forwarded_from="Alice",
            )

            call_kwargs = mock_store.call_args[1]
            assert "Alice" in call_kwargs["title"]

    def test_handle_dm_forward_without_source(self):
        """Uses generic title if no forwarded_from."""
        with patch('personal.db.store_personal_source') as mock_store:
            mock_store.return_value = 1

            personal.handle_dm_forward(123, "Message")

            call_kwargs = mock_store.call_args[1]
            assert "Forwarded message" in call_kwargs["title"]

    def test_handle_dm_forward_stores_original_text(self):
        """Stores original text for search."""
        with patch('personal.db.store_personal_source') as mock_store:
            mock_store.return_value = 1

            personal.handle_dm_forward(123, "Important info", forwarded_from="Bob")

            call_kwargs = mock_store.call_args[1]
            assert call_kwargs["original_text"] == "Important info"

    def test_handle_dm_forward_db_error(self):
        """Propagates DB error (caller should handle)."""
        with patch('personal.db.store_personal_source', side_effect=Exception("DB error")):
            # Function does not catch exceptions
            with pytest.raises(Exception):
                personal.handle_dm_forward(123, "text")


class TestHandleDmNote:
    """Test DM personal note handling."""

    def test_handle_dm_note_basic(self):
        """Store a personal note."""
        with patch('personal.db.store_personal_source') as mock_store:
            mock_store.return_value = 99

            result = personal.handle_dm_note(123, "My personal todo list")

            assert result == 99
            call_kwargs = mock_store.call_args[1]
            assert call_kwargs["tg_user_id"] == 123
            assert call_kwargs["source_type"] == "note"
            assert call_kwargs["content"] == "My personal todo list"

    def test_handle_dm_note_no_url(self):
        """Note has no URL."""
        with patch('personal.db.store_personal_source') as mock_store:
            mock_store.return_value = 1

            personal.handle_dm_note(123, "Note text")

            call_kwargs = mock_store.call_args[1]
            assert "url" not in call_kwargs or call_kwargs["url"] is None

    def test_handle_dm_note_no_title(self):
        """Note generation doesn't require title."""
        with patch('personal.db.store_personal_source') as mock_store:
            mock_store.return_value = 1

            personal.handle_dm_note(456, "Quick thought")

            call_kwargs = mock_store.call_args[1]
            # Should not fail on missing title
            assert call_kwargs["content"] == "Quick thought"

    def test_handle_dm_note_multiline(self):
        """Note can span multiple lines."""
        with patch('personal.db.store_personal_source') as mock_store:
            mock_store.return_value = 1

            note_text = "Line 1\nLine 2\nLine 3"
            personal.handle_dm_note(789, note_text)

            call_kwargs = mock_store.call_args[1]
            assert call_kwargs["content"] == note_text

    def test_handle_dm_note_db_error(self):
        """Propagates DB error (caller should handle)."""
        with patch('personal.db.store_personal_source', side_effect=Exception("DB error")):
            # Function does not catch exceptions
            with pytest.raises(Exception):
                personal.handle_dm_note(123, "text")
