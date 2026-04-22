"""Telegram DM command handlers — /start, /catchup, /search, /note, /sources, /delete,
/topics, /topic, /decide, /remind, /export, /kb."""

import logging
import re
import html

from telegram import Update
from telegram.ext import ContextTypes

import config
import db
import summarizer
from telegram_format import md_to_telegram_html
import personal

logger = logging.getLogger(__name__)

MAX_MSG_LEN = 4096
URL_REGEX = r"(https?:\/\/[^\s]+)"


async def _send_long(update: Update, text: str, parse_mode: str | None = "HTML") -> None:
    """Send a long message, chunking if needed. Falls back to plain text on parse failure."""
    for i in range(0, len(text), MAX_MSG_LEN):
        chunk = text[i:i + MAX_MSG_LEN]
        try:
            await update.message.reply_text(chunk, parse_mode=parse_mode)
        except Exception:
            await update.message.reply_text(chunk)


async def _send_llm_response(update: Update, text: str) -> None:
    """Send an LLM response, converting markdown to Telegram HTML."""
    formatted = md_to_telegram_html(text)
    await _send_long(update, formatted, parse_mode="HTML")


# ---------------------------------------------------------------------------
# /start
# ---------------------------------------------------------------------------

COMMAND_LIST = """
<b>Available Commands</b> (use in DM):

/start — Welcome and help
/catchup — Get digest of recent discussions
/search &lt;keyword&gt; — Search messages and links
/topics — List active discussion threads
/topic &lt;name&gt; — Deep dive on a specific topic
/decide &lt;topic&gt; — Structured decision view on a topic
/note &lt;text&gt; — Save a personal note
/sources — List your personal sources
/delete &lt;id&gt; — Remove a personal source
/remind &lt;off|daily|weekly&gt; — Set reminder frequency
/export — Export topics to NotebookLM
/kb — Link to team knowledge base
/feedback &lt;text&gt; — Send feedback to improve Murmur
"""


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start — welcome message with command list."""
    user = update.effective_user
    logger.info(f"/start from user {user.id} ({user.username})")
    welcome = (
        f"Hey {user.first_name}! I'm <b>Murmur</b> — your team's silent listener.\n\n"
        "I capture group discussions, summarize shared links, "
        "and help you catch up, search, and brainstorm via DM.\n"
        f"{COMMAND_LIST}"
    )
    await update.message.reply_text(welcome, parse_mode="HTML")


# ---------------------------------------------------------------------------
# /catchup — Phase 2
# ---------------------------------------------------------------------------

async def catchup_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /catchup — digest of messages since last check-in."""
    user = update.effective_user
    tg_user_id = user.id
    logger.info(f"/catchup from {tg_user_id}")

    # Get user's groups
    chats = db.get_user_chats(tg_user_id)
    if not chats:
        await update.message.reply_text(
            "I haven't seen you in any groups yet. Add me to a group first!"
        )
        return

    # If multiple groups, check if user specified one
    args = context.args
    tg_chat_id = None

    if len(chats) == 1:
        tg_chat_id = chats[0]["tg_chat_id"]
    elif args:
        # Try to match arg to a chat ID
        try:
            tg_chat_id = int(args[0])
            if not any(c["tg_chat_id"] == tg_chat_id for c in chats):
                tg_chat_id = None
        except ValueError:
            tg_chat_id = None

    if tg_chat_id is None and len(chats) > 1:
        chat_list = "\n".join(f"• <code>{c['tg_chat_id']}</code>" for c in chats)
        await update.message.reply_text(
            f"You're in multiple groups. Specify which one:\n\n"
            f"/catchup &lt;chat_id&gt;\n\n{chat_list}",
            parse_mode="HTML",
        )
        return

    await update.message.reply_text("⏳ Generating catch-up digest...")

    # Get messages since last catchup
    last_catchup = db.get_last_catchup(tg_user_id, tg_chat_id)
    messages = db.get_messages_since(tg_chat_id, since=last_catchup)

    if not messages:
        await update.message.reply_text("No new messages since your last catch-up! 🎉")
        db.update_last_catchup(tg_user_id, tg_chat_id)
        return

    # Get link summaries for messages with links
    msg_ids_with_links = [m["id"] for m in messages if m.get("has_links")]
    link_summaries = db.get_link_summaries_for_messages(msg_ids_with_links)

    # Generate digest via Gemini
    digest = await summarizer.generate_catchup(messages, link_summaries)

    header = f"📋 <b>Catch-up</b> ({len(messages)} messages"
    if link_summaries:
        header += f", {len(link_summaries)} links"
    header += ")\n\n"

    await _send_long(update, header + md_to_telegram_html(digest), parse_mode="HTML")
    db.update_last_catchup(tg_user_id, tg_chat_id)


