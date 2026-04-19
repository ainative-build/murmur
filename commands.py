"""Telegram DM command handlers."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

logger = logging.getLogger(__name__)

# All planned commands listed here for /start welcome message
COMMAND_LIST = """
<b>Available Commands</b> (use in DM):

/start — Welcome and help
/catchup — Get digest of recent discussions
/search &lt;keyword&gt; — Search messages and links
/topics — List active discussion threads
/topic &lt;name&gt; — Deep dive on a specific topic
/draft &lt;topic&gt; — Brainstorm with AI using team context
/decide &lt;topic&gt; — Structured decision view on a topic

<i>Coming soon: /note, /sources, /remind, /export</i>
"""


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command — welcome message with command list."""
    user = update.effective_user
    logger.info(f"/start from user {user.id} ({user.username})")

    welcome = (
        f"Hey {user.first_name}! I'm <b>Murmur</b> — your team's silent listener.\n\n"
        "I capture group discussions, summarize shared links, "
        "and help you catch up, search, and brainstorm via DM.\n"
        f"{COMMAND_LIST}"
    )
    await update.message.reply_text(welcome, parse_mode="HTML")
