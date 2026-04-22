"""Personal source processing — handle DM links, forwarded messages, and notes."""

import logging
import re
from typing import Optional

import db
from agent import run_agent

logger = logging.getLogger(__name__)

URL_REGEX = r"(https?:\/\/[^\s]+)"


def _needs_tinyfish(url: str) -> bool:
    """Check if URL needs TinyFish extraction (login-walled, JS-heavy, or no BAML route)."""
    url_lower = url.lower()
    return (
        "grok.com" in url_lower
        or "github.com" in url_lower
        # X Articles (long-form posts that require login)
        or ("/article/" in url_lower and ("x.com" in url_lower or "twitter.com" in url_lower))
    )


async def extract_link_summary(url: str, original_text: str) -> Optional[str]:
    """Extract and summarize a link — returns summary text, no storage.

    Routes: TinyFish-eligible → TinyFish+BAML, Spotify → API/oEmbed, rest → BAML agent.
    """
    try:
        url_lower = url.lower()
        logger.info(f"extract_link_summary: url={url[:60]}")

        # Grok, GitHub, X Articles → TinyFish extraction + BAML summarization
        if _needs_tinyfish(url):
            return await _extract_via_tinyfish(url)
        # Spotify → Web API / oEmbed
        elif "spotify.com" in url_lower:
            return _extract_spotify_link(url)
        # Everything else → BAML agent pipeline
        else:
            agent_result = await run_agent(original_text)
            if isinstance(agent_result, str) and not agent_result.startswith("Error:"):
                return agent_result
            # Agent failed — try TinyFish as last resort
            logger.info(f"Agent failed, trying TinyFish fallback for {url[:60]}")
            return await _extract_via_tinyfish(url)
    except Exception as e:
        logger.error(f"Link extraction failed: {type(e).__name__}: {e}", exc_info=True)
        return None


async def _extract_via_tinyfish(url: str) -> Optional[str]:
    """Extract content via TinyFish and summarize with BAML."""
    try:
        from tools.tinyfish_fetcher import fetch_url_content
        from baml_client import b
        from baml_client.types import ContentType

        content = await fetch_url_content(url)
        if not content or len(content) < 100:
            logger.warning(f"TinyFish returned insufficient content for {url[:60]}")
            return None

        result = b.SummarizeContent(
            content=content,
            content_type=ContentType.Webpage,
            context=f"Content from {url}",
        )
        title = getattr(result, "title", "Summary")
        key_points = getattr(result, "key_points", [])
        concise_summary = getattr(result, "concise_summary", "")

        formatted = f"# {title}\n\n"
        if key_points:
            formatted += "## Key Points:\n"
            for point in key_points:
                formatted += f"- {point}\n"
            formatted += "\n"
        formatted += f"## Summary:\n{concise_summary}"
        logger.info(f"TinyFish+BAML summary: {len(formatted)} chars for {url[:60]}")
        return formatted
    except Exception as e:
        logger.error(f"TinyFish extraction failed: {type(e).__name__}: {e}")
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
