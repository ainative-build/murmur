"""Murmur Bot — Telegram bot with group message capture, link summarization, and DM commands.

FastAPI + python-telegram-bot v21+. Supports webhook (production) and polling (local dev).
"""

import logging
import asyncio
import re
import html
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, Request, Response, HTTPException, Header
import uvicorn

from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler,
    filters, ContextTypes,
)
from telegram.constants import ParseMode

import config
import db
from agent import run_agent
from telegram_format import md_to_telegram_html
from commands import (
    start_handler, catchup_handler, search_handler,
    note_handler, sources_handler, delete_handler, dm_message_handler,
    dm_voice_handler, dm_document_handler,
    topics_handler, topic_handler, decide_handler,
    remind_handler, export_handler, kb_handler, feedback_handler,
)
# draft_mode disabled for now — ConversationHandler UX needs refinement

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- Constants ---
URL_REGEX = r"(https?:\/\/[^\s]+)"
MAX_TELEGRAM_MSG_LEN = 4096

# PTB app constructed lazily in lifespan, not at import time
ptb_app: Optional[Application] = None

# Dedup: track message IDs currently being processed to prevent webhook retry duplicates.
# Telegram retries webhooks if response is slow (>~30s), causing double processing.
_processing_messages: set[tuple[int, int]] = set()  # (tg_chat_id, tg_msg_id)


def _register_handlers(app: Application) -> None:
    """Register all handlers on a PTB Application. Single source of truth."""
    # DM commands (private chat only)
    private = filters.ChatType.PRIVATE
    app.add_handler(CommandHandler("start", start_handler, filters=private))
    app.add_handler(CommandHandler("catchup", catchup_handler, filters=private))
    app.add_handler(CommandHandler("search", search_handler, filters=private))
    app.add_handler(CommandHandler("note", note_handler, filters=private))
    app.add_handler(CommandHandler("sources", sources_handler, filters=private))
    app.add_handler(CommandHandler("delete", delete_handler, filters=private))
    app.add_handler(CommandHandler("topics", topics_handler, filters=private))
    app.add_handler(CommandHandler("topic", topic_handler, filters=private))
    app.add_handler(CommandHandler("decide", decide_handler, filters=private))
    app.add_handler(CommandHandler("remind", remind_handler, filters=private))
    app.add_handler(CommandHandler("export", export_handler, filters=private))
    app.add_handler(CommandHandler("kb", kb_handler, filters=private))
    app.add_handler(CommandHandler("feedback", feedback_handler, filters=private))

    # DM non-command messages — links, forwards, plain text.
    app.add_handler(MessageHandler(
        filters.TEXT & (~filters.COMMAND) & private,
        dm_message_handler,
    ))

    # DM voice/audio messages — transcribe and save as personal source.
    app.add_handler(MessageHandler(
        (filters.VOICE | filters.AUDIO) & private,
        dm_voice_handler,
    ))

    # DM document attachments — extract text and save as personal source.
    app.add_handler(MessageHandler(
        filters.Document.ALL & private,
        dm_document_handler,
    ))

    # Group messages: capture ALL text + photos + documents + voice for history.
    # group=1 runs alongside command handlers in group 0.
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL
             | filters.VOICE | filters.AUDIO) & filters.ChatType.GROUPS,
            group_message_handler,
        ),
        group=1,
    )


# --- Handlers ---

