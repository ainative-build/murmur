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
    Application, MessageHandler, CommandHandler, ConversationHandler,
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
    topics_handler, topic_handler, decide_handler,
    remind_handler, export_handler, kb_handler,
)
from draft_mode import draft_start_handler, draft_continue_handler, draft_end_handler, draft_cancel_handler, DRAFTING

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

    # Draft mode — ConversationHandler for multi-turn /draft in DM
    draft_handler = ConversationHandler(
        entry_points=[CommandHandler("draft", draft_start_handler, filters=private)],
        states={
            DRAFTING: [MessageHandler(filters.TEXT & (~filters.COMMAND), draft_continue_handler)],
        },
        fallbacks=[
            CommandHandler("done", draft_end_handler),
            CommandHandler("cancel", draft_cancel_handler),
        ],
        per_user=True,
        per_chat=True,
    )
    app.add_handler(draft_handler)

    # DM non-command messages — links, forwards, plain text
    app.add_handler(MessageHandler(
        filters.TEXT & (~filters.COMMAND) & private,
        dm_message_handler,
    ))

    # Group messages: capture ALL text + photos + documents for history.
    # group=1 runs alongside command handlers in group 0.
    app.add_handler(
        MessageHandler(
            (filters.TEXT | filters.PHOTO | filters.Document.ALL) & filters.ChatType.GROUPS,
            group_message_handler,
        ),
        group=1,
    )


# --- Handlers ---

async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture ALL group messages (text + photos + docs) into Supabase."""
    message = update.effective_message
    if not message:
        return

    tg_user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    tg_chat_id = message.chat_id
    tg_msg_id = message.message_id
    timestamp = message.date or datetime.now(timezone.utc)

    # Get text — could be message.text or message.caption (for photos/docs)
    text = message.text or message.caption or ""

    # Check if this is a photo/document that needs vision analysis
    has_photo = bool(message.photo)
    has_document = bool(message.document)

    # If photo, analyze with Gemini vision and prepend description to text
    if has_photo:
        description = await _analyze_image(message, context)
        if description:
            text = f"[Image: {description}]" + (f"\n{text}" if text else "")

    if not text:
        return  # Nothing to store (no text, no caption, image analysis failed)

    urls = re.findall(URL_REGEX, text)
    has_links = len(urls) > 0

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
    )

    db.upsert_user(tg_user_id, username)
    db.ensure_user_chat_state(tg_user_id, tg_chat_id)

    if has_links:
        await _process_links_and_store(message, text, urls, message_id)


async def _process_links_and_store(
    message, text: str, urls: list[str], message_id: Optional[int]
) -> None:
    """Run agent pipeline on link message, reply with summary, store in link_summaries."""
    try:
        agent_result = await run_agent(text)

        if isinstance(agent_result, str) and not agent_result.startswith("Error:"):
            url = urls[0]
            title = None
            lines = agent_result.strip().split("\n")
            if lines and lines[0].startswith("#"):
                title = lines[0].lstrip("#").strip()

            if message_id:
                db.store_link_summary(
                    message_id=message_id,
                    url=url,
                    link_type=_detect_link_type(url),
                    title=title,
                    summary=agent_result,
                )

            # Convert markdown to Telegram HTML, schedule auto-delete after 1 hour.
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

            # Schedule deletion after 1 hour
            if sent_msgs:
                asyncio.create_task(_delete_after(sent_msgs, delay_seconds=3600))
        elif isinstance(agent_result, str):
            logger.error(f"Agent error for {urls[0]}: {agent_result}")
            # Let users know the link couldn't be processed
            await message.reply_text(
                f"⚠️ Couldn't extract content from this link (may require login or has bot protection)."
            )
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


async def _delete_after(messages: list, delay_seconds: int = 3600) -> None:
    """Delete messages after a delay. Used for auto-cleaning summaries from group chat."""
    await asyncio.sleep(delay_seconds)
    for msg in messages:
        try:
            await msg.delete()
        except Exception as e:
            logger.debug(f"Could not delete message {msg.message_id}: {e}")


def _detect_link_type(url: str) -> str:
    """Simple heuristic to detect link type from URL."""
    url_lower = url.lower()
    if "twitter.com" in url_lower or "x.com" in url_lower:
        return "tweet"
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        return "youtube"
    if "linkedin.com" in url_lower:
        return "linkedin"
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
        asyncio.create_task(_safe_process_update(update))
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
