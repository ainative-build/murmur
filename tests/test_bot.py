"""Unit tests for bot.py — Telegram bot handlers and link detection."""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock, call
from datetime import datetime, timezone
import sys

# Mock external dependencies before importing bot
sys.modules['fastapi'] = MagicMock()
sys.modules['telegram'] = MagicMock()
sys.modules['telegram.ext'] = MagicMock()
sys.modules['telegram.constants'] = MagicMock()
sys.modules['agent'] = MagicMock()

# Import after mocking
import bot


class TestDetectLinkType:
    """Test _detect_link_type function."""

    def test_detect_twitter_url(self):
        """Should detect twitter.com URLs as 'tweet'."""
        assert bot._detect_link_type("https://twitter.com/user/status/123") == "tweet"
        assert bot._detect_link_type("http://TWITTER.COM/user/status/123") == "tweet"

    def test_detect_x_url(self):
        """Should detect x.com URLs as 'tweet'."""
        assert bot._detect_link_type("https://x.com/user/status/123") == "tweet"
        assert bot._detect_link_type("https://X.COM/user/status/123") == "tweet"

    def test_detect_youtube_url(self):
        """Should detect youtube.com URLs as 'youtube'."""
        assert bot._detect_link_type("https://youtube.com/watch?v=ABC") == "youtube"
        assert bot._detect_link_type("https://www.youtube.com/watch?v=ABC") == "youtube"

    def test_detect_youtu_be_short_url(self):
        """Should detect youtu.be short URLs as 'youtube'."""
        assert bot._detect_link_type("https://youtu.be/ABC") == "youtube"
        assert bot._detect_link_type("https://YOUTU.BE/ABC") == "youtube"

    def test_detect_linkedin_url(self):
        """Should detect linkedin.com URLs as 'linkedin'."""
        assert bot._detect_link_type("https://linkedin.com/in/username") == "linkedin"
        assert bot._detect_link_type("https://LINKEDIN.COM/in/username") == "linkedin"

    def test_detect_pdf_url(self):
        """Should detect PDF URLs by .pdf extension."""
        assert bot._detect_link_type("https://example.com/document.pdf") == "pdf"
        assert bot._detect_link_type("https://example.com/file.PDF") == "pdf"
        assert bot._detect_link_type("http://arxiv.org/paper.pdf") == "pdf"

    def test_detect_default_webpage(self):
        """Should return 'webpage' for unrecognized URLs."""
        assert bot._detect_link_type("https://example.com/article") == "webpage"
        assert bot._detect_link_type("https://github.com/user/repo") == "webpage"
        assert bot._detect_link_type("https://medium.com/@author/post") == "webpage"

    def test_detect_case_insensitive(self):
        """Link type detection should be case-insensitive."""
        assert bot._detect_link_type("HTTPS://TWITTER.COM/USER") == "tweet"
        assert bot._detect_link_type("HTTPs://YouTube.COM/watch") == "youtube"
        assert bot._detect_link_type("https://LINKEDIN.COM/in/user") == "linkedin"