async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture ALL group messages (text + photos + docs + voice) into Supabase."""
    message = update.effective_message
    if not message:
        return

    tg_user_id = message.from_user.id if message.from_user else 0
    # Use username if available, otherwise fall back to first_name (e.g. "Alice")
    username = (
        message.from_user.username
        or message.from_user.first_name
        if message.from_user else None
    )
    tg_chat_id = message.chat_id
    tg_msg_id = message.message_id
    timestamp = message.date or datetime.now(timezone.utc)

    # In-memory dedup: skip concurrent retries within this process.
    msg_key = (tg_chat_id, tg_msg_id)
    if msg_key in _processing_messages:
        logger.debug(f"Skipping duplicate webhook for msg {tg_msg_id} in chat {tg_chat_id}")
        return
    _processing_messages.add(msg_key)

    try:
        # Get text — could be message.text or message.caption (for photos/docs)
        text = message.text or message.caption or ""
        media_type = None
        source_filename = None
        file_text = None

        # Check message content types
        has_photo = bool(message.photo)
        has_voice = bool(message.voice or message.audio)
        has_document = bool(message.document)

        # Voice/audio messages — transcribe with Gemini (stored silently, no reply)
        if has_voice:
            transcript = await _transcribe_voice(message, context)
            if transcript:
                text = f"[Voice: {transcript}]" + (f"\n{text}" if text else "")
            media_type = "voice" if message.voice else "audio"

        # Photo — analyze with Gemini vision
        elif has_photo:
            description = await _analyze_image(message, context)
            if description:
                text = f"[Image: {description}]" + (f"\n{text}" if text else "")
            media_type = "photo"

        # Document — extract text if supported type
        elif has_document:
            file_text, filename = await _extract_document_text(message, context)
            source_filename = filename
            if file_text:
                text = f"[File: {filename}]\n{file_text}" + (f"\n{text}" if text else "")
                media_type = "file"

        if not text:
            return  # Nothing to store

        urls = re.findall(URL_REGEX, text)
        has_links = len(urls) > 0

        # Atomic claim: store_message uses INSERT ... ON CONFLICT DO NOTHING,
        # so concurrent webhook retries across container instances all converge
        # on a single winning insert. The winner gets a non-None id; losers get
        # None. This replaces the racy SELECT-then-INSERT pattern.
        message_id = db.store_message(
            tg_msg_id=tg_msg_id,
            tg_chat_id=tg_chat_id,
            tg_user_id=tg_user_id,
            username=username,
            text=text,
            timestamp=timestamp,
            has_links=has_links,
            reply_to_tg_msg_id=message.reply_to_message.message_id if message.reply_to_message else None,
            forwarded_from=message.forward_origin.sender_user.username if (
                message.forward_origin and hasattr(message.forward_origin, "sender_user") and message.forward_origin.sender_user
            ) else None,
            media_type=media_type,
            source_filename=source_filename,
        )

        if message_id is None:
            # No id from atomic insert: either a duplicate webhook retry or a
            # transient DB error. Disambiguate via lookup.
            existing_id = db.get_message_id(tg_chat_id, tg_msg_id)
            if existing_id is None:
                # Row doesn't exist → DB write actually failed. Proceed best-effort
                # (rare; may produce a duplicate if the original eventually succeeds,
                # but losing a summary entirely is worse).
                logger.warning(
                    f"store_message failed and no row exists for msg {tg_msg_id} — "
                    "proceeding best-effort"
                )
            else:
                # Duplicate webhook. The "summary delivered" signal is the existence
                # of a link_summary row, which is written ONLY after a reply chunk
                # is successfully sent. So:
                #   - has_links + has_link_summary  → already delivered → skip
                #   - has_links + no link_summary   → prior attempt died before
                #                                     delivery → retry
                #   - no has_links                  → media-only message; nothing
                #                                     user-visible to retry → skip
                if not has_links:
                    logger.info(
                        f"Skipping retry of duplicate msg {tg_msg_id} (no links to redeliver)"
                    )
                    return
                if db.has_link_summary(existing_id):
                    logger.info(
                        f"Skipping retry of msg {tg_msg_id}: link summary already delivered"
                    )
                    return
                logger.info(
                    f"Retrying msg {tg_msg_id}: prior attempt left no delivered summary"
                )
                message_id = existing_id

        db.upsert_user(tg_user_id, username)
        db.ensure_user_chat_state(tg_user_id, tg_chat_id)

        if has_links:
            await _process_links_and_store(message, text, urls, message_id)

        # Auto-summarize file attachments (not voice — voice is silent)
        # Only if extracted text is 1K+ chars (already truncated to 10K by file_extractor)
        if media_type == "file" and file_text and len(file_text) >= 1000:
            await _summarize_and_reply_file(message, file_text, source_filename)
    finally:
        # Clean up dedup set (allow reprocessing if message is sent again later)
        _processing_messages.discard(msg_key)


def _handle_spotify_link(url: str) -> str:
    """Extract Spotify metadata via Web API (podcast-focused) with oEmbed fallback."""
    from tools.spotify_scraper import get_spotify_metadata

    metadata = get_spotify_metadata(url)
    if not metadata:
        return "Error: Could not extract Spotify metadata."

    title = metadata.get("title", "Unknown")
    desc = metadata.get("description", "")
    content_type = metadata.get("type", "unknown")
    show_name = metadata.get("show_name", "")

    if content_type == "episode" and desc:
        formatted = f"# 🎙️ {title}\n\n"
        if show_name:
            formatted += f"**Show:** {show_name}\n\n"
        formatted += f"## Description\n{desc}"
        return formatted
    elif content_type == "show" and desc:
        return f"# 🎙️ {title}\n\n## About\n{desc}"
    elif title:
        return f"# 🎵 {title}\n\nSpotify {content_type}"
    else:
        return "Error: Spotify link detected but couldn't extract details."


async def _handle_grok_link(url: str) -> str:
    """Extract Grok conversation via TinyFish and summarize with BAML.

    Grok share links are JS-heavy — TinyFish is the only working extractor.
    """
    from tools.tinyfish_fetcher import fetch_url_content
    from baml_client import b
    from baml_client.types import ContentType

    content = await fetch_url_content(url)
    logger.info(f"Grok TinyFish result: {len(content) if content else 0} chars")
    if not content or len(content) < 100:
        return "Error: Could not extract content from Grok link."

    try:
        summary_result = b.SummarizeContent(
            content=content,
            content_type=ContentType.Webpage,
            context=f"Grok AI conversation from {url}",
        )
        title = getattr(summary_result, "title", "Grok Conversation")
        key_points = getattr(summary_result, "key_points", [])
        concise_summary = getattr(summary_result, "concise_summary", "")

        formatted = f"# {title}\n\n"
        if key_points:
            formatted += "## Key Points:\n"
            for point in key_points:
                formatted += f"- {point}\n"
            formatted += "\n"
        formatted += f"## Summary:\n{concise_summary}"
        return formatted
    except Exception as e:
        logger.error(f"Grok summarization failed: {e}")
        return f"Error: Failed to summarize Grok conversation: {e}"


async def _process_links_and_store(
    message, text: str, urls: list[str], message_id: Optional[int]
) -> None:
    """Run agent pipeline on link message, reply with summary, store in link_summaries.

    Grok links are handled pre-agent via TinyFish (no BAML route exists for Grok).
    """
    try:
        url = urls[0]
        link_type = _detect_link_type(url)

        logger.info(f"Processing link: type={link_type}, url={url[:80]}")

        # Grok links: TinyFish pre-agent (no BAML route for Grok)
        if link_type == "grok":
            agent_result = await _handle_grok_link(url)
        # Spotify links: Web API pre-agent (no BAML route for Spotify)
        elif link_type == "spotify":
            agent_result = _handle_spotify_link(url)
        else:
            agent_result = await run_agent(text)

        if isinstance(agent_result, str) and not agent_result.startswith("Error:"):
            title = None
            lines = agent_result.strip().split("\n")
            if lines and lines[0].startswith("#"):
                title = lines[0].lstrip("#").strip()

            # Send reply chunks first; defer link_summary persistence until at least
            # one chunk is delivered. This makes link_summary the "fully delivered"
            # signal for cross-instance webhook-retry dedup — if the reply never
            # lands, no signal is written, so a future retry can re-attempt.
            formatted = md_to_telegram_html(agent_result)
            sent_msgs = []
            for i in range(0, len(formatted), MAX_TELEGRAM_MSG_LEN):
                chunk = formatted[i:i + MAX_TELEGRAM_MSG_LEN]
                try:
                    sent = await message.reply_text(chunk, parse_mode=ParseMode.HTML)
                    sent_msgs.append(sent)
                except Exception:
                    # Fallback to plain text if HTML parsing fails
                    try:
                        raw_chunk = agent_result[i:i + MAX_TELEGRAM_MSG_LEN]
                        sent = await message.reply_text(raw_chunk)
                        sent_msgs.append(sent)
                    except Exception as e:
                        logger.error(f"Failed to send chunk: {e}")
                        break
                if i + MAX_TELEGRAM_MSG_LEN < len(formatted):
                    await asyncio.sleep(0.5)

            if message_id and sent_msgs:
                db.store_link_summary(
                    message_id=message_id,
                    url=url,
                    link_type=link_type,
                    title=title,
                    summary=agent_result,
                )

            # Schedule deletion after 1 hour via Supabase (survives container restarts)
            if sent_msgs:
                from datetime import timedelta
                delete_after = datetime.now(timezone.utc) + timedelta(hours=24)
                for sent in sent_msgs:
                    db.schedule_message_deletion(sent.chat_id, sent.message_id, delete_after)
        elif isinstance(agent_result, str):
            logger.warning(f"Agent failed for {url[:60]}: {agent_result[:100]}")
            # Skip TinyFish for YouTube — it returns rendered page chrome
            # (footer, nav, "About/Press/Copyright") instead of video content.
            # Better to fail clearly than summarize the YouTube site footer.
            if link_type == "youtube":
                await message.reply_text(
                    "⚠️ Couldn't extract content from this YouTube video "
                    "(no transcript available)."
                )
                return
            # TinyFish fallback — try extracting content directly
            from tools.tinyfish_fetcher import fetch_url_content
            tf_content = await fetch_url_content(url)
            if tf_content and len(tf_content) > 100:
                try:
                    from baml_client import b as baml_b
                    from baml_client.types import ContentType as CT
                    sr = baml_b.SummarizeContent(content=tf_content, content_type=CT.Webpage, context=f"Content from {url}")
                    fallback_title = getattr(sr, "title", "Summary")
                    kp = getattr(sr, "key_points", [])
                    cs = getattr(sr, "concise_summary", "")
                    fallback_summary = f"# {fallback_title}\n\n"
                    if kp:
                        fallback_summary += "## Key Points:\n" + "".join(f"- {p}\n" for p in kp) + "\n"
                    fallback_summary += f"## Summary:\n{cs}"
                    # Send reply first; persist link_summary only after delivery
                    # so retries with no summary signal can re-attempt.
                    formatted = md_to_telegram_html(fallback_summary)
                    sent_msgs = []
                    for i in range(0, len(formatted), MAX_TELEGRAM_MSG_LEN):
                        chunk = formatted[i:i + MAX_TELEGRAM_MSG_LEN]
                        try:
                            sent = await message.reply_text(chunk, parse_mode=ParseMode.HTML)
                            sent_msgs.append(sent)
                        except Exception:
                            await message.reply_text(fallback_summary[i:i + MAX_TELEGRAM_MSG_LEN])
                    if message_id and sent_msgs:
                        db.store_link_summary(message_id=message_id, url=url, link_type=link_type, title=fallback_title, summary=fallback_summary)
                    if sent_msgs:
                        from datetime import timedelta
                        delete_after = datetime.now(timezone.utc) + timedelta(hours=24)
                        for sent in sent_msgs:
                            db.schedule_message_deletion(sent.chat_id, sent.message_id, delete_after)
                    logger.info(f"TinyFish fallback succeeded for {url[:60]}")
                except Exception as tf_err:
                    logger.error(f"TinyFish fallback summarization failed: {tf_err}")
                    await message.reply_text("⚠️ Couldn't extract content from this link.")
            else:
                await message.reply_text("⚠️ Couldn't extract content from this link.")
        else:
            logger.error(f"Agent returned {type(agent_result)} for {urls[0]}")

    except Exception as e:
        logger.error(f"Error processing links: {e}", exc_info=True)


async def _analyze_image(message, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Download a photo from Telegram and analyze it with Gemini 3 vision.

    Returns a brief text description or None on failure.
    """
    try:
        from google.genai import types as genai_types
        from summarizer import get_genai_client, MODEL_FLASH

        # Get the largest photo size
        photo = message.photo[-1]  # last = highest resolution
        file = await context.bot.get_file(photo.file_id)

        # Download to bytes
        photo_bytes = await file.download_as_bytearray()

        client = get_genai_client()
        caption = message.caption or ""
        prompt = f"Describe this image concisely in 1-2 sentences for a team discussion log.{f' Context: {caption}' if caption else ''}"

        response = await client.aio.models.generate_content(
            model=MODEL_FLASH,
            contents=[
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part(text=prompt),
                        genai_types.Part.from_bytes(data=bytes(photo_bytes), mime_type="image/jpeg"),
                    ],
                )
            ],
            config=genai_types.GenerateContentConfig(max_output_tokens=256),
        )
        description = response.text
        if description:
            logger.info(f"Image analyzed: {description[:80]}")
            return description.strip()
        return None
    except Exception as e:
        logger.error(f"Image analysis failed: {e}")
        return None


