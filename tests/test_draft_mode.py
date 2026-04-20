"""Unit tests for draft_mode.py — Multi-turn /draft conversation handler."""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from telegram.ext import ConversationHandler

import draft_mode


class TestDraftStartHandler:
    """Test /draft <topic> initialization."""

    @pytest.mark.asyncio
    async def test_draft_start_no_topic(self):
        """Returns END if no topic provided."""
        mock_update = Mock()
        mock_update.message.reply_text = AsyncMock()
        mock_update.effective_user.id = 123
        mock_context = Mock()
        mock_context.args = None

        result = await draft_mode.draft_start_handler(mock_update, mock_context)

        assert result == ConversationHandler.END
        mock_update.message.reply_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_draft_start_creates_session(self):
        """Creates draft session for valid topic."""
        mock_update = Mock()
        mock_update.message.reply_text = AsyncMock()
        mock_update.effective_user.id = 123
        mock_context = Mock()
        mock_context.args = ["frontend", "stack"]
        mock_context.user_data = {}

        with patch('draft_mode.db.get_user_chats', return_value=[{"tg_chat_id": 456}]):
            with patch('draft_mode.db.get_messages_by_keyword', return_value=[]):
                with patch('draft_mode.db.get_link_summaries_for_messages', return_value=[]):
                    with patch('draft_mode.db.create_draft_session', return_value=999):
                        with patch('draft_mode.summarizer.build_draft_system_prompt', return_value="prompt"):
                            with patch('draft_mode.summarizer.generate_draft_response', new_callable=AsyncMock, return_value="Opening message"):
                                with patch('draft_mode.db.append_draft_message'):
                                    result = await draft_mode.draft_start_handler(mock_update, mock_context)

                                    assert result == draft_mode.DRAFTING
                                    assert mock_context.user_data["draft_session_id"] == 999

    @pytest.mark.asyncio
    async def test_draft_start_existing_session(self):
        """Returns DRAFTING if user already has active session."""
        mock_update = Mock()
        mock_update.message.reply_text = AsyncMock()
        mock_update.effective_user.id = 123
        mock_context = Mock()
        mock_context.args = ["topic"]

        with patch('draft_mode.db.get_active_draft_session', return_value={"topic": "old topic", "id": 111}):
            result = await draft_mode.draft_start_handler(mock_update, mock_context)

            assert result == draft_mode.DRAFTING
            call_text = mock_update.message.reply_text.call_args[0][0]
            assert "already have an active draft" in call_text

    @pytest.mark.asyncio
    async def test_draft_start_no_chats(self):
        """Returns END if user not in any group."""
        mock_update = Mock()
        mock_update.message.reply_text = AsyncMock()
        mock_update.effective_user.id = 123
        mock_context = Mock()
        mock_context.args = ["topic"]

        with patch('draft_mode.db.get_active_draft_session', return_value=None):
            with patch('draft_mode.db.get_user_chats', return_value=[]):
                result = await draft_mode.draft_start_handler(mock_update, mock_context)

                assert result == ConversationHandler.END
                call_text = mock_update.message.reply_text.call_args[0][0]
                assert "haven't seen you in any groups" in call_text


class TestDraftContinueHandler:
    """Test user messages during draft mode."""

    @pytest.mark.asyncio
    async def test_draft_continue_appends_message(self):
        """User message is appended to conversation."""
        mock_update = Mock()
        mock_update.effective_user.id = 123
        mock_update.message.text = "I think React is better"
        mock_update.message.reply_text = AsyncMock()
        mock_context = Mock()
        mock_context.user_data = {
            "draft_session_id": 999,
            "draft_system_prompt": "prompt",
        }

        with patch('draft_mode.db.append_draft_message') as mock_append:
            with patch('draft_mode.db.get_active_draft_session', return_value={
                "conversation_history": [{"role": "user", "content": "test"}],
                "id": 999,
            }):
                with patch('draft_mode.summarizer.generate_draft_response', new_callable=AsyncMock, return_value="Good point"):
                    result = await draft_mode.draft_continue_handler(mock_update, mock_context)

                    assert result == draft_mode.DRAFTING
                    assert mock_append.called

    @pytest.mark.asyncio
    async def test_draft_continue_generates_response(self):
        """Generates response and appends to history."""
        mock_update = Mock()
        mock_update.effective_user.id = 123
        mock_update.message.text = "My thoughts"
        mock_update.message.reply_text = AsyncMock()
        mock_context = Mock()
        mock_context.user_data = {
            "draft_session_id": 999,
            "draft_system_prompt": "prompt",
        }

        with patch('draft_mode.db.append_draft_message'):
            with patch('draft_mode.db.get_active_draft_session', return_value={
                "conversation_history": [{"role": "user", "content": "start"}],
                "id": 999,
            }):
                with patch('draft_mode.summarizer.generate_draft_response', new_callable=AsyncMock, return_value="Murmur response"):
                    result = await draft_mode.draft_continue_handler(mock_update, mock_context)

                    assert result == draft_mode.DRAFTING
                    mock_update.message.reply_text.assert_called()

    @pytest.mark.asyncio
    async def test_draft_continue_recover_from_db(self):
        """Recovers session from DB if not in user_data."""
        mock_update = Mock()
        mock_update.effective_user.id = 123
        mock_update.message.text = "message"
        mock_update.message.reply_text = AsyncMock()
        mock_context = Mock()
        mock_context.user_data = {}

        with patch('draft_mode.db.get_active_draft_session', return_value={
            "id": 888,
            "conversation_history": [],
            "context_snapshot": {"context_text": "context"},
        }):
            with patch('draft_mode.db.append_draft_message'):
                with patch('draft_mode.summarizer.build_draft_system_prompt', return_value="prompt"):
                    with patch('draft_mode.summarizer.generate_draft_response', new_callable=AsyncMock, return_value="response"):
                        result = await draft_mode.draft_continue_handler(mock_update, mock_context)

                        assert result == draft_mode.DRAFTING
                        assert mock_context.user_data["draft_session_id"] == 888

    @pytest.mark.asyncio
    async def test_draft_continue_no_session(self):
        """Returns END if no session found."""
        mock_update = Mock()
        mock_update.effective_user.id = 123
        mock_update.message.reply_text = AsyncMock()
        mock_context = Mock()
        mock_context.user_data = {}

        with patch('draft_mode.db.get_active_draft_session', return_value=None):
            result = await draft_mode.draft_continue_handler(mock_update, mock_context)

            assert result == ConversationHandler.END