class TestGroupMessageHandler:
    """Test group_message_handler function."""

    @pytest.mark.asyncio
    async def test_handler_extracts_message_data(self):
        """Handler should extract and store message data correctly."""
        # Create mock message
        mock_user = Mock()
        mock_user.id = 789
        mock_user.username = "testuser"

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.message_id = 123
        mock_message.chat_id = 456
        mock_message.text = "Hello everyone"
        mock_message.date = datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)
        mock_message.reply_to_message = None
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        with patch('bot.db.store_message') as mock_store_msg:
            with patch('bot.db.upsert_user'):
                with patch('bot.db.ensure_user_chat_state'):
                    mock_store_msg.return_value = 42

                    await bot.group_message_handler(mock_update, mock_context)

                    # Verify store_message was called with correct data
                    mock_store_msg.assert_called_once()
                    call_kwargs = mock_store_msg.call_args[1]
                    assert call_kwargs["tg_msg_id"] == 123
                    assert call_kwargs["tg_chat_id"] == 456
                    assert call_kwargs["tg_user_id"] == 789
                    assert call_kwargs["username"] == "testuser"
                    assert call_kwargs["text"] == "Hello everyone"
                    assert call_kwargs["has_links"] is False

    @pytest.mark.asyncio
    async def test_handler_detects_links(self):
        """Handler should detect URLs in message."""
        mock_user = Mock()
        mock_user.id = 789

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.message_id = 123
        mock_message.chat_id = 456
        mock_message.text = "Check this: https://example.com and https://twitter.com/user"
        mock_message.date = datetime.now(timezone.utc)
        mock_message.reply_to_message = None
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        with patch('bot.db.store_message') as mock_store_msg:
            with patch('bot.db.upsert_user'):
                with patch('bot.db.ensure_user_chat_state'):
                    with patch('bot._process_links_and_store', new_callable=AsyncMock):
                        mock_store_msg.return_value = 42

                        await bot.group_message_handler(mock_update, mock_context)

                        # Verify has_links is set to True
                        call_kwargs = mock_store_msg.call_args[1]
                        assert call_kwargs["has_links"] is True

    @pytest.mark.asyncio
    async def test_handler_stores_user_data(self):
        """Handler should upsert user and ensure user_chat_state."""
        mock_user = Mock()
        mock_user.id = 789
        mock_user.username = "testuser"

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.message_id = 123
        mock_message.chat_id = 456
        mock_message.text = "Hello"
        mock_message.date = datetime.now(timezone.utc)
        mock_message.reply_to_message = None
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        with patch('bot.db.store_message') as mock_store_msg:
            with patch('bot.db.upsert_user') as mock_upsert_user:
                with patch('bot.db.ensure_user_chat_state') as mock_ensure_state:
                    mock_store_msg.return_value = 42

                    await bot.group_message_handler(mock_update, mock_context)

                    # Verify user functions were called
                    mock_upsert_user.assert_called_once_with(789, "testuser")
                    mock_ensure_state.assert_called_once_with(789, 456)

    @pytest.mark.asyncio
    async def test_handler_calls_agent_on_links(self):
        """Handler should call agent processor if message has links and was stored."""
        mock_user = Mock()
        mock_user.id = 789

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.message_id = 123
        mock_message.chat_id = 456
        mock_message.text = "Check this: https://example.com"
        mock_message.date = datetime.now(timezone.utc)
        mock_message.reply_to_message = None
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        with patch('bot.db.store_message') as mock_store_msg:
            with patch('bot.db.upsert_user'):
                with patch('bot.db.ensure_user_chat_state'):
                    with patch('bot._process_links_and_store', new_callable=AsyncMock) as mock_process:
                        mock_store_msg.return_value = 42  # Non-None means message was stored

                        await bot.group_message_handler(mock_update, mock_context)

                        # Verify process_links was called
                        mock_process.assert_called_once()

    @pytest.mark.asyncio
    async def test_handler_runs_agent_even_on_db_failure(self):
        """Agent pipeline runs even if store_message returns None (duplicate or DB error).

        Link summarization is independent of persistence — transient Supabase failure
        should not suppress the group reply.
        """
        mock_user = Mock()
        mock_user.id = 789

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.message_id = 123
        mock_message.chat_id = 456
        mock_message.text = "Check: https://example.com"
        mock_message.date = datetime.now(timezone.utc)
        mock_message.reply_to_message = None
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        with patch('bot.db.store_message') as mock_store_msg:
            with patch('bot.db.upsert_user'):
                with patch('bot.db.ensure_user_chat_state'):
                    with patch('bot._process_links_and_store', new_callable=AsyncMock) as mock_process:
                        mock_store_msg.return_value = None  # DB failure or duplicate

                        await bot.group_message_handler(mock_update, mock_context)

                        # Agent pipeline still called with message_id=None
                        mock_process.assert_called_once()
                        assert mock_process.call_args[0][3] is None

    @pytest.mark.asyncio
    async def test_handler_skips_agent_if_no_links(self):
        """Handler should not call agent if message has no links."""
        mock_user = Mock()
        mock_user.id = 789

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.message_id = 123
        mock_message.chat_id = 456
        mock_message.text = "Just a regular message"
        mock_message.date = datetime.now(timezone.utc)
        mock_message.reply_to_message = None
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        with patch('bot.db.store_message') as mock_store_msg:
            with patch('bot.db.upsert_user'):
                with patch('bot.db.ensure_user_chat_state'):
                    with patch('bot._process_links_and_store', new_callable=AsyncMock) as mock_process:
                        mock_store_msg.return_value = 42

                        await bot.group_message_handler(mock_update, mock_context)

                        # Verify process_links was NOT called
                        mock_process.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_handles_no_message(self):
        """Handler should gracefully handle update with no message."""
        mock_update = Mock()
        mock_update.effective_message = None

        mock_context = Mock()

        # Should not raise
        await bot.group_message_handler(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_handler_handles_message_without_text(self):
        """Handler should gracefully handle message without text or caption."""
        mock_message = Mock()
        mock_message.text = None
        mock_message.caption = None
        mock_message.photo = None
        mock_message.document = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        # Should not raise
        await bot.group_message_handler(mock_update, mock_context)

    @pytest.mark.asyncio
    async def test_handler_handles_no_from_user(self):
        """Handler should handle message with no from_user."""
        mock_message = Mock()
        mock_message.from_user = None
        mock_message.message_id = 123
        mock_message.chat_id = 456
        mock_message.text = "Hello"
        mock_message.date = datetime.now(timezone.utc)
        mock_message.reply_to_message = None
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        with patch('bot.db.store_message') as mock_store_msg:
            with patch('bot.db.upsert_user'):
                with patch('bot.db.ensure_user_chat_state'):
                    mock_store_msg.return_value = 42

                    await bot.group_message_handler(mock_update, mock_context)

                    # Should use tg_user_id = 0 for None user
                    call_kwargs = mock_store_msg.call_args[1]
                    assert call_kwargs["tg_user_id"] == 0

    @pytest.mark.asyncio
    async def test_handler_with_reply_to_message(self):
        """Handler should capture reply_to_message info."""
        mock_user = Mock()
        mock_user.id = 789

        mock_reply_msg = Mock()
        mock_reply_msg.message_id = 100

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.message_id = 123
        mock_message.chat_id = 456
        mock_message.text = "Hello"
        mock_message.date = datetime.now(timezone.utc)
        mock_message.reply_to_message = mock_reply_msg
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        with patch('bot.db.store_message') as mock_store_msg:
            with patch('bot.db.upsert_user'):
                with patch('bot.db.ensure_user_chat_state'):
                    mock_store_msg.return_value = 42

                    await bot.group_message_handler(mock_update, mock_context)

                    call_kwargs = mock_store_msg.call_args[1]
                    assert call_kwargs["reply_to_tg_msg_id"] == 100


class TestURLDetectionRegex:
    """Test URL detection via regex."""

    def test_regex_matches_http_url(self):
        """Regex should match HTTP URLs."""
        text = "Check out http://example.com"
        matches = bot.re.findall(bot.URL_REGEX, text)
        assert len(matches) == 1
        assert "http://example.com" in matches

    def test_regex_matches_https_url(self):
        """Regex should match HTTPS URLs."""
        text = "See https://example.com/page"
        matches = bot.re.findall(bot.URL_REGEX, text)
        assert len(matches) == 1
        assert "https://example.com/page" in matches

    def test_regex_matches_multiple_urls(self):
        """Regex should match multiple URLs in text."""
        text = "https://example.com and https://twitter.com/user"
        matches = bot.re.findall(bot.URL_REGEX, text)
        assert len(matches) == 2

    def test_regex_stops_at_whitespace(self):
        """Regex should stop at whitespace."""
        text = "Check https://example.com here"
        matches = bot.re.findall(bot.URL_REGEX, text)
        assert "https://example.com" in matches
        assert "here" not in matches[0]

    def test_regex_handles_urls_with_query_params(self):
        """Regex should match URLs with query parameters."""
        text = "https://youtube.com/watch?v=ABC123&t=10s"
        matches = bot.re.findall(bot.URL_REGEX, text)
        assert len(matches) == 1
        assert "https://youtube.com/watch?v=ABC123&t=10s" in matches


class TestProcessLinksAndStore:
    """Test _process_links_and_store function."""

    @pytest.mark.asyncio
    async def test_process_links_calls_agent(self):
        """Should call run_agent for link processing."""
        mock_message = Mock()
        mock_message.reply_text = AsyncMock()

        with patch('bot.run_agent', new_callable=AsyncMock) as mock_agent:
            with patch('bot.db.store_link_summary'):
                mock_agent.return_value = "# Article Title\nSummary content"

                text = "Check https://example.com"
                urls = ["https://example.com"]

                await bot._process_links_and_store(mock_message, text, urls, 42)

                mock_agent.assert_called_once_with(text)

    @pytest.mark.asyncio
    async def test_process_links_extracts_title(self):
        """Should extract title from agent response."""
        mock_message = Mock()
        mock_message.reply_text = AsyncMock()

        with patch('bot.run_agent', new_callable=AsyncMock) as mock_agent:
            with patch('bot.db.store_link_summary') as mock_store_link:
                mock_agent.return_value = "# Amazing Article\nThis is a summary."

                await bot._process_links_and_store(mock_message, "text", ["https://example.com"], 42)

                # Check that store_link_summary was called with extracted title
                call_kwargs = mock_store_link.call_args[1]
                assert call_kwargs["title"] == "Amazing Article"

    @pytest.mark.asyncio
    async def test_process_links_stores_link_type(self):
        """Should store detected link type."""
        mock_message = Mock()
        mock_message.reply_text = AsyncMock()

        with patch('bot.run_agent', new_callable=AsyncMock) as mock_agent:
            with patch('bot.db.store_link_summary') as mock_store_link:
                mock_agent.return_value = "# Video Summary\nContent here"

                await bot._process_links_and_store(
                    mock_message,
                    "text",
                    ["https://youtube.com/watch?v=ABC"],
                    42
                )

                call_kwargs = mock_store_link.call_args[1]
                assert call_kwargs["link_type"] == "youtube"

    @pytest.mark.asyncio
    async def test_process_links_handles_agent_error(self):
        """Should handle agent errors gracefully."""
        mock_message = Mock()
        mock_message.reply_text = AsyncMock()

        with patch('bot.run_agent', new_callable=AsyncMock) as mock_agent:
            with patch('bot.logger') as mock_logger:
                mock_agent.return_value = "Error: Failed to process"

                await bot._process_links_and_store(mock_message, "text", ["https://example.com"], 42)

                # Should log the error
                mock_logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_process_links_replies_with_summary(self):
        """Should reply with agent summary in group."""
        mock_message = Mock()
        mock_message.reply_text = AsyncMock()

        with patch('bot.run_agent', new_callable=AsyncMock) as mock_agent:
            with patch('bot.db.store_link_summary'):
                mock_agent.return_value = "# Title\nSummary content"

                await bot._process_links_and_store(mock_message, "text", ["https://example.com"], 42)

                # Should reply with the summary (escaped for HTML)
                assert mock_message.reply_text.called

    @pytest.mark.asyncio
    async def test_process_links_chunks_long_messages(self):
        """Should split long responses into chunks."""
        mock_message = Mock()
        mock_message.reply_text = AsyncMock()

        # Create a response longer than MAX_TELEGRAM_MSG_LEN
        long_response = "X" * (bot.MAX_TELEGRAM_MSG_LEN + 100)

        with patch('bot.run_agent', new_callable=AsyncMock) as mock_agent:
            with patch('bot.db.store_link_summary'):
                mock_agent.return_value = long_response

                await bot._process_links_and_store(mock_message, "text", ["https://example.com"], 42)

                # Should be called multiple times for chunks
                assert mock_message.reply_text.call_count >= 2
