"""Unit tests for commands.py — Telegram DM command handlers."""

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock

from commands import start_handler, COMMAND_LIST


class TestStartHandler:
    """Test /start command handler."""

    @pytest.mark.asyncio
    async def test_start_handler_sends_welcome_message(self):
        """Start handler should send welcome message with command list."""
        # Create mock objects
        mock_user = Mock()
        mock_user.id = 123
        mock_user.username = "testuser"
        mock_user.first_name = "Test"

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.reply_text = AsyncMock()

        mock_update = Mock()
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message
        mock_update.message = mock_message

        mock_context = Mock()

        # Call handler
        await start_handler(mock_update, mock_context)

        # Verify reply_text was called
        mock_message.reply_text.assert_called_once()
        call_args = mock_message.reply_text.call_args

        # Check that message contains expected content
        sent_text = call_args[0][0]
        assert "Test" in sent_text  # first_name should be included
        assert "Murmur" in sent_text
        assert "Available Commands" in sent_text
        assert "parse_mode" in call_args[1]
        assert call_args[1]["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_start_handler_includes_all_commands(self):
        """Welcome message should include all planned commands."""
        mock_user = Mock()
        mock_user.id = 123
        mock_user.first_name = "Test"

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.reply_text = AsyncMock()

        mock_update = Mock()
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message
        mock_update.message = mock_message

        mock_context = Mock()

        await start_handler(mock_update, mock_context)

        sent_text = mock_message.reply_text.call_args[0][0]

        # Check for key commands
        assert "/start" in sent_text
        assert "/catchup" in sent_text
        assert "/search" in sent_text
        assert "/topics" in sent_text
        assert "/topic" in sent_text
        assert "/decide" in sent_text

    @pytest.mark.asyncio
    async def test_start_handler_logs_user_info(self):
        """Handler should log user ID and username."""
        mock_user = Mock()
        mock_user.id = 456
        mock_user.username = "myusername"
        mock_user.first_name = "Test"

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.reply_text = AsyncMock()

        mock_update = Mock()
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message
        mock_update.message = mock_message

        mock_context = Mock()

        with patch('commands.logger') as mock_logger:
            await start_handler(mock_update, mock_context)
            mock_logger.info.assert_called_once()
            log_msg = mock_logger.info.call_args[0][0]
            assert "456" in log_msg  # user ID
            assert "myusername" in log_msg  # username

    @pytest.mark.asyncio
    async def test_start_handler_html_escaping(self):
        """Message should use HTML parse mode for proper escaping."""
        mock_user = Mock()
        mock_user.id = 123
        mock_user.first_name = "Test"

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.reply_text = AsyncMock()

        mock_update = Mock()
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message
        mock_update.message = mock_message

        mock_context = Mock()

        await start_handler(mock_update, mock_context)

        # Check parse_mode is HTML
        call_kwargs = mock_message.reply_text.call_args[1]
        assert call_kwargs["parse_mode"] == "HTML"

    @pytest.mark.asyncio
    async def test_start_handler_message_structure(self):
        """Welcome message should have clear structure."""
        mock_user = Mock()
        mock_user.id = 123
        mock_user.first_name = "Alice"

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.reply_text = AsyncMock()

        mock_update = Mock()
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message
        mock_update.message = mock_message

        mock_context = Mock()

        await start_handler(mock_update, mock_context)

        sent_text = mock_message.reply_text.call_args[0][0]

        # Should have greeting
        assert "Hey Alice" in sent_text

        # Should mention core features
        assert "capture" in sent_text.lower()
        assert "summarize" in sent_text.lower() or "summary" in sent_text.lower()

    @pytest.mark.asyncio
    async def test_start_handler_without_username(self):
        """Handler should work if username is None."""
        mock_user = Mock()
        mock_user.id = 789
        mock_user.username = None
        mock_user.first_name = "Test"

        mock_message = Mock()
        mock_message.from_user = mock_user
        mock_message.reply_text = AsyncMock()

        mock_update = Mock()
        mock_update.effective_user = mock_user
        mock_update.effective_message = mock_message
        mock_update.message = mock_message

        mock_context = Mock()

        # Should not raise
        await start_handler(mock_update, mock_context)
        mock_message.reply_text.assert_called_once()


class TestCommandList:
    """Test COMMAND_LIST constant."""

    def test_command_list_is_string(self):
        """COMMAND_LIST should be a string."""
        assert isinstance(COMMAND_LIST, str)

    def test_command_list_contains_available_commands_header(self):
        """COMMAND_LIST should mention 'Available Commands'."""
        assert "Available Commands" in COMMAND_LIST

    def test_command_list_has_basic_commands(self):
        """COMMAND_LIST should include basic commands."""
        assert "/start" in COMMAND_LIST
        assert "/catchup" in COMMAND_LIST
        assert "/search" in COMMAND_LIST

    def test_command_list_has_advanced_commands(self):
        """COMMAND_LIST should include advanced commands."""
        assert "/topics" in COMMAND_LIST
        assert "/decide" in COMMAND_LIST

    def test_command_list_includes_all_commands(self):
        """COMMAND_LIST should include all implemented commands."""
        for cmd in ["/note", "/sources", "/delete", "/remind", "/export", "/kb"]:
            assert cmd in COMMAND_LIST, f"Missing {cmd} in COMMAND_LIST"

    def test_command_list_is_html_formatted(self):
        """COMMAND_LIST should have HTML formatting."""
        # Should have bold/italic tags for formatting
        assert "<b>" in COMMAND_LIST or "<i>" in COMMAND_LIST
