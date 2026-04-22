"""Personal source processing — handle DM links, forwarded messages, and notes."""

import logging
import re
from typing import Optional

import db
from agent import run_agent

logger = logging.getLogger(__name__)

URL_REGEX = r"(https?:\/\/[^\s]+)"


async def handle_dm_link(tg_user_id: int, url: str, original_text: str) -> Optional[int]:
    """Process a link sent in DM — run agent pipeline, store as personal source."""
    try:
        agent_result = await run_agent(original_text)
        title = None
        summary = None

        if isinstance(agent_result, str) and not agent_result.startswith("Error:"):
            summary = agent_result
            lines = agent_result.strip().split("\n")
            if lines and lines[0].startswith("#"):
                title = lines[0].lstrip("#").strip()

        return db.store_personal_source(
            tg_user_id=tg_user_id,
            source_type="link",
            url=url,
            title=title,
            content=summary,
            summary=summary,
            original_text=original_text,
        )
    except Exception as e:
        logger.error(f"Failed to handle DM link: {e}")
        return None


def handle_dm_forward(tg_user_id: int, text: str, forwarded_from: Optional[str] = None) -> Optional[int]:
    """Store a forwarded message as personal source."""
    title = f"Forwarded from {forwarded_from}" if forwarded_from else "Forwarded message"
    return db.store_personal_source(
        tg_user_id=tg_user_id,
        source_type="forwarded_message",
        content=text,
        title=title,
        original_text=text,
    )


def handle_dm_note(tg_user_id: int, text: str) -> Optional[int]:
    """Store a personal note."""
    return db.store_personal_source(
        tg_user_id=tg_user_id,
        source_type="note",
        content=text,
    )


def handle_dm_voice(tg_user_id: int, transcript: str) -> Optional[int]:
    """Store a voice transcript as personal source."""
    return db.store_personal_source(
        tg_user_id=tg_user_id,
        source_type="voice",
        content=transcript,
        title="Voice message",
    )


def handle_dm_file(
    tg_user_id: int, filename: str, text: str, summary: Optional[str] = None
) -> Optional[int]:
    """Store extracted file text as personal source."""
    return db.store_personal_source(
        tg_user_id=tg_user_id,
        source_type="file",
        content=text,
        title=filename,
        summary=summary,
    )


def detect_urls(text: str) -> list[str]:
    """Extract URLs from text."""
    return re.findall(URL_REGEX, text)
