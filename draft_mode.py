"""Draft mode — multi-turn /draft conversation handler using Gemini 3.1 Pro.

One active session per user. Auto-expires after 24h inactivity.
/done saves final draft as personal note. /cancel discards.
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes, ConversationHandler

import db
import summarizer
import personal
from telegram_format import md_to_telegram_html

logger = logging.getLogger(__name__)

# ConversationHandler state
DRAFTING = 0


async def draft_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /draft <topic> — start a new draft session."""
    topic = " ".join(context.args) if context.args else ""
    if not topic:
        await update.message.reply_text("Usage: /draft &lt;topic&gt;", parse_mode="HTML")
        return ConversationHandler.END

    tg_user_id = update.effective_user.id
    logger.info(f"/draft '{topic}' from {tg_user_id}")

    # Check for existing active session
    existing = db.get_active_draft_session(tg_user_id)
    if existing:
        await update.message.reply_text(
            f"You already have an active draft on \"{existing['topic']}\".\n"
            "Use /done to finish it or /cancel to discard."
        )
        return DRAFTING

    # Gather context from user's groups
    chats = db.get_user_chats(tg_user_id)
    if not chats:
        await update.message.reply_text("I haven't seen you in any groups yet.")
        return ConversationHandler.END

    tg_chat_id = chats[0]["tg_chat_id"]

    await update.message.reply_text(f"⏳ Gathering context on \"{topic}\"...")

    # Gather relevant messages + personal sources
    messages = db.get_messages_by_keyword(tg_chat_id, topic, hours=72)
    msg_ids = [m["id"] for m in messages if m.get("has_links")]
    links = db.get_link_summaries_for_messages(msg_ids)

    # Build context snapshot
    msg_lines = [
        f"[{m.get('timestamp', '')[:16]} {m.get('username', '?')}]: {m.get('text', '')}"
        for m in messages[:100]
    ]
    link_lines = [
        f"[link: {ls.get('title', ls.get('url', ''))}]: {ls.get('summary', '')[:200]}"
        for ls in links[:10]
    ]
    context_text = "Team discussions:\n" + "\n".join(msg_lines)
    if link_lines:
        context_text += "\n\nShared links:\n" + "\n".join(link_lines)

    context_snapshot = {
        "topic": topic,
        "message_count": len(messages),
        "link_count": len(links),
        "context_text": context_text,
    }

    # Create session
    session_id = db.create_draft_session(tg_user_id, topic, context_snapshot)
    if not session_id:
        await update.message.reply_text("❌ Failed to start draft session. Try again.")
        return ConversationHandler.END

    # Store session ID in user_data for quick access
    context.user_data["draft_session_id"] = session_id
    context.user_data["draft_system_prompt"] = summarizer.build_draft_system_prompt(context_text)

    # Generate opening message
    opening = await summarizer.generate_draft_response(
        conversation_history=[{"role": "user", "content": f"I want to draft my position on: {topic}"}],
        system_prompt=context.user_data["draft_system_prompt"],
    )

    db.append_draft_message(session_id, "user", f"I want to draft my position on: {topic}")
    db.append_draft_message(session_id, "model", opening)

    await update.message.reply_text(
        f"📝 <b>Draft mode: {topic}</b>\n\n{opening}\n\n"
        "<i>Send messages to continue. /done to finish, /cancel to discard.</i>",
        parse_mode="HTML",
    )
    return DRAFTING


async def draft_continue_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle user messages during draft mode."""
    tg_user_id = update.effective_user.id
    user_msg = update.message.text

    session_id = context.user_data.get("draft_session_id")
    system_prompt = context.user_data.get("draft_system_prompt", "")

    if not session_id:
        # Try to recover from DB
        session = db.get_active_draft_session(tg_user_id)
        if not session:
            await update.message.reply_text("No active draft session. Use /draft <topic> to start.")
            return ConversationHandler.END
        session_id = session["id"]
        context.user_data["draft_session_id"] = session_id
        context_text = (session.get("context_snapshot") or {}).get("context_text", "")
        system_prompt = summarizer.build_draft_system_prompt(context_text)
        context.user_data["draft_system_prompt"] = system_prompt

    # Append user message
    db.append_draft_message(session_id, "user", user_msg)

    # Get full history for multi-turn
    session = db.get_active_draft_session(tg_user_id)
    history = (session.get("conversation_history") or []) if session else []

    # Generate response
    response = await summarizer.generate_draft_response(history, system_prompt)
    db.append_draft_message(session_id, "model", response)

    try:
        await update.message.reply_text(md_to_telegram_html(response), parse_mode="HTML")
    except Exception:
        await update.message.reply_text(response)
    return DRAFTING


async def draft_end_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /done — end draft session, offer to save as personal note."""
    tg_user_id = update.effective_user.id
    session_id = context.user_data.get("draft_session_id")

    if not session_id:
        session = db.get_active_draft_session(tg_user_id)
        session_id = session["id"] if session else None

    if not session_id:
        await update.message.reply_text("No active draft to finish.")
        return ConversationHandler.END

    # Get final session for summary
    session = db.get_active_draft_session(tg_user_id)
    history = (session.get("conversation_history") or []) if session else []
    topic = (session.get("topic") or "draft") if session else "draft"

    # Save the conversation as a personal note
    draft_content = "\n\n".join(
        f"{'You' if m['role'] == 'user' else 'Murmur'}: {m['content']}"
        for m in history
    )
    personal.handle_dm_note(tg_user_id, f"Draft: {topic}\n\n{draft_content}")

    db.end_draft_session(session_id)
    context.user_data.pop("draft_session_id", None)
    context.user_data.pop("draft_system_prompt", None)

    await update.message.reply_text(
        f"✅ Draft on \"{topic}\" saved to your personal notes.\n"
        "Use /sources to see it."
    )
    return ConversationHandler.END


async def draft_cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /cancel — discard draft session without saving."""
    tg_user_id = update.effective_user.id
    session_id = context.user_data.get("draft_session_id")

    if not session_id:
        session = db.get_active_draft_session(tg_user_id)
        session_id = session["id"] if session else None

    if session_id:
        db.cancel_draft_session(session_id)

    context.user_data.pop("draft_session_id", None)
    context.user_data.pop("draft_system_prompt", None)

    await update.message.reply_text("🗑 Draft discarded.")
    return ConversationHandler.END
