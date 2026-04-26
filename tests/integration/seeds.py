"""DB seed helpers for DM-flow integration tests.

All helpers go through `db.*` functions so the supabase_shim and FTS
triggers fire end-to-end the same way production does.

Each helper returns IDs / metadata the test can use for further setup.
Tests never assert on absolute IDs (sequences aren't reset) — only on
relationships ("the digest contains user X's text").
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import db


def seed_user(tg_user_id: int, username: str = "alice") -> None:
    db.upsert_user(tg_user_id, username)


def seed_user_chat_state(
    tg_user_id: int,
    tg_chat_id: int,
    *,
    last_catchup: Optional[datetime] = None,
    username: str = "alice",
) -> None:
    """Ensure (user, chat) pair is registered. Optionally back-date last_catchup."""
    db.upsert_user(tg_user_id, username)
    db.ensure_user_chat_state(tg_user_id, tg_chat_id)
    if last_catchup is not None:
        # Direct UPDATE since db has no setter for arbitrary timestamps
        client = db.get_client()
        client.table("user_chat_state").update(
            {"last_catchup_at": last_catchup.isoformat()}
        ).eq("tg_user_id", tg_user_id).eq("tg_chat_id", tg_chat_id).execute()


def seed_message(
    tg_chat_id: int,
    tg_msg_id: int,
    tg_user_id: int,
    text: str,
    *,
    username: str = "alice",
    timestamp: Optional[datetime] = None,
    has_links: bool = False,
) -> int:
    """Insert one group message via db.store_message. Returns internal id."""
    return db.store_message(
        tg_msg_id=tg_msg_id,
        tg_chat_id=tg_chat_id,
        tg_user_id=tg_user_id,
        username=username,
        text=text,
        timestamp=timestamp or datetime.now(timezone.utc),
        has_links=has_links,
    )


def seed_messages_for_topics(
    tg_chat_id: int,
    *,
    base_msg_id: int = 100,
    base_user_id: int = 700,
) -> list[int]:
    """Seed 12 messages across 4 implicit topics. Returns list of internal IDs."""
    now = datetime.now(timezone.utc)
    payloads = [
        # auth thread
        ("alice", "should we use OAuth or JWT for the new auth flow?"),
        ("bob", "OAuth is overkill for our use case, JWT keeps it simple"),
        ("alice", "agreed, let's go with JWT and short token lifetimes"),
        # deploys thread
        ("carol", "the deploy on Friday hit a snag with the migration step"),
        ("dave", "migration ordering — we need to fix that runbook"),
        ("carol", "I'll write up the migration sequence in the wiki"),
        # latency thread
        ("alice", "API p99 latency jumped 200ms after the last release"),
        ("bob", "could be the new query — let's check pg_stat_statements"),
        ("alice", "it's the join with link_summaries; needs an index"),
        # planning thread
        ("dave", "what should we tackle next sprint?"),
        ("carol", "the export feature is most-requested by users"),
        ("dave", "let's prioritise export then; add it to next sprint plan"),
    ]
    ids = []
    for i, (uname, text) in enumerate(payloads):
        ids.append(seed_message(
            tg_chat_id=tg_chat_id,
            tg_msg_id=base_msg_id + i,
            tg_user_id=base_user_id + (i % 4),
            username=uname,
            text=text,
            timestamp=now - timedelta(hours=24, minutes=i * 5),
        ))
    return [i for i in ids if i is not None]


def seed_messages_for_decide(
    tg_chat_id: int,
    *,
    topic_keyword: str = "auth",
    base_msg_id: int = 200,
    base_user_id: int = 800,
) -> list[int]:
    """Seed messages mentioning `topic_keyword` with multiple opinions."""
    now = datetime.now(timezone.utc)
    payloads = [
        ("alice", f"on {topic_keyword}: I think we should use OAuth providers"),
        ("bob", f"counterpoint on {topic_keyword}: passwordless via magic links is simpler"),
        ("carol", f"the {topic_keyword} library has a bug in the refresh flow"),
        ("alice", f"verified — {topic_keyword} library v2 fixed it"),
        ("bob", f"latency is fine but {topic_keyword} requires a redirect step"),
    ]
    ids = []
    for i, (uname, text) in enumerate(payloads):
        ids.append(seed_message(
            tg_chat_id=tg_chat_id,
            tg_msg_id=base_msg_id + i,
            tg_user_id=base_user_id + (i % 3),
            username=uname,
            text=text,
            timestamp=now - timedelta(hours=12, minutes=i * 5),
        ))
    return [i for i in ids if i is not None]


def seed_link_summary(
    message_id: int,
    url: str,
    *,
    link_type: str = "webpage",
    title: str = "Test Link",
    summary: str = "Summary text.",
) -> None:
    db.store_link_summary(
        message_id=message_id,
        url=url,
        link_type=link_type,
        title=title,
        summary=summary,
    )


def seed_personal_source(
    tg_user_id: int,
    *,
    source_type: str = "note",
    content: str = "personal content",
    title: Optional[str] = None,
    url: Optional[str] = None,
) -> int:
    return db.store_personal_source(
        tg_user_id=tg_user_id,
        source_type=source_type,
        content=content,
        title=title,
        url=url,
    )
