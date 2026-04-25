"""Supabase client wrapper — singleton client, message/link storage, user state, search."""

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


# ---------------------------------------------------------------------------
# Phase 1: Message & link storage
# ---------------------------------------------------------------------------

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
    media_type: Optional[str] = None,
    source_filename: Optional[str] = None,
) -> Optional[int]:
    """Store a group message. Returns internal id or None if duplicate/error."""
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
        "media_type": media_type,
        "source_filename": source_filename,
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


def message_exists(tg_chat_id: int, tg_msg_id: int) -> bool:
    """True if a message with these Telegram IDs is already in DB.

    Used as cross-instance webhook-retry dedup: in-memory `_processing_messages`
    only catches retries within the same running process, but Cloud Run cold
    starts and scaling create scenarios where Telegram retries hit a fresh
    container with an empty set. On DB error, return False so we still process
    (better to risk a duplicate than silently drop a valid message).
    """
    client = get_client()
    try:
        result = (
            client.table("messages")
            .select("id")
            .eq("tg_chat_id", tg_chat_id)
            .eq("tg_msg_id", tg_msg_id)
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.warning(f"message_exists check failed: {e}")
        return False


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
    row = {"tg_user_id": tg_user_id, "tg_chat_id": tg_chat_id}
    try:
        client.table("user_chat_state").upsert(
            row, on_conflict="tg_user_id,tg_chat_id", ignore_duplicates=True
        ).execute()
    except Exception as e:
        logger.error(f"Failed to ensure user_chat_state: {e}")


# ---------------------------------------------------------------------------
# Phase 2: Catchup queries
# ---------------------------------------------------------------------------

def get_user_chats(tg_user_id: int) -> list[dict]:
    """Get all chats a user has been seen in. Returns list of {tg_chat_id, last_catchup_at}."""
    client = get_client()
    try:
        result = (
            client.table("user_chat_state")
            .select("tg_chat_id, last_catchup_at")
            .eq("tg_user_id", tg_user_id)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to get user chats: {e}")
        return []


def get_last_catchup(tg_user_id: int, tg_chat_id: int) -> Optional[datetime]:
    """Get last catchup timestamp for a (user, chat) pair."""
    client = get_client()
    try:
        result = (
            client.table("user_chat_state")
            .select("last_catchup_at")
            .eq("tg_user_id", tg_user_id)
            .eq("tg_chat_id", tg_chat_id)
            .single()
            .execute()
        )
        if result.data and result.data.get("last_catchup_at"):
            return datetime.fromisoformat(result.data["last_catchup_at"])
        return None
    except Exception as e:
        logger.error(f"Failed to get last catchup: {e}")
        return None


def update_last_catchup(tg_user_id: int, tg_chat_id: int) -> None:
    """Update last_catchup_at to now for a (user, chat) pair."""
    client = get_client()
    try:
        client.table("user_chat_state").update(
            {"last_catchup_at": datetime.now(timezone.utc).isoformat()}
        ).eq("tg_user_id", tg_user_id).eq("tg_chat_id", tg_chat_id).execute()
    except Exception as e:
        logger.error(f"Failed to update last catchup: {e}")


def get_messages_since(
    tg_chat_id: int, since: Optional[datetime] = None, limit: int = 200
) -> list[dict]:
    """Get group messages since a timestamp. If since is None, get last `limit` messages."""
    client = get_client()
    try:
        query = (
            client.table("messages")
            .select("id, tg_user_id, username, text, timestamp, has_links")
            .eq("tg_chat_id", tg_chat_id)
            .order("timestamp", desc=False)
            .limit(limit)
        )
        if since:
            query = query.gt("timestamp", since.isoformat())
        result = query.execute()
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to get messages since: {e}")
        return []


def get_link_summaries_for_messages(message_ids: list[int]) -> list[dict]:
    """Get link summaries for a set of message IDs."""
    if not message_ids:
        return []
    client = get_client()
    try:
        result = (
            client.table("link_summaries")
            .select("message_id, url, title, summary, link_type")
            .in_("message_id", message_ids)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to get link summaries: {e}")
        return []


# ---------------------------------------------------------------------------
# Phase 2: Full-text search
# ---------------------------------------------------------------------------

def search_all(tg_user_id: int, query: str, limit: int = 20) -> list[dict]:
    """Full-text search across messages, link_summaries, and personal_sources.

    Returns results with 'origin' label: 'group' or 'personal'.
    Personal sources filtered by tg_user_id (privacy boundary).
    """
    client = get_client()
    ts_query = " & ".join(query.strip().split())  # "foo bar" → "foo & bar"
    results = []

    try:
        # Search group messages (text_search doesn't support .limit() chaining)
        msg_result = (
            client.table("messages")
            .select("id, username, text, timestamp")
            .text_search("search_vector", ts_query)
            .execute()
        )
        for row in (msg_result.data or [])[:limit]:
            row["origin"] = "group"
            row["type"] = "message"
            results.append(row)
    except Exception as e:
        logger.error(f"FTS messages failed: {e}")

    try:
        link_result = (
            client.table("link_summaries")
            .select("id, url, title, summary, created_at")
            .text_search("search_vector", ts_query)
            .execute()
        )
        for row in (link_result.data or [])[:limit]:
            row["origin"] = "group"
            row["type"] = "link"
            results.append(row)
    except Exception as e:
        logger.error(f"FTS link_summaries failed: {e}")

    try:
        # Personal sources — filtered by user (privacy boundary)
        personal_result = (
            client.table("personal_sources")
            .select("id, source_type, url, title, content, summary, created_at")
            .eq("tg_user_id", tg_user_id)
            .text_search("search_vector", ts_query)
            .execute()
        )
        for row in (personal_result.data or [])[:limit]:
            row["origin"] = "personal"
            row["type"] = row.get("source_type", "note")
            results.append(row)
    except Exception as e:
        logger.error(f"FTS personal_sources failed: {e}")

    return results


# ---------------------------------------------------------------------------
# Phase 2: Personal sources CRUD
# ---------------------------------------------------------------------------

def store_personal_source(
    tg_user_id: int,
    source_type: str,
    content: Optional[str] = None,
    url: Optional[str] = None,
    title: Optional[str] = None,
    summary: Optional[str] = None,
    original_text: Optional[str] = None,
) -> Optional[int]:
    """Store a personal source (link, note, or forwarded message)."""
    client = get_client()
    row = {
        "tg_user_id": tg_user_id,
        "source_type": source_type,
        "url": url,
        "url_normalized": normalize_url(url) if url else None,
        "title": title,
        "content": content,
        "summary": summary,
        "original_text": original_text,
    }
    try:
        result = client.table("personal_sources").insert(row).execute()
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Failed to store personal source: {e}")
        return None


def get_personal_sources(tg_user_id: int, limit: int = 10) -> list[dict]:
    """Get recent personal sources for a user."""
    client = get_client()
    try:
        result = (
            client.table("personal_sources")
            .select("id, source_type, url, title, content, created_at")
            .eq("tg_user_id", tg_user_id)
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to get personal sources: {e}")
        return []


def get_personal_sources_count(tg_user_id: int) -> int:
    """Get count of personal sources for a user."""
    client = get_client()
    try:
        result = (
            client.table("personal_sources")
            .select("id", count="exact")
            .eq("tg_user_id", tg_user_id)
            .execute()
        )
        return result.count or 0
    except Exception as e:
        logger.error(f"Failed to count personal sources: {e}")
        return 0


def delete_personal_source(tg_user_id: int, source_id: int) -> bool:
    """Delete a personal source. Ownership check: must belong to tg_user_id."""
    client = get_client()
    try:
        result = (
            client.table("personal_sources")
            .delete()
            .eq("id", source_id)
            .eq("tg_user_id", tg_user_id)  # ownership check
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.error(f"Failed to delete personal source {source_id}: {e}")
        return False


# ---------------------------------------------------------------------------
# Phase 3: Topic queries + draft sessions
# ---------------------------------------------------------------------------

def get_recent_messages(tg_chat_id: int, hours: int = 48, limit: int = 200) -> list[dict]:
    """Get recent group messages within a time window."""
    client = get_client()
    since = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0
    )
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    try:
        result = (
            client.table("messages")
            .select("id, tg_user_id, username, text, timestamp, has_links")
            .eq("tg_chat_id", tg_chat_id)
            .gt("timestamp", since.isoformat())
            .order("timestamp", desc=False)
            .limit(limit)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to get recent messages: {e}")
        return []


def get_messages_by_keyword(
    tg_chat_id: int, keyword: str, hours: int = 72, limit: int = 100
) -> list[dict]:
    """Get messages matching a keyword via FTS within a time window."""
    client = get_client()
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    # Sanitize keyword for tsquery: split into words, join with & (AND)
    words = [w.strip() for w in keyword.strip().split() if w.strip()]
    if not words:
        return []
    ts_query = " & ".join(words)
    try:
        result = (
            client.table("messages")
            .select("id, tg_user_id, username, text, timestamp, has_links")
            .eq("tg_chat_id", tg_chat_id)
            .gt("timestamp", since.isoformat())
            .text_search("search_vector", ts_query)
            .execute()
        )
        data = sorted((result.data or []), key=lambda m: m.get("timestamp", ""))
        return data[:limit]
    except Exception as e:
        logger.error(f"Failed to search messages by keyword: {e}")
        return []


def create_draft_session(
    tg_user_id: int, topic: str, context_snapshot: dict
) -> Optional[int]:
    """Create a draft session. Fails if an active session already exists (enforced by DB unique index)."""
    client = get_client()
    row = {
        "tg_user_id": tg_user_id,
        "topic": topic,
        "context_snapshot": context_snapshot,
        "conversation_history": [],
    }
    try:
        result = client.table("draft_sessions").insert(row).execute()
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Failed to create draft session: {e}")
        return None


def get_active_draft_session(tg_user_id: int) -> Optional[dict]:
    """Get the active (non-ended, non-expired) draft session for a user."""
    client = get_client()
    from datetime import timedelta
    expiry = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        result = (
            client.table("draft_sessions")
            .select("*")
            .eq("tg_user_id", tg_user_id)
            .is_("ended_at", "null")
            .gt("updated_at", expiry)
            .single()
            .execute()
        )
        return result.data
    except Exception:
        return None


def append_draft_message(session_id: int, role: str, content: str) -> None:
    """Append a message to the draft session's conversation history."""
    client = get_client()
    try:
        # Fetch current history
        session = (
            client.table("draft_sessions")
            .select("conversation_history")
            .eq("id", session_id)
            .single()
            .execute()
        )
        history = session.data.get("conversation_history") or []
        history.append({"role": role, "content": content})
        client.table("draft_sessions").update({
            "conversation_history": history,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", session_id).execute()
    except Exception as e:
        logger.error(f"Failed to append draft message: {e}")


def end_draft_session(session_id: int) -> None:
    """Mark a draft session as ended."""
    client = get_client()
    try:
        client.table("draft_sessions").update({
            "ended_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", session_id).execute()
    except Exception as e:
        logger.error(f"Failed to end draft session: {e}")


def cancel_draft_session(session_id: int) -> None:
    """Cancel (end without saving) a draft session."""
    end_draft_session(session_id)


def expire_stale_drafts() -> int:
    """Expire draft sessions inactive >24h. Returns count expired."""
    client = get_client()
    from datetime import timedelta
    expiry = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    try:
        result = (
            client.table("draft_sessions")
            .update({"ended_at": datetime.now(timezone.utc).isoformat()})
            .is_("ended_at", "null")
            .lt("updated_at", expiry)
            .execute()
        )
        return len(result.data) if result.data else 0
    except Exception as e:
        logger.error(f"Failed to expire stale drafts: {e}")
        return 0


# ---------------------------------------------------------------------------
# Phase 4: Reminder + export helpers
# ---------------------------------------------------------------------------

def get_users_with_reminders_due() -> list[dict]:
    """Get users whose reminders are currently due based on frequency + last_reminder_at.

    daily: due if last_reminder_at is NULL or >24h ago
    weekly: due if last_reminder_at is NULL or >7 days ago
    """
    client = get_client()
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    try:
        result = (
            client.table("users")
            .select("tg_user_id, username, reminder_frequency, timezone, reminder_time, last_reminder_at")
            .neq("reminder_frequency", "off")
            .execute()
        )
        due_users = []
        for user in (result.data or []):
            freq = user.get("reminder_frequency", "off")
            last = user.get("last_reminder_at")
            if last:
                last_dt = datetime.fromisoformat(last)
                if freq == "daily" and (now - last_dt) < timedelta(hours=23):
                    continue  # not due yet
                if freq == "weekly" and (now - last_dt) < timedelta(days=6, hours=23):
                    continue  # not due yet
            due_users.append(user)
        return due_users
    except Exception as e:
        logger.error(f"Failed to get users with reminders: {e}")
        return []


def update_last_reminder(tg_user_id: int) -> None:
    """Update last_reminder_at to now after sending a reminder."""
    client = get_client()
    try:
        client.table("users").update(
            {"last_reminder_at": datetime.now(timezone.utc).isoformat()}
        ).eq("tg_user_id", tg_user_id).execute()
    except Exception as e:
        logger.error(f"Failed to update last_reminder_at: {e}")


def update_user_reminder(tg_user_id: int, frequency: str) -> None:
    """Update a user's reminder frequency."""
    client = get_client()
    try:
        client.table("users").update(
            {"reminder_frequency": frequency}
        ).eq("tg_user_id", tg_user_id).execute()
    except Exception as e:
        logger.error(f"Failed to update reminder: {e}")


def store_export(
    topic: str, export_target: str, content_hash: str,
    notebooklm_source_id: Optional[str] = None,
) -> Optional[int]:
    """Store an export record. Dedup by (export_target, content_hash)."""
    client = get_client()
    row = {
        "topic": topic,
        "export_target": export_target,
        "content_hash": content_hash,
        "notebooklm_source_id": notebooklm_source_id,
    }
    try:
        result = (
            client.table("exports")
            .upsert(row, on_conflict="export_target,content_hash", ignore_duplicates=True)
            .execute()
        )
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Failed to store export: {e}")
        return None


def export_exists(export_target: str, content_hash: str) -> bool:
    """Check if an export with this content_hash already exists."""
    client = get_client()
    try:
        result = (
            client.table("exports")
            .select("id")
            .eq("export_target", export_target)
            .eq("content_hash", content_hash)
            .limit(1)
            .execute()
        )
        return bool(result.data)
    except Exception as e:
        logger.error(f"Failed to check export existence: {e}")
        return False


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def store_feedback(tg_user_id: int, username: Optional[str], feedback_text: str) -> Optional[int]:
    """Store user feedback."""
    client = get_client()
    try:
        result = client.table("feedback").insert({
            "tg_user_id": tg_user_id,
            "username": username,
            "feedback_text": feedback_text,
        }).execute()
        if result.data:
            return result.data[0].get("id")
        return None
    except Exception as e:
        logger.error(f"Failed to store feedback: {e}")
        return None


# ---------------------------------------------------------------------------
# Scheduled deletions — persists auto-delete timers across container restarts
# ---------------------------------------------------------------------------

def schedule_message_deletion(
    tg_chat_id: int, tg_message_id: int, delete_after: datetime
) -> None:
    """Schedule a Telegram message for deletion at a future time."""
    client = get_client()
    row = {
        "tg_chat_id": tg_chat_id,
        "tg_message_id": tg_message_id,
        "delete_after": delete_after.isoformat(),
    }
    try:
        client.table("scheduled_deletions").upsert(
            row, on_conflict="tg_chat_id,tg_message_id", ignore_duplicates=True
        ).execute()
    except Exception as e:
        logger.error(f"Failed to schedule deletion: {e}")


def get_due_deletions() -> list[dict]:
    """Get all scheduled deletions that are past their delete_after time."""
    client = get_client()
    try:
        result = (
            client.table("scheduled_deletions")
            .select("id, tg_chat_id, tg_message_id")
            .lte("delete_after", datetime.now(timezone.utc).isoformat())
            .limit(100)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"Failed to get due deletions: {e}")
        return []


def remove_scheduled_deletion(deletion_id: int) -> None:
    """Remove a scheduled deletion record after processing."""
    client = get_client()
    try:
        client.table("scheduled_deletions").delete().eq("id", deletion_id).execute()
    except Exception as e:
        logger.error(f"Failed to remove scheduled deletion {deletion_id}: {e}")