async def _transcribe_voice(message, context: ContextTypes.DEFAULT_TYPE) -> str | None:
    """Download voice/audio from Telegram and transcribe with Gemini.

    Returns transcript text or None on failure. Stored silently (no reply in group).
    """
    try:
        from tools.voice_transcriber import transcribe_audio

        voice = message.voice or message.audio
        if not voice:
            return None

        file = await context.bot.get_file(voice.file_id)
        audio_bytes = await file.download_as_bytearray()

        mime_type = voice.mime_type or "audio/ogg"
        transcript = await transcribe_audio(bytes(audio_bytes), mime_type=mime_type)
        if transcript:
            logger.info(f"Voice transcribed: {transcript[:80]}")
            return transcript
        return None
    except Exception as e:
        logger.error(f"Voice transcription failed: {e}")
        return None


async def _extract_document_text(
    message, context: ContextTypes.DEFAULT_TYPE
) -> tuple[str | None, str | None]:
    """Download a document from Telegram and extract text.

    Returns (extracted_text, filename) tuple. Both None if unsupported or failed.
    """
    try:
        from tools.file_extractor import extract_file_text, MAX_FILE_SIZE

        doc = message.document
        if not doc:
            return None, None

        filename = doc.file_name or "unknown"
        mime_type = doc.mime_type

        # Size gate: skip files > 5MB
        if doc.file_size and doc.file_size > MAX_FILE_SIZE:
            logger.info(f"File too large ({doc.file_size} bytes): {filename}")
            return None, filename

        file = await context.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()

        text = extract_file_text(bytes(file_bytes), filename, mime_type)
        if text:
            logger.info(f"File extracted: {filename} → {len(text)} chars")
        return text, filename
    except Exception as e:
        logger.error(f"Document extraction failed: {e}")
        return None, message.document.file_name if message.document else None