# ---------------------------------------------------------------------------
# /search — Phase 2
# ---------------------------------------------------------------------------

async def search_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /search <keyword> — full-text search across group + personal."""
    user = update.effective_user
    query = " ".join(context.args) if context.args else ""
    if not query:
        await update.message.reply_text("Usage: /search &lt;keyword&gt;", parse_mode="HTML")
        return

    logger.info(f"/search '{query}' from {user.id}")
    results = db.search_all(user.id, query)

    if not results:
        await update.message.reply_text(f"No results for \"{html.escape(query)}\".", parse_mode="HTML")
        return

    lines = [f"🔍 <b>Search results for \"{html.escape(query)}\"</b>\n"]
    for r in results[:15]:  # cap display at 15
        origin_tag = f"[{r['origin'].upper()}]"
        if r["type"] == "message":
            user_name = r.get("username", "?")
            text_preview = (r.get("text", "")[:100] + "...") if len(r.get("text", "")) > 100 else r.get("text", "")
            lines.append(f"{origin_tag} <b>{html.escape(user_name)}</b>: {html.escape(text_preview)}")
        elif r["type"] == "link":
            title = r.get("title") or r.get("url", "link")
            lines.append(f"{origin_tag} 🔗 {html.escape(title[:80])}")
        else:
            content = r.get("content", r.get("title", ""))[:80]
            lines.append(f"{origin_tag} 📝 {html.escape(content)}")

    await _send_long(update, "\n".join(lines))


# ---------------------------------------------------------------------------
# /note, /sources, /delete — Phase 2
# ---------------------------------------------------------------------------

async def note_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /note <text> — save a personal note."""
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Usage: /note &lt;text&gt;", parse_mode="HTML")
        return

    source_id = personal.handle_dm_note(update.effective_user.id, text)
    if source_id:
        await update.message.reply_text(f"✅ Note saved (#{source_id})")
    else:
        await update.message.reply_text("❌ Failed to save note. Try again.")


async def sources_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /sources — list personal sources count and recent entries."""
    tg_user_id = update.effective_user.id
    count = db.get_personal_sources_count(tg_user_id)
    recent = db.get_personal_sources(tg_user_id, limit=5)

    if count == 0:
        await update.message.reply_text(
            "No personal sources yet.\n\n"
            "DM me a link, forward a message, or use /note to save something."
        )
        return

    lines = [f"📚 <b>Personal Sources</b> ({count} total)\n\nRecent:"]
    for s in recent:
        type_icon = {"link": "🔗", "note": "📝", "forwarded_message": "↩️"}.get(s["source_type"], "📄")
        label = s.get("title") or s.get("url") or (s.get("content", "")[:50] + "...")
        lines.append(f"{type_icon} #{s['id']} — {html.escape(str(label)[:60])}")

    lines.append("\nUse /delete &lt;id&gt; to remove an entry.")
    await _send_long(update, "\n".join(lines))


async def delete_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /delete <id> — remove a personal source with ownership check."""
    if not context.args:
        await update.message.reply_text("Usage: /delete &lt;id&gt;", parse_mode="HTML")
        return

    try:
        source_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid ID. Use /sources to see your entries.")
        return

    success = db.delete_personal_source(update.effective_user.id, source_id)
    if success:
        await update.message.reply_text(f"✅ Source #{source_id} deleted.")
    else:
        await update.message.reply_text(f"❌ Source #{source_id} not found or not yours.")


