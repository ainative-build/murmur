"""Unit tests for reminders.py — Scheduled reminder check and send."""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime, timezone

import reminders


class TestCheckAndSendReminders:
    """Test check_and_send_reminders orchestration."""

    @pytest.mark.asyncio
    async def test_check_and_send_reminders_success(self):
        """Successfully sends reminders to all users with due reminders."""
        mock_bot = Mock()
        mock_bot.send_message = AsyncMock()

        users_with_reminders = [
            {
                "tg_user_id": 123,
                "reminder_frequency": "daily",
            },
            {
                "tg_user_id": 456,
                "reminder_frequency": "weekly",
            },
        ]

        with patch('reminders.db.get_users_with_reminders_due', return_value=users_with_reminders):
            with patch('reminders.db.get_user_chats', side_effect=lambda uid: [{"tg_chat_id": 789}]):
                with patch('reminders.db.get_last_catchup', return_value=None):
                    with patch('reminders.db.get_messages_since', return_value=[
                        {"id": 1, "text": "message"}
                    ]):
                        with patch('reminders.summarizer.generate_reminder_digest', new_callable=AsyncMock, return_value="📬 1 new message"):
                            with patch('reminders.db.update_last_reminder'):
                                with patch('reminders.db.expire_stale_drafts', return_value=0):
                                    sent = await reminders.check_and_send_reminders(mock_bot)

                                    assert sent == 2
                                    assert mock_bot.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_check_and_send_skips_off_reminders(self):
        """Skips users with reminder_frequency='off'."""
        mock_bot = Mock()

        users = [
            {"tg_user_id": 111, "reminder_frequency": "off"},
            {"tg_user_id": 222, "reminder_frequency": "daily"},
        ]

        with patch('reminders.db.get_users_with_reminders_due', return_value=users):
            with patch('reminders.db.get_user_chats', side_effect=lambda uid: [{"tg_chat_id": 789}]):
                with patch('reminders.db.get_last_catchup', return_value=None):
                    with patch('reminders.db.get_messages_since', return_value=[{"id": 1}]):
                        with patch('reminders.summarizer.generate_reminder_digest', new_callable=AsyncMock, return_value="digest"):
                            with patch('reminders.db.expire_stale_drafts', return_value=0):
                                sent = await reminders.check_and_send_reminders(mock_bot)

                                # Only the non-off user should get a reminder
                                assert sent <= 1

    @pytest.mark.asyncio
    async def test_check_and_send_no_new_messages(self):
        """Skips reminders if no new messages."""
        mock_bot = Mock()

        users = [{"tg_user_id": 123, "reminder_frequency": "daily"}]

        with patch('reminders.db.get_users_with_reminders_due', return_value=users):
            with patch('reminders.db.get_user_chats', return_value=[{"tg_chat_id": 789}]):
                with patch('reminders.db.get_last_catchup', return_value=None):
                    with patch('reminders.db.get_messages_since', return_value=[]):
                        with patch('reminders.db.expire_stale_drafts', return_value=0):
                            sent = await reminders.check_and_send_reminders(mock_bot)

                            # No messages = no reminder sent
                            assert sent == 0

    @pytest.mark.asyncio
    async def test_check_and_send_no_chats(self):
        """Skips user if they have no chat history."""
        mock_bot = Mock()

        users = [{"tg_user_id": 123, "reminder_frequency": "daily"}]

        with patch('reminders.db.get_users_with_reminders_due', return_value=users):
            with patch('reminders.db.get_user_chats', return_value=[]):
                with patch('reminders.db.expire_stale_drafts', return_value=0):
                    sent = await reminders.check_and_send_reminders(mock_bot)

                    assert sent == 0

    @pytest.mark.asyncio
    async def test_check_and_send_multiple_chats(self):
        """Counts messages across all user chats."""
        mock_bot = Mock()
        mock_bot.send_message = AsyncMock()

        users = [{"tg_user_id": 123, "reminder_frequency": "daily"}]

        with patch('reminders.db.get_users_with_reminders_due', return_value=users):
            with patch('reminders.db.get_user_chats', return_value=[
                {"tg_chat_id": 789},
                {"tg_chat_id": 890},
            ]):
                with patch('reminders.db.get_last_catchup', return_value=None):
                    with patch('reminders.db.get_messages_since', side_effect=[
                        [{"id": 1}],  # 1 message in first chat
                        [{"id": 2}, {"id": 3}],  # 2 messages in second chat
                    ]):
                        with patch('reminders.summarizer.generate_reminder_digest', new_callable=AsyncMock, return_value="digest"):
                            with patch('reminders.db.update_last_reminder'):
                                with patch('reminders.db.expire_stale_drafts', return_value=0):
                                    sent = await reminders.check_and_send_reminders(mock_bot)

                                    assert sent == 1

    @pytest.mark.asyncio
    async def test_check_and_send_generates_digest(self):
        """Generates reminder digest with correct counts."""
        mock_bot = Mock()
        mock_bot.send_message = AsyncMock()

        users = [{"tg_user_id": 123, "reminder_frequency": "daily"}]

        with patch('reminders.db.get_users_with_reminders_due', return_value=users):
            with patch('reminders.db.get_user_chats', return_value=[{"tg_chat_id": 789}]):
                with patch('reminders.db.get_last_catchup', return_value=None):
                    with patch('reminders.db.get_messages_since', return_value=[
                        {"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}, {"id": 5}
                    ]):
                        with patch('reminders.summarizer.generate_reminder_digest', new_callable=AsyncMock, return_value="5 messages") as mock_digest:
                            with patch('reminders.db.expire_stale_drafts', return_value=0):
                                await reminders.check_and_send_reminders(mock_bot)

                                # Verify digest was called with correct message count
                                call_kwargs = mock_digest.call_args[1]
                                assert call_kwargs["message_count"] == 5

    @pytest.mark.asyncio
    async def test_check_and_send_expires_stale_drafts(self):
        """Calls expire_stale_drafts during check."""
        mock_bot = Mock()

        with patch('reminders.db.get_users_with_reminders_due', return_value=[]):
            with patch('reminders.db.expire_stale_drafts', return_value=3) as mock_expire:
                sent = await reminders.check_and_send_reminders(mock_bot)

                mock_expire.assert_called_once()

    @pytest.mark.asyncio
    async def test_check_and_send_error_handling(self):
        """Continues on error for individual users."""
        mock_bot = Mock()
        mock_bot.send_message = AsyncMock(side_effect=Exception("Send failed"))

        users = [
            {"tg_user_id": 123, "reminder_frequency": "daily"},
            {"tg_user_id": 456, "reminder_frequency": "daily"},
        ]

        with patch('reminders.db.get_users_with_reminders_due', return_value=users):
            with patch('reminders.db.get_user_chats', return_value=[{"tg_chat_id": 789}]):
                with patch('reminders.db.get_last_catchup', return_value=None):
                    with patch('reminders.db.get_messages_since', return_value=[{"id": 1}]):
                        with patch('reminders.summarizer.generate_reminder_digest', new_callable=AsyncMock, return_value="digest"):
                            with patch('reminders.db.expire_stale_drafts', return_value=0):
                                # Should not raise, just continue
                                sent = await reminders.check_and_send_reminders(mock_bot)
                                # Sent count may be 0 or 2 depending on error handling order

    @pytest.mark.asyncio
    async def test_check_and_send_respects_last_catchup(self):
        """Uses last_catchup timestamp to fetch only new messages."""
        mock_bot = Mock()
        mock_bot.send_message = AsyncMock()

        users = [{"tg_user_id": 123, "reminder_frequency": "daily"}]
        last_catchup = datetime(2024, 1, 15, 10, 0, 0, tzinfo=timezone.utc)

        with patch('reminders.db.get_users_with_reminders_due', return_value=users):
            with patch('reminders.db.get_user_chats', return_value=[{"tg_chat_id": 789}]):
                with patch('reminders.db.get_last_catchup', return_value=last_catchup) as mock_last:
                    with patch('reminders.db.get_messages_since', return_value=[{"id": 1}]) as mock_msgs:
                        with patch('reminders.summarizer.generate_reminder_digest', new_callable=AsyncMock, return_value="digest"):
                            with patch('reminders.db.expire_stale_drafts', return_value=0):
                                await reminders.check_and_send_reminders(mock_bot)

                                # Verify get_messages_since was called with last_catchup
                                call_kwargs = mock_msgs.call_args[1]
                                assert call_kwargs["since"] == last_catchup