async def _summarize_and_reply_file(message, file_text: str, filename: str) -> None:
    """Summarize extracted file text and reply in group (like link summaries)."""
    try:
        from baml_client import b
        from baml_client.types import ContentType

        summary_result = b.SummarizeContent(
            content=file_text,
            content_type=ContentType.PDF,
            context=f"File: {filename}",
        )
        title = getattr(summary_result, "title", filename)
        key_points = getattr(summary_result, "key_points", [])
        concise_summary = getattr(summary_result, "concise_summary", "")

        formatted = f"# {title}\n\n"
        if key_points:
            formatted += "## Key Points:\n"
            for point in key_points:
                formatted += f"- {point}\n"
            formatted += "\n"
        formatted += f"## Summary:\n{concise_summary}"

        html_text = md_to_telegram_html(formatted)
        sent_msgs = []
        for i in range(0, len(html_text), MAX_TELEGRAM_MSG_LEN):
            chunk = html_text[i:i + MAX_TELEGRAM_MSG_LEN]
            try:
                sent = await message.reply_text(chunk, parse_mode=ParseMode.HTML)
                sent_msgs.append(sent)
            except Exception:
                await message.reply_text(formatted[i:i + MAX_TELEGRAM_MSG_LEN])

        # Schedule auto-delete after 1 hour via Supabase (survives container restarts)
        if sent_msgs:
            from datetime import timedelta
            delete_after = datetime.now(timezone.utc) + timedelta(hours=24)
            for sent in sent_msgs:
                db.schedule_message_deletion(sent.chat_id, sent.message_id, delete_after)
    except Exception as e:
        logger.error(f"File summarization failed: {e}")