# ---------------------------------------------------------------------------
# DM voice handler — voice/audio → transcribe → save as personal source
# ---------------------------------------------------------------------------

async def dm_voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice/audio DMs — transcribe and save as personal source."""
    message = update.effective_message
    if not message:
        return

    tg_user_id = update.effective_user.id
    voice = message.voice or message.audio
    if not voice:
        return

    await message.reply_text("⏳ Transcribing voice message...")

    try:
        from tools.voice_transcriber import transcribe_audio

        file = await context.bot.get_file(voice.file_id)
        audio_bytes = await file.download_as_bytearray()
        mime_type = voice.mime_type or "audio/ogg"

        transcript = await transcribe_audio(bytes(audio_bytes), mime_type=mime_type)
        if transcript:
            source_id = personal.handle_dm_voice(tg_user_id, transcript)
            if source_id:
                preview = transcript[:100] + ("..." if len(transcript) > 100 else "")
                await message.reply_text(
                    f"✅ Voice message saved (#{source_id})\n\n<i>{html.escape(preview)}</i>",
                    parse_mode="HTML",
                )
            else:
                await message.reply_text("❌ Failed to save voice message. Try again.")
        else:
            await message.reply_text("⚠️ Couldn't transcribe this voice message.")
    except Exception as e:
        logger.error(f"DM voice handler failed: {e}")
        await message.reply_text("❌ Voice transcription failed. Try again.")


# ---------------------------------------------------------------------------
# DM document handler — extract text → save as personal source
# ---------------------------------------------------------------------------

async def dm_document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle document DMs — extract text and save as personal source."""
    message = update.effective_message
    if not message or not message.document:
        return

    tg_user_id = update.effective_user.id
    doc = message.document
    filename = doc.file_name or "unknown"

    try:
        from tools.file_extractor import extract_file_text, MAX_FILE_SIZE

        if doc.file_size and doc.file_size > MAX_FILE_SIZE:
            await message.reply_text(f"⚠️ File too large (max 5MB): {html.escape(filename)}", parse_mode="HTML")
            return

        await message.reply_text(f"⏳ Processing {html.escape(filename)}...", parse_mode="HTML")

        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()

        text = extract_file_text(bytes(file_bytes), filename, doc.mime_type)
        if text:
            source_id = personal.handle_dm_file(tg_user_id, filename, text)
            if source_id:
                await message.reply_text(
                    f"✅ File saved (#{source_id}): {html.escape(filename)} ({len(text)} chars extracted)",
                    parse_mode="HTML",
                )
            else:
                await message.reply_text("❌ Failed to save file. Try again.")
        else:
            await message.reply_text(
                f"⚠️ Couldn't extract text from {html.escape(filename)}. "
                "Supported: PDF, DOCX, TXT, MD.",
                parse_mode="HTML",
            )
    except Exception as e:
        logger.error(f"DM document handler failed: {e}")
        await message.reply_text("❌ File processing failed. Try again.")


# ---------------------------------------------------------------------------
# DM message handler (non-command) — Phase 2
# ---------------------------------------------------------------------------

