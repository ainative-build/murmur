"""Scheduled reminder logic — checks users with active reminders and sends digest DMs.

Called via POST /api/check-reminders (Cloud Scheduler in production).
"""

import logging
from datetime import datetime, timezone

from telegram import Bot

import db
import summarizer

logger = logging.getLogger(__name__)


async def check_and_send_reminders(bot: Bot) -> int:
    """Check all users with active reminders and send digest DMs. Returns count sent."""
    users = db.get_users_with_reminders_due()
    sent = 0

    for user in users:
        tg_user_id = user["tg_user_id"]
        frequency = user.get("reminder_frequency", "off")
        if frequency == "off":
            continue

        try:
            # Get user's groups
            chats = db.get_user_chats(tg_user_id)
            if not chats:
                continue

            total_new = 0
            all_topics = []

            for chat in chats:
                tg_chat_id = chat["tg_chat_id"]
                last_catchup = db.get_last_catchup(tg_user_id, tg_chat_id)
                messages = db.get_messages_since(tg_chat_id, since=last_catchup, limit=200)
                total_new += len(messages)

            if total_new == 0:
                continue

            # Generate brief digest
            digest = await summarizer.generate_reminder_digest(
                message_count=total_new,
                topic_names=[],  # v1: skip topic detection for reminders to save LLM cost
                stale_topics=[],
            )

            await bot.send_message(chat_id=tg_user_id, text=digest)
            sent += 1
            logger.info(f"Reminder sent to {tg_user_id}: {total_new} new messages")

        except Exception as e:
            logger.error(f"Failed to send reminder to {tg_user_id}: {e}")

    # Expire stale draft sessions while we're at it
    expired = db.expire_stale_drafts()
    if expired:
        logger.info(f"Expired {expired} stale draft sessions")

    return sent
