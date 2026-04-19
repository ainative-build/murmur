"""Supabase client wrapper — singleton client, message/link storage, user state."""

import logging
from datetime import datetime, timezone
from typing import Optional

from supabase import create_client, Client

import config
from url_normalize import normalize_url

logger = logging.getLogger(__name__)

# Singleton Supabase client
_client: Optional[Client] = None


def get_client() -> Client:
    """Return singleton Supabase client, creating on first call."""
    global _client
    if _client is None:
        if not config.SUPABASE_URL or not config.SUPABASE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_KEY must be set")
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        logger.info("Supabase client initialized")
    return _client


def store_message(
    tg_msg_id: int,
    tg_chat_id: int,
    tg_user_id: int,
    username: Optional[str],
    text: Optional[str],
    timestamp: datetime,
    has_links: bool = False,
    reply_to_tg_msg_id: Optional[int] = None,
    forwarded_from: Optional[str] = None,
) -> Optional[int]:
    """Store a group message. Returns internal id or None if duplicate.

    Idempotent via UNIQUE (tg_chat_id, tg_msg_id) — duplicates are ignored.
    """
    client = get_client()
    row = {
        "tg_msg_id": tg_msg_id,
        "tg_chat_id": tg_chat_id,
        "tg_user_id": tg_user_id,
        "username": username,
        "text": text,
        "timestamp": timestamp.isoformat(),
        "has_links": has_links,
        "reply_to_tg_msg_id": reply_to_tg_msg_id,
        "forwarded_from": forwarded_from,
    }
    try:
        result = (
            client.table("messages")
            .upsert(row, on_conflict="tg_chat_id,tg_msg_id", ignore_duplicates=True)
            .execute()
        )
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Failed to store message: {e}")
        return None


def store_link_summary(
    message_id: int,
    url: str,
    link_type: Optional[str] = None,
    title: Optional[str] = None,
    extracted_content: Optional[str] = None,
    summary: Optional[str] = None,
) -> Optional[int]:
    """Store a link summary tied to a message. Dedup by (message_id, url_normalized)."""
    client = get_client()
    url_norm = normalize_url(url)
    row = {
        "message_id": message_id,
        "url": url,
        "url_normalized": url_norm,
        "link_type": link_type,
        "title": title,
        "extracted_content": extracted_content,
        "summary": summary,
    }
    try:
        result = (
            client.table("link_summaries")
            .upsert(row, on_conflict="message_id,url_normalized", ignore_duplicates=True)
            .execute()
        )
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Failed to store link summary: {e}")
        return None


def upsert_user(tg_user_id: int, username: Optional[str] = None) -> None:
    """Create or update a user record."""
    client = get_client()
    row = {"tg_user_id": tg_user_id, "username": username}
    try:
        client.table("users").upsert(row, on_conflict="tg_user_id").execute()
    except Exception as e:
        logger.error(f"Failed to upsert user {tg_user_id}: {e}")


def ensure_user_chat_state(tg_user_id: int, tg_chat_id: int) -> None:
    """Ensure a row exists in user_chat_state for this (user, chat) pair."""
    client = get_client()
    row = {
        "tg_user_id": tg_user_id,
        "tg_chat_id": tg_chat_id,
    }
    try:
        client.table("user_chat_state").upsert(
            row, on_conflict="tg_user_id,tg_chat_id", ignore_duplicates=True
        ).execute()
    except Exception as e:
        logger.error(f"Failed to ensure user_chat_state: {e}")
