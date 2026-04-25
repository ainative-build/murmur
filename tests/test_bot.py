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

    def test_detect_github(self):
        """Should detect GitHub URLs."""
        assert bot._detect_link_type("https://github.com/user/repo") == "github"

    def test_detect_grok(self):
        """Should detect Grok share URLs."""
        assert bot._detect_link_type("https://grok.com/share/abc123") == "grok"

    def test_detect_spotify(self):
        """Should detect Spotify URLs."""
        assert bot._detect_link_type("https://open.spotify.com/episode/abc") == "spotify"

    def test_detect_default_webpage(self):
        """Should return 'webpage' for unrecognized URLs."""
        assert bot._detect_link_type("https://example.com/article") == "webpage"
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
    async def test_handler_runs_agent_on_transient_db_failure(self):
        """Agent still runs when store_message AND get_message_id both return None.

        That combination means the row genuinely isn't in DB — this is a real
        write failure, not a duplicate retry. Proceed best-effort rather than
        silently dropping a valid summary.
        """
        bot._processing_messages.clear()

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

        with patch('bot.db.store_message', return_value=None):
            with patch('bot.db.get_message_id', return_value=None):
                with patch('bot.db.upsert_user'):
                    with patch('bot.db.ensure_user_chat_state'):
                        with patch('bot._process_links_and_store', new_callable=AsyncMock) as mock_process:
                            await bot.group_message_handler(mock_update, mock_context)

                            # Agent pipeline still called with message_id=None (best-effort)
                            mock_process.assert_called_once()
                            assert mock_process.call_args[0][3] is None

    @pytest.mark.asyncio
    async def test_handler_skips_retry_when_summary_already_delivered(self):
        """Duplicate webhook with a stored link_summary → already delivered → skip.

        The atomic claim (store_message INSERT...ON CONFLICT) returns None on
        retry. get_message_id finds the existing row, has_link_summary returns
        True (because the original attempt got far enough to send the reply
        and persist the summary afterwards), so we skip — preventing duplicates.
        """
        bot._processing_messages.clear()

        mock_user = Mock()
        mock_user.id = 789

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.message_id = 999
        mock_message.chat_id = 888
        mock_message.text = "Check: https://example.com"
        mock_message.date = datetime.now(timezone.utc)
        mock_message.reply_to_message = None
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        with patch('bot.db.store_message', return_value=None):  # claim lost (duplicate)
            with patch('bot.db.get_message_id', return_value=42) as mock_get_id:
                with patch('bot.db.has_link_summary', return_value=True) as mock_has:
                    with patch('bot.db.upsert_user') as mock_upsert:
                        with patch('bot._process_links_and_store', new_callable=AsyncMock) as mock_process:
                            await bot.group_message_handler(mock_update, mock_context)

                            mock_get_id.assert_called_once_with(888, 999)
                            mock_has.assert_called_once_with(42)
                            mock_process.assert_not_called()
                            # Skip path returns before user/chat state writes
                            mock_upsert.assert_not_called()

    @pytest.mark.asyncio
    async def test_handler_retries_when_prior_attempt_left_no_summary(self):
        """Duplicate webhook with NO link_summary → prior attempt died before
        delivery → retry processes (prevents permanent drop on partial failures).
        """
        bot._processing_messages.clear()

        mock_user = Mock()
        mock_user.id = 789

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.message_id = 1001
        mock_message.chat_id = 2002
        mock_message.text = "Check: https://example.com"
        mock_message.date = datetime.now(timezone.utc)
        mock_message.reply_to_message = None
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        with patch('bot.db.store_message', return_value=None):  # claim lost
            with patch('bot.db.get_message_id', return_value=77):  # row exists
                with patch('bot.db.has_link_summary', return_value=False):  # but never delivered
                    with patch('bot.db.upsert_user'):
                        with patch('bot.db.ensure_user_chat_state'):
                            with patch('bot._process_links_and_store', new_callable=AsyncMock) as mock_process:
                                await bot.group_message_handler(mock_update, mock_context)

                                # Retry runs the pipeline with the existing message_id
                                mock_process.assert_called_once()
                                assert mock_process.call_args[0][3] == 77

    @pytest.mark.asyncio
    async def test_handler_skips_retry_for_no_link_messages(self):
        """Duplicate webhook for a no-link message → nothing user-visible to
        re-deliver → skip (avoids re-running media analysis on every retry)."""
        bot._processing_messages.clear()

        mock_user = Mock()
        mock_user.id = 789

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.message_id = 3003
        mock_message.chat_id = 4004
        mock_message.text = "Just chatting, no links"
        mock_message.date = datetime.now(timezone.utc)
        mock_message.reply_to_message = None
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        with patch('bot.db.store_message', return_value=None):  # claim lost
            with patch('bot.db.get_message_id', return_value=55):  # row exists
                with patch('bot.db.has_link_summary') as mock_has:
                    with patch('bot.db.upsert_user') as mock_upsert:
                        await bot.group_message_handler(mock_update, mock_context)

                        # Without links, has_link_summary doesn't even need to be checked
                        mock_has.assert_not_called()
                        mock_upsert.assert_not_called()

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
        # Reset in-memory dedup so this test can run independently
        bot._processing_messages.clear()

        mock_user = Mock()
        mock_user.id = 789
        mock_user.username = "tester"

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.message_id = 555
        mock_message.chat_id = 666
        mock_message.text = None
        mock_message.caption = None
        mock_message.photo = None
        mock_message.voice = None
        mock_message.audio = None
        mock_message.document = None
        mock_message.date = datetime.now(timezone.utc)
        mock_message.reply_to_message = None
        mock_message.forward_origin = None

        mock_update = Mock()
        mock_update.effective_message = mock_message

        mock_context = Mock()

        # Should not raise — empty text returns before any DB calls
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
        """Should handle agent errors gracefully with TinyFish fallback."""
        mock_message = Mock()
        mock_message.reply_text = AsyncMock()

        with patch('bot.run_agent', new_callable=AsyncMock) as mock_agent:
            with patch('bot.logger') as mock_logger:
                # Agent fails, TinyFish fallback also returns None
                mock_agent.return_value = "Error: Failed to process"
                with patch('tools.tinyfish_fetcher.fetch_url_content', new_callable=AsyncMock, return_value=None):
                    await bot._process_links_and_store(mock_message, "text", ["https://example.com"], 42)

                    # Should log warning and reply with error
                    mock_logger.warning.assert_called()
                    mock_message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_process_links_stores_summary_only_after_reply_success(self):
        """link_summary must be stored AFTER reply succeeds, not before.

        This ordering makes link_summary the cross-instance "summary delivered"
        signal: if reply fails entirely (no sent_msgs), no link_summary is
        stored, leaving the door open for a webhook retry to re-attempt.
        """
        mock_message = Mock()
        # reply_text raises on every call → sent_msgs stays empty
        mock_message.reply_text = AsyncMock(side_effect=Exception("Telegram down"))

        with patch('bot.run_agent', new_callable=AsyncMock) as mock_agent:
            with patch('bot.db.store_link_summary') as mock_store_link:
                mock_agent.return_value = "# Title\nSummary content"

                await bot._process_links_and_store(
                    mock_message, "text", ["https://example.com"], 42
                )

                # Reply attempted (and failed twice — HTML + plain-text fallback)
                assert mock_message.reply_text.called
                # No link_summary stored because no reply chunk landed
                mock_store_link.assert_not_called()

    @pytest.mark.asyncio
    async def test_process_links_no_summary_on_partial_delivery(self):
        """Partial delivery (some chunks sent, later chunks fail) must NOT
        write the delivered signal — otherwise retries skip and the user is
        permanently stuck with a truncated reply.
        """
        # First reply call (chunk 1) succeeds; subsequent calls (chunk 2 HTML
        # + chunk 2 plain-text fallback) all fail.
        call_count = {"n": 0}

        async def reply_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return Mock()
            raise Exception("Telegram error mid-stream")

        mock_message = Mock()
        mock_message.reply_text = AsyncMock(side_effect=reply_side_effect)

        # Long enough to require multiple chunks
        long_response = "X" * (bot.MAX_TELEGRAM_MSG_LEN * 2 + 100)

        with patch('bot.run_agent', new_callable=AsyncMock) as mock_agent:
            with patch('bot.db.store_link_summary') as mock_store_link:
                with patch('bot.db.schedule_message_deletion') as mock_sched:
                    mock_agent.return_value = long_response

                    await bot._process_links_and_store(
                        mock_message, "text", ["https://example.com"], 42
                    )

                    # No delivered signal: chunk 2 failed, so fully_delivered=False
                    mock_store_link.assert_not_called()
                    # But the chunk that DID land still gets scheduled for cleanup
                    assert mock_sched.called

    @pytest.mark.asyncio
    async def test_process_links_skips_tinyfish_for_youtube_on_error(self):
        """When agent fails for a YouTube URL, do NOT fall back to TinyFish.

        TinyFish returns the rendered YouTube page chrome (footer/nav) instead
        of video content, producing nonsense summaries. The user should get a
        clear error instead of a footer summary.
        """
        mock_message = Mock()
        mock_message.reply_text = AsyncMock()

        with patch('bot.run_agent', new_callable=AsyncMock) as mock_agent:
            mock_agent.return_value = "Error: YouTube extraction failed"
            with patch('tools.tinyfish_fetcher.fetch_url_content', new_callable=AsyncMock) as mock_tf:
                await bot._process_links_and_store(
                    mock_message,
                    "text",
                    ["https://youtube.com/watch?v=ABC"],
                    42,
                )

                # TinyFish must NOT be called for YouTube fallback
                mock_tf.assert_not_called()
                # User gets a clear error message instead
                mock_message.reply_text.assert_called_once()
                reply_text = mock_message.reply_text.call_args[0][0]
                assert "YouTube" in reply_text or "transcript" in reply_text.lower()

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