def _detect_link_type(url: str) -> str:
    """Simple heuristic to detect link type from URL."""
    url_lower = url.lower()
    if "grok.com" in url_lower:
        return "grok"
    if "twitter.com" in url_lower or "x.com" in url_lower:
        return "tweet"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if "linkedin.com" in url_lower:
        return "linkedin"
    if "spotify.com" in url_lower:
        return "spotify"
    if "github.com" in url_lower:
        return "github"
    if url_lower.endswith(".pdf"):
        return "pdf"
    return "webpage"


async def _safe_process_update(update: Update) -> None:
    """Process a Telegram update with error logging."""
    try:
        await ptb_app.process_update(update)
    except Exception as e:
        logger.error(f"Update processing failed: {e}", exc_info=True)


# --- FastAPI Lifespan ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init PTB, register handlers, set webhook or start polling."""
    global ptb_app
    logger.info("Application startup...")

    if not config.BOT_TOKEN:
        logger.critical("TELEGRAM_BOT_TOKEN not set. Cannot start.")
        raise RuntimeError("TELEGRAM_BOT_TOKEN required")

    ptb_app = Application.builder().token(config.BOT_TOKEN).build()
    await ptb_app.initialize()
    _register_handlers(ptb_app)
    await ptb_app.start()

    polling_task = None
    if config.USE_POLLING:
        logger.info("Starting polling mode...")
        polling_task = asyncio.create_task(
            ptb_app.updater.start_polling(poll_interval=1.0)
        )
    elif config.WEBHOOK_URL:
        full_url = f"{config.WEBHOOK_URL.rstrip('/')}/{config.WEBHOOK_SECRET_PATH.lstrip('/')}"
        logger.info(f"Setting webhook: {full_url}")
        try:
            await ptb_app.bot.set_webhook(
                url=full_url,
                secret_token=config.WEBHOOK_SECRET_TOKEN or None,
                allowed_updates=Update.ALL_TYPES,
            )
        except Exception as e:
            logger.error(f"Failed to set webhook: {e}", exc_info=True)
    else:
        logger.warning("No polling and no WEBHOOK_URL. Bot may not receive updates.")

    app.state.bot_initialized = True
    logger.info("Bot initialization complete.")

    yield

    logger.info("Application shutdown...")
    try:
        if polling_task and not polling_task.done():
            ptb_app.updater.stop()
            try:
                await asyncio.wait_for(polling_task, timeout=5.0)
            except (asyncio.TimeoutError, Exception):
                polling_task.cancel()
        elif config.WEBHOOK_URL and not config.USE_POLLING:
            try:
                await ptb_app.bot.delete_webhook(drop_pending_updates=True)
            except Exception as e:
                logger.error(f"Failed to delete webhook: {e}")

        if ptb_app.running:
            await ptb_app.stop()
        await ptb_app.shutdown()
        logger.info("PTB shut down.")
    except Exception as e:
        logger.error(f"Error during shutdown: {e}", exc_info=True)