async def dm_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle non-command DMs — detect links, forwards, or prompt for /note."""
    message = update.effective_message
    if not message or not message.text:
        return

    tg_user_id = update.effective_user.id
    text = message.text

    # Check for forwarded message
    if message.forward_origin:
        forwarded_from = None
        if hasattr(message.forward_origin, "sender_user") and message.forward_origin.sender_user:
            forwarded_from = message.forward_origin.sender_user.username
        source_id = personal.handle_dm_forward(tg_user_id, text, forwarded_from)
        if source_id:
            await message.reply_text(f"✅ Forwarded message saved (#{source_id})")
        else:
            await message.reply_text("❌ Failed to save. Try again.")
        return

    # Check for links — extract + show summary (don't auto-save)
    urls = personal.detect_urls(text)
    if urls:
        await message.reply_text("⏳ Processing link...")
        summary = await personal.extract_link_summary(urls[0], text)
        if summary:
            await _send_llm_response(update, summary)
        else:
            await message.reply_text("⚠️ Couldn't extract content from this link.")
        return

    # Plain text — prompt for /note
    await message.reply_text(
        "To save this as a personal note, use:\n/note " + html.escape(text[:50]) + "..."
        if len(text) > 50 else
        "To save this as a personal note, use:\n/note " + html.escape(text)
    )


# ---------------------------------------------------------------------------
# /topics — Phase 3
# ---------------------------------------------------------------------------

async def topics_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /topics — list active discussion threads."""
    tg_user_id = update.effective_user.id
    chats = db.get_user_chats(tg_user_id)
    if not chats:
        await update.message.reply_text("I haven't seen you in any groups yet.")
        return

    # Use first chat (v1 simplification for single-group)
    tg_chat_id = chats[0]["tg_chat_id"]

    await update.message.reply_text("⏳ Analyzing recent discussions...")

    messages = db.get_recent_messages(tg_chat_id, hours=48)
    if not messages:
        await update.message.reply_text("No messages in the last 48 hours.")
        return

    topics = await summarizer.generate_topics(messages)
    if not topics:
        await update.message.reply_text("Couldn't identify distinct topics. Try again later.")
        return

    lines = [f"📊 <b>Active Topics</b> (last 48h)\n"]
    for i, t in enumerate(topics, 1):
        name = html.escape(t.get("name", f"Topic {i}"))
        desc = html.escape(t.get("description", ""))
        participants = ", ".join(t.get("participants", []))
        lines.append(f"<b>{i}. {name}</b>\n   {desc}")
        if participants:
            lines.append(f"   👥 {html.escape(participants)}")
        lines.append("")

    lines.append("Use /topic &lt;name&gt; to dive deeper into a topic.")
    await _send_long(update, "\n".join(lines))


# ---------------------------------------------------------------------------
# /topic <name> — Phase 3
# ---------------------------------------------------------------------------

async def topic_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /topic <name> — deep dive on a specific topic."""
    topic_name = " ".join(context.args) if context.args else ""
    if not topic_name:
        await update.message.reply_text("Usage: /topic &lt;name&gt;", parse_mode="HTML")
        return

    tg_user_id = update.effective_user.id
    chats = db.get_user_chats(tg_user_id)
    if not chats:
        await update.message.reply_text("I haven't seen you in any groups yet.")
        return

    tg_chat_id = chats[0]["tg_chat_id"]
    await update.message.reply_text(f"⏳ Analyzing \"{html.escape(topic_name)}\"...", parse_mode="HTML")

    messages = db.get_messages_by_keyword(tg_chat_id, topic_name)
    if not messages:
        await update.message.reply_text(f"No messages found about \"{html.escape(topic_name)}\".", parse_mode="HTML")
        return

    msg_ids = [m["id"] for m in messages if m.get("has_links")]
    links = db.get_link_summaries_for_messages(msg_ids)

    detail = await summarizer.generate_topic_detail(messages, links, topic_name)
    header = f"🔎 <b>Topic: {html.escape(topic_name)}</b>\n\n"
    await _send_long(update, header + md_to_telegram_html(detail), parse_mode="HTML")


# ---------------------------------------------------------------------------
# /decide <topic> — Phase 3
# ---------------------------------------------------------------------------

async def decide_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /decide <topic> — structured decision view."""
    topic = " ".join(context.args) if context.args else ""
    if not topic:
        await update.message.reply_text("Usage: /decide &lt;topic&gt;", parse_mode="HTML")
        return

    tg_user_id = update.effective_user.id
    chats = db.get_user_chats(tg_user_id)
    if not chats:
        await update.message.reply_text("I haven't seen you in any groups yet.")
        return

    tg_chat_id = chats[0]["tg_chat_id"]
    await update.message.reply_text(f"⏳ Building decision view for \"{html.escape(topic)}\"...", parse_mode="HTML")

    messages = db.get_messages_by_keyword(tg_chat_id, topic)
    if not messages:
        await update.message.reply_text(f"No discussion found about \"{html.escape(topic)}\".", parse_mode="HTML")
        return

    msg_ids = [m["id"] for m in messages if m.get("has_links")]
    links = db.get_link_summaries_for_messages(msg_ids)

    view = await summarizer.generate_decision_view(messages, links, topic)
    header = f"⚖️ <b>Decision: {html.escape(topic)}</b>\n\n"
    await _send_long(update, header + md_to_telegram_html(view), parse_mode="HTML")


