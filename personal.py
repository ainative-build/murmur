"""Personal source processing — handle DM links, forwarded messages, and notes."""

import logging
import re
from typing import Optional

import db
from agent import run_agent

logger = logging.getLogger(__name__)

URL_REGEX = r"(https?:\/\/[^\s]+)"


async def handle_dm_link(tg_user_id: int, url: str, original_text: str) -> Optional[int]:
    """Process a link sent in DM — route by link type, store as personal source.

    Grok and Spotify links use dedicated extractors (TinyFish / Spotify API).
    All other links go through the BAML agent pipeline.
    """
    try:
        url_lower = url.lower()
        title = None
        summary = None

        # Grok links → TinyFish (no BAML route)
        if "grok.com" in url_lower:
            summary = await _extract_grok_link(url)
        # Spotify links → Web API / oEmbed
        elif "spotify.com" in url_lower:
            summary = _extract_spotify_link(url)
        # All other links → BAML agent pipeline
        else:
            agent_result = await run_agent(original_text)
            if isinstance(agent_result, str) and not agent_result.startswith("Error:"):
                summary = agent_result

        if summary:
            lines = summary.strip().split("\n")
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


async def _extract_grok_link(url: str) -> Optional[str]:
    """Extract Grok conversation via TinyFish and summarize with BAML."""
    try:
        from tools.tinyfish_fetcher import fetch_url_content
        from baml_client import b
        from baml_client.types import ContentType

        content = await fetch_url_content(url)
        if not content or len(content) < 100:
            return None

        result = b.SummarizeContent(
            content=content,
            content_type=ContentType.Webpage,
            context=f"Grok AI conversation from {url}",
        )
        title = getattr(result, "title", "Grok Conversation")
        key_points = getattr(result, "key_points", [])
        concise_summary = getattr(result, "concise_summary", "")

        formatted = f"# {title}\n\n"
        if key_points:
            formatted += "## Key Points:\n"
            for point in key_points:
                formatted += f"- {point}\n"
            formatted += "\n"
        formatted += f"## Summary:\n{concise_summary}"
        return formatted
    except Exception as e:
        logger.error(f"Grok DM extraction failed: {e}")
        return None


def _extract_spotify_link(url: str) -> Optional[str]:
    """Extract Spotify metadata via Web API / oEmbed."""
    try:
        from tools.spotify_scraper import get_spotify_metadata

        metadata = get_spotify_metadata(url)
        if not metadata:
            return None

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
        return None
    except Exception as e:
        logger.error(f"Spotify DM extraction failed: {e}")
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