class TestDraftEndHandler:
    """Test /done — end draft and save to notes."""

    @pytest.mark.asyncio
    async def test_draft_end_saves_note(self):
        """Saves draft conversation as personal note."""
        mock_update = Mock()
        mock_update.effective_user.id = 123
        mock_update.message.reply_text = AsyncMock()
        mock_context = Mock()
        mock_context.user_data = {"draft_session_id": 999}

        with patch('draft_mode.db.get_active_draft_session', return_value={
            "id": 999,
            "topic": "Frontend Stack",
            "conversation_history": [
                {"role": "user", "content": "Start"},
                {"role": "model", "content": "Response"},
            ],
        }):
            with patch('draft_mode.db.end_draft_session') as mock_end:
                with patch('draft_mode.personal.handle_dm_note') as mock_note:
                    result = await draft_mode.draft_end_handler(mock_update, mock_context)

                    assert result == ConversationHandler.END
                    assert mock_note.called
                    call_kwargs = mock_note.call_args[0]
                    assert "Frontend Stack" in call_kwargs[1] or call_kwargs[0] == 123
                    mock_end.assert_called_once_with(999)

    @pytest.mark.asyncio
    async def test_draft_end_clears_user_data(self):
        """Clears session data from context."""
        mock_update = Mock()
        mock_update.effective_user.id = 123
        mock_update.message.reply_text = AsyncMock()
        mock_context = Mock()
        mock_context.user_data = {
            "draft_session_id": 999,
            "draft_system_prompt": "prompt",
        }

        with patch('draft_mode.db.get_active_draft_session', return_value={
            "id": 999,
            "topic": "test",
            "conversation_history": [],
        }):
            with patch('draft_mode.db.end_draft_session'):
                with patch('draft_mode.personal.handle_dm_note'):
                    result = await draft_mode.draft_end_handler(mock_update, mock_context)

                    assert "draft_session_id" not in mock_context.user_data
                    assert "draft_system_prompt" not in mock_context.user_data

    @pytest.mark.asyncio
    async def test_draft_end_no_session(self):
        """Handles case where no session exists."""
        mock_update = Mock()
        mock_update.effective_user.id = 123
        mock_update.message.reply_text = AsyncMock()
        mock_context = Mock()
        mock_context.user_data = {}

        with patch('draft_mode.db.get_active_draft_session', return_value=None):
            result = await draft_mode.draft_end_handler(mock_update, mock_context)

            assert result == ConversationHandler.END


class TestDraftCancelHandler:
    """Test /cancel — discard draft."""

    @pytest.mark.asyncio
    async def test_draft_cancel_discards_session(self):
        """Cancels session without saving."""
        mock_update = Mock()
        mock_update.effective_user.id = 123
        mock_update.message.reply_text = AsyncMock()
        mock_context = Mock()
        mock_context.user_data = {"draft_session_id": 999}

        with patch('draft_mode.db.cancel_draft_session') as mock_cancel:
            result = await draft_mode.draft_cancel_handler(mock_update, mock_context)

            assert result == ConversationHandler.END
            mock_cancel.assert_called_once_with(999)

    @pytest.mark.asyncio
    async def test_draft_cancel_clears_user_data(self):
        """Clears session from context."""
        mock_update = Mock()
        mock_update.effective_user.id = 123
        mock_update.message.reply_text = AsyncMock()
        mock_context = Mock()
        mock_context.user_data = {
            "draft_session_id": 999,
            "draft_system_prompt": "prompt",
        }

        with patch('draft_mode.db.cancel_draft_session'):
            result = await draft_mode.draft_cancel_handler(mock_update, mock_context)

            assert "draft_session_id" not in mock_context.user_data
            assert "draft_system_prompt" not in mock_context.user_data

    @pytest.mark.asyncio
    async def test_draft_cancel_no_session(self):
        """Gracefully handles no existing session."""
        mock_update = Mock()
        mock_update.effective_user.id = 123
        mock_update.message.reply_text = AsyncMock()
        mock_context = Mock()
        mock_context.user_data = {}

        with patch('draft_mode.db.get_active_draft_session', return_value=None):
            result = await draft_mode.draft_cancel_handler(mock_update, mock_context)

            assert result == ConversationHandler.END
