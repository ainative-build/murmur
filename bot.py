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
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from telegram.constants import ParseMode

import config
import db
from agent import run_agent
from commands import start_handler

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
    app.add_handler(CommandHandler("start", start_handler, filters=filters.ChatType.PRIVATE))
    # Capture ALL group text messages — including commands — so the full
    # conversation history is stored for catchup/search. group=1 ensures
    # this runs alongside (not instead of) any future group CommandHandlers.
    app.add_handler(
        MessageHandler(
            filters.TEXT & filters.ChatType.GROUPS,
            group_message_handler,
        ),
        group=1,
    )


# --- Handlers ---

async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Capture ALL group messages into Supabase. If message has links, also run agent pipeline."""
    message = update.effective_message
    if not message or not message.text:
        return

    tg_user_id = message.from_user.id if message.from_user else 0
    username = message.from_user.username if message.from_user else None
    text = message.text
    tg_chat_id = message.chat_id
    tg_msg_id = message.message_id
    timestamp = message.date or datetime.now(timezone.utc)

    # Check for links
    urls = re.findall(URL_REGEX, text)
    has_links = len(urls) > 0

    # Store message in Supabase
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

    # Ensure user + user_chat_state records exist
    db.upsert_user(tg_user_id, username)
    db.ensure_user_chat_state(tg_user_id, tg_chat_id)

    # If message has links, run agent pipeline regardless of DB write outcome.
    # message_id may be None on duplicate or transient DB failure — link processing
    # should still proceed since run_agent() is independent of persistence.
    if has_links:
        await _process_links_and_store(message, text, urls, message_id)


async def _process_links_and_store(
    message, text: str, urls: list[str], message_id: Optional[int]
) -> None:
    """Run agent pipeline on link message, reply with summary, store in link_summaries.

    message_id may be None if store_message failed — agent still runs and replies,
    but link summary is not persisted to DB without a parent message row.
    """
    try:
        agent_result = await run_agent(text)

        if isinstance(agent_result, str) and not agent_result.startswith("Error:"):
            url = urls[0]  # Agent processes first URL in message
            # Extract title from agent result (first line is often "# Title")
            title = None
            lines = agent_result.strip().split("\n")
            if lines and lines[0].startswith("#"):
                title = lines[0].lstrip("#").strip()

            # Only persist to DB if we have a valid parent message row
            if message_id:
                db.store_link_summary(
                    message_id=message_id,
                    url=url,
                    link_type=_detect_link_type(url),
                    title=title,
                    summary=agent_result,
                )

            # Reply in group — escape per chunk to avoid splitting HTML entities
            for i in range(0, len(agent_result), MAX_TELEGRAM_MSG_LEN):
                raw_chunk = agent_result[i:i + MAX_TELEGRAM_MSG_LEN]
                try:
                    await message.reply_text(html.escape(raw_chunk), parse_mode=ParseMode.HTML)
                except Exception:
                    try:
                        await message.reply_text(raw_chunk)
                    except Exception as e:
                        logger.error(f"Failed to send chunk: {e}")
                        break
                if i + MAX_TELEGRAM_MSG_LEN < len(agent_result):
                    await asyncio.sleep(0.5)
        elif isinstance(agent_result, str):
            logger.error(f"Agent error for {urls[0]}: {agent_result}")
        else:
            logger.error(f"Agent returned {type(agent_result)} for {urls[0]}")

    except Exception as e:
        logger.error(f"Error processing links: {e}", exc_info=True)


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
    """Process a Telegram update with error logging (prevents silent task failures)."""
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

    # Build PTB app here (not at import time) to avoid crashes in tests/scripts
    ptb_app = Application.builder().token(config.BOT_TOKEN).build()
    await ptb_app.initialize()
    _register_handlers(ptb_app)
    await ptb_app.start()

    # Polling or webhook mode
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

    # --- Shutdown ---
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