# ---------------------------------------------------------------------------
# /remind — Phase 4
# ---------------------------------------------------------------------------

async def remind_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /remind <off|daily|weekly> — set reminder frequency."""
    valid = {"off", "daily", "weekly"}
    freq = context.args[0].lower() if context.args else ""
    if freq not in valid:
        await update.message.reply_text(
            "Usage: /remind &lt;off|daily|weekly&gt;", parse_mode="HTML"
        )
        return

    db.update_user_reminder(update.effective_user.id, freq)
    if freq == "off":
        await update.message.reply_text("🔕 Reminders turned off.")
    else:
        await update.message.reply_text(f"🔔 Reminders set to <b>{freq}</b>.", parse_mode="HTML")


# ---------------------------------------------------------------------------
# /export, /kb — Phase 4
# ---------------------------------------------------------------------------

async def export_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /export — generate topic markdown files and send them in chat."""
    tg_user_id = update.effective_user.id
    chats = db.get_user_chats(tg_user_id)
    if not chats:
        await update.message.reply_text("I haven't seen you in any groups yet.")
        return

    await update.message.reply_text("⏳ Generating topic exports...")

    try:
        import io
        from export_formatter import format_topic_document, content_hash

        tg_chat_id = chats[0]["tg_chat_id"]
        messages = db.get_recent_messages(tg_chat_id, hours=48)
        if not messages:
            await update.message.reply_text("No messages in the last 48 hours to export.")
            return

        topics = await summarizer.generate_topics(messages)
        if not topics:
            await update.message.reply_text("Couldn't identify topics to export.")
            return

        sent = 0
        for topic_data in topics:
            topic_name = topic_data.get("name", "Untitled")
            topic_messages = db.get_messages_by_keyword(tg_chat_id, topic_name, hours=72)
            if not topic_messages:
                topic_messages = messages

            msg_ids = [m["id"] for m in topic_messages if m.get("has_links")]
            links = db.get_link_summaries_for_messages(msg_ids)

            doc = format_topic_document(
                topic=topic_name,
                messages=topic_messages,
                links=links,
                summary=topic_data.get("description", ""),
            )

            # Send as .md file in chat
            safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in topic_name)
            file_bytes = io.BytesIO(doc.encode("utf-8"))
            file_bytes.name = f"{safe_name}.md"
            await update.message.reply_document(document=file_bytes, filename=f"{safe_name}.md")
            sent += 1

        await update.message.reply_text(f"✅ Exported {sent} topic(s) as markdown files.")

    except Exception as e:
        logger.error(f"Export failed: {e}")
        await update.message.reply_text(f"❌ Export failed: {e}")


async def kb_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /kb — link to NotebookLM notebook."""
    notebook_id = config.NOTEBOOKLM_NOTEBOOK_ID
    if notebook_id:
        await update.message.reply_text(
            f"📚 Team Knowledge Base:\nhttps://notebooklm.google.com/notebook/{notebook_id}"
        )
    else:
        await update.message.reply_text("⚠️ NotebookLM notebook not configured yet.")


# ---------------------------------------------------------------------------
# /feedback — collect user feedback
# ---------------------------------------------------------------------------

async def feedback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /feedback <text> — collect user feedback for product iteration."""
    text = " ".join(context.args) if context.args else ""
    if not text:
        await update.message.reply_text("Usage: /feedback &lt;your feedback&gt;", parse_mode="HTML")
        return

    user = update.effective_user
    feedback_id = db.store_feedback(user.id, user.username, text)
    if feedback_id:
        await update.message.reply_text("🙏 Thanks for your feedback! We'll use it to improve Murmur.")
    else:
        await update.message.reply_text("❌ Failed to save feedback. Please try again.")
