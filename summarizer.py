"""Thin orchestration layer — delegates to AI provider. Public API unchanged.

All generate_* functions, constants, and get_genai_client are kept importable
from this module so existing callers and tests require no changes.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

import config  # noqa: F401 — kept so test patches on summarizer.config.* still resolve
from src.providers import Feature, get_provider
from src.providers.gemini_client import get_gemini_client as get_genai_client  # noqa: F401
from src.providers.types import TextGenerationConfig
from src.ai.prompts import catchup as _catchup
from src.ai.prompts import topics as _topics
from src.ai.prompts import topic_detail as _topic_detail
from src.ai.prompts import decide as _decide
from src.ai.prompts import draft as _draft
from src.ai.prompts import reminder as _reminder

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — kept for backward compat (tests reference these directly)
# ---------------------------------------------------------------------------

MODEL_FLASH = "gemini-3-flash-preview"
MODEL_PRO = "gemini-3.1-pro-preview"

_USER_FACING_UNAVAILABLE = (
    "Sorry, I couldn't generate a digest right now — Gemini is temporarily "
    "overloaded. Please try again in a minute."
)

# Legacy singleton ref — test setups reset this via `summarizer._genai_client = None`
# Kept as a module-level stub so test setups that do `summarizer._genai_client = None`
# (to reset the old singleton) don't raise AttributeError.
_genai_client: Optional[object] = None


# ---------------------------------------------------------------------------
# Public API — also exported so tests that import these names still work
# ---------------------------------------------------------------------------

# Re-export system prompt constants consumed by other modules
CATCHUP_SYSTEM = _catchup.SYSTEM
TOPICS_SYSTEM = _topics.SYSTEM
TOPIC_DETAIL_SYSTEM = _topic_detail.SYSTEM
DECIDE_SYSTEM = _decide.SYSTEM
REMINDER_SYSTEM = _reminder.SYSTEM


def build_draft_system_prompt(context: str) -> str:
    """Build system instruction for draft mode with team context."""
    return _draft.build_system_prompt(context)


# ---------------------------------------------------------------------------
# Generate functions — delegate to provider
# ---------------------------------------------------------------------------

async def generate_catchup(messages: list[dict], link_summaries: list[dict]) -> str:
    """Generate a catch-up digest from group messages and link summaries."""
    prompt = _catchup.build_prompt(messages, link_summaries)
    cfg = TextGenerationConfig(system_instruction=_catchup.SYSTEM, max_output_tokens=4096)
    try:
        result = await get_provider(Feature.TEXT).generate_text(prompt, cfg)
        return result or "No digest generated."
    except Exception as e:
        logger.error("Catchup generation failed: %s", e)
        return _USER_FACING_UNAVAILABLE


async def generate_topics(messages: list[dict]) -> list[dict]:
    """Identify discussion topics from recent messages. Returns structured topic list."""
    prompt = _topics.build_prompt(messages)
    cfg = TextGenerationConfig(
        system_instruction=_topics.SYSTEM,
        max_output_tokens=2048,
        response_mime_type="application/json",
    )
    raw = ""
    try:
        raw = await get_provider(Feature.TEXT).generate_text(prompt, cfg)
        return json.loads(raw or "[]")
    except json.JSONDecodeError:
        logger.error("Topics JSON parse failed: %s", raw[:200])
        return []
    except Exception as e:
        logger.error("Topics generation failed: %s", e)
        return []


async def generate_topic_detail(
    messages: list[dict], links: list[dict], topic_name: str
) -> str:
    """Generate detailed synthesis of a specific topic with citations."""
    prompt = _topic_detail.build_prompt(messages, links, topic_name)
    cfg = TextGenerationConfig(
        system_instruction=_topic_detail.SYSTEM,
        max_output_tokens=3072,
    )
    try:
        result = await get_provider(Feature.TEXT).generate_text(prompt, cfg)
        return result or "No detail generated."
    except Exception as e:
        logger.error("Topic detail generation failed: %s", e)
        return (
            "Sorry, I couldn't generate topic detail right now — Gemini is "
            "temporarily overloaded. Please try again in a minute."
        )


async def generate_decision_view(
    messages: list[dict], links: list[dict], topic: str
) -> str:
    """Generate structured decision view with citations."""
    prompt = _decide.build_prompt(messages, links, topic)
    cfg = TextGenerationConfig(
        system_instruction=_decide.SYSTEM,
        max_output_tokens=3072,
    )
    try:
        result = await get_provider(Feature.TEXT).generate_text(prompt, cfg)
        return result or "No decision view generated."
    except Exception as e:
        logger.error("Decision view generation failed: %s", e)
        return (
            "Sorry, I couldn't generate a decision view right now — Gemini is "
            "temporarily overloaded. Please try again in a minute."
        )


async def generate_draft_response(
    conversation_history: list[dict], system_prompt: str
) -> str:
    """Generate a draft response in multi-turn conversation using Pro model preferred."""
    # Build contents as google-genai types.Content for chat history format.
    # The provider's generate_text accepts list[dict] with role/content keys,
    # but draft mode requires proper Content objects for multi-turn context.
    # We pass list[dict] and let the GeminiProvider convert via build_text_contents.
    contents = [
        {"role": ("user" if m["role"] == "user" else "model"), "content": m["content"]}
        for m in conversation_history
    ]
    cfg = TextGenerationConfig(
        system_instruction=system_prompt,
        max_output_tokens=1024,
        model_chain=(MODEL_PRO, MODEL_FLASH),  # Pro preferred for nuanced drafting
    )
    try:
        result = await get_provider(Feature.TEXT).generate_text(contents, cfg)
        return result or "..."
    except Exception as e:
        logger.error("Draft generation failed: %s", e)
        return "Sorry, I had trouble generating a response. Please try again later."


async def generate_reminder_digest(
    message_count: int, topic_names: list[str], stale_topics: list[str]
) -> str:
    """Generate a brief reminder digest for DM."""
    prompt = _reminder.build_prompt(message_count, topic_names, stale_topics)
    cfg = TextGenerationConfig(
        system_instruction=_reminder.SYSTEM,
        max_output_tokens=512,
    )
    try:
        result = await get_provider(Feature.TEXT).generate_text(prompt, cfg)
        return result or f"📬 {message_count} new messages. Use /catchup for details."
    except Exception as e:
        logger.error("Reminder digest generation failed: %s", e)
        return f"📬 {message_count} new messages. Use /catchup for details."