class TestSendChunksWithHtmlFallback:
    """Unit tests for `_send_chunks_with_html_fallback`."""

    @pytest.mark.asyncio
    async def test_all_chunks_succeed_via_html(self):
        """Every HTML chunk lands → fully_delivered=True, all sends captured."""
        mock_message = Mock()
        mock_message.reply_text = AsyncMock()

        sent, ok = await bot._send_chunks_with_html_fallback(
            mock_message, "short html", "short plain"
        )
        assert ok is True
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_plain_text_fallback_is_captured_in_sent_msgs(self):
        """When HTML send raises and plain-text fallback succeeds, the
        plain-text send is captured in sent_msgs and fully_delivered stays True.

        Without this, a successful plain-text fallback delivery would not write
        the link_summary signal, and a webhook retry would resend duplicate
        replies to the user.
        """
        # HTML attempt (with kwargs) raises; plain-text attempt (no kwargs) succeeds.
        async def reply_side_effect(text, **kwargs):
            if kwargs:  # parse_mode passed → HTML attempt
                raise Exception("HTML parse failed")
            return Mock()

        mock_message = Mock()
        mock_message.reply_text = AsyncMock(side_effect=reply_side_effect)

        sent, ok = await bot._send_chunks_with_html_fallback(
            mock_message, "<bad>html</bad>", "plain text"
        )
        assert ok is True
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_partial_delivery_marks_not_fully_delivered(self):
        """First chunk lands, later chunk fails on both HTML and plain-text →
        fully_delivered=False so caller skips writing the delivered signal."""
        call_count = {"n": 0}

        async def reply_side_effect(*args, **kwargs):
            call_count["n"] += 1
            # call 1: chunk 1 HTML succeeds
            # call 2: chunk 2 HTML fails
            # call 3: chunk 2 plain-text fails
            if call_count["n"] == 1:
                return Mock()
            raise Exception("Telegram error")

        mock_message = Mock()
        mock_message.reply_text = AsyncMock(side_effect=reply_side_effect)

        long_html = "X" * (bot.MAX_TELEGRAM_MSG_LEN * 2 + 50)
        sent, ok = await bot._send_chunks_with_html_fallback(
            mock_message, long_html, long_html
        )
        assert ok is False
        # First chunk did land; subsequent chunk failed both attempts
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_total_failure_returns_empty_and_not_delivered(self):
        """All HTML and plain-text attempts fail → empty sent_msgs, not delivered."""
        mock_message = Mock()
        mock_message.reply_text = AsyncMock(side_effect=Exception("Telegram down"))

        sent, ok = await bot._send_chunks_with_html_fallback(
            mock_message, "html", "plain"
        )
        assert ok is False
        assert sent == []