# --- FastAPI App ---
app = FastAPI(lifespan=lifespan)


@app.post(f"/{config.WEBHOOK_SECRET_PATH}")
async def webhook(
    request: Request,
    secret_token: str | None = Header(None, alias="X-Telegram-Bot-Api-Secret-Token"),
) -> dict:
    """Handle incoming Telegram updates via webhook."""
    if config.WEBHOOK_SECRET_TOKEN and secret_token != config.WEBHOOK_SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid secret token")

    if not getattr(app.state, "bot_initialized", False):
        raise HTTPException(status_code=503, detail="Bot not initialized")

    try:
        update_data = await request.json()
        update = Update.de_json(update_data, ptb_app.bot)
        # Process synchronously — keeps the HTTP request open so Cloud Run
        # doesn't kill the container while agent pipeline is running.
        # Telegram allows up to 60s before webhook timeout.
        await _safe_process_update(update)
        return {"ok": True}
    except json.JSONDecodeError:
        return {"ok": False, "error": "Invalid JSON"}
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return {"ok": False, "error": "Internal error"}


@app.post("/api/check-reminders")
async def check_reminders_endpoint():
    """Called by Cloud Scheduler to trigger reminder checks."""
    try:
        from reminders import check_and_send_reminders
        count = await check_and_send_reminders(ptb_app.bot)
        return {"ok": True, "reminders_sent": count}
    except Exception as e:
        logger.error(f"Reminder check failed: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


@app.post("/api/cleanup-messages")
async def cleanup_messages_endpoint():
    """Called by Cloud Scheduler to delete messages past their auto-delete time.

    Processes scheduled_deletions table: deletes Telegram messages, removes DB records.
    Recommended: run every 10 minutes via Cloud Scheduler.
    """
    try:
        due = db.get_due_deletions()
        deleted = 0
        for row in due:
            try:
                await ptb_app.bot.delete_message(
                    chat_id=row["tg_chat_id"],
                    message_id=row["tg_message_id"],
                )
                deleted += 1
            except Exception as e:
                logger.debug(f"Could not delete message {row['tg_message_id']}: {e}")
            # Remove record regardless (message may already be deleted manually)
            db.remove_scheduled_deletion(row["id"])
        return {"ok": True, "processed": len(due), "deleted": deleted}
    except Exception as e:
        logger.error(f"Cleanup messages failed: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


@app.get("/health")
async def health_check():
    """Basic health check endpoint."""
    return {"status": "ok"}


# --- Direct execution (local dev) ---
if __name__ == "__main__":
    if config.USE_POLLING:
        logger.info("Starting in polling mode (direct)...")

        async def _run_polling():
            global ptb_app
            ptb_app = Application.builder().token(config.BOT_TOKEN).build()
            await ptb_app.initialize()
            _register_handlers(ptb_app)
            await ptb_app.start()
            await ptb_app.updater.start_polling(poll_interval=1.0)
            try:
                while True:
                    await asyncio.sleep(3600)
            except KeyboardInterrupt:
                logger.info("Polling stopped.")
            finally:
                if ptb_app.updater.running:
                    ptb_app.updater.stop()
                if ptb_app.running:
                    await ptb_app.stop()
                await ptb_app.shutdown()

        asyncio.run(_run_polling())
    else:
        logger.info(f"Starting Uvicorn on {config.HOST}:{config.PORT}...")
        uvicorn.run(app, host=config.HOST, port=config.PORT)
