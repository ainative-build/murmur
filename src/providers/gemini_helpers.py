"""Low-level helpers for GeminiProvider: retry predicate, chain runner, config builder.

Extracted to keep gemini.py under 200 LOC. Not part of the public providers API.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from google.genai import types as genai_types

from .retry import with_retry
from .types import TextGenerationConfig

logger = logging.getLogger(__name__)

_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}

TRANSCRIPTION_PROMPT = (
    "Transcribe this audio accurately. Return only the transcription text, "
    "no commentary, timestamps, or formatting. If the audio is not speech "
    "or is unintelligible, return 'Unable to transcribe'."
)


def is_retryable_gemini(exc: BaseException) -> bool:
    """True for transient Gemini errors (429, 5xx, UNAVAILABLE, RESOURCE_EXHAUSTED)."""
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int) and code in _RETRYABLE_STATUSES:
        return True
    msg = str(exc).upper()
    return "UNAVAILABLE" in msg or "RESOURCE_EXHAUSTED" in msg or " 503" in msg or " 429" in msg


async def run_with_chain(
    call_factory: Callable[[str, Any], Any],
    models: tuple[str, ...],
    cfg: Any,
) -> genai_types.GenerateContentResponse:
    """Try each model in turn, retrying each 3x on transient errors before falling back."""
    last_exc: Optional[BaseException] = None
    for model in models:
        try:
            return await with_retry(
                lambda m=model: call_factory(m, cfg),
                is_retryable=is_retryable_gemini,
                label=f"gemini/{model}",
            )
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            logger.warning("Gemini %s exhausted, trying next: %s", model, exc)
    raise last_exc  # type: ignore[misc]


def build_generate_cfg(cfg: TextGenerationConfig) -> genai_types.GenerateContentConfig:
    """Map TextGenerationConfig fields to a GenerateContentConfig for the SDK."""
    kwargs: dict[str, Any] = {"max_output_tokens": cfg.max_output_tokens}
    if cfg.system_instruction:
        kwargs["system_instruction"] = cfg.system_instruction
    if cfg.response_mime_type:
        kwargs["response_mime_type"] = cfg.response_mime_type
    return genai_types.GenerateContentConfig(**kwargs)


def build_text_contents(prompt: str | list[dict]) -> list:
    """Convert a plain-string prompt or chat-history list into genai Content objects."""
    if isinstance(prompt, str):
        return [genai_types.Part(text=prompt)]
    # Chat-history: [{"role": "user"|"model"|"assistant", "content": str}, ...]
    return [
        genai_types.Content(
            role="user" if m["role"] == "user" else "model",
            parts=[genai_types.Part(text=m["content"])],
        )
        for m in prompt
    ]


def extract_usage(response) -> tuple[int, int]:
    """Return (input_tokens, output_tokens) from a response, defaulting to 0."""
    usage = response.usage_metadata or {}
    return (
        getattr(usage, "prompt_token_count", 0) or 0,
        getattr(usage, "candidates_token_count", 0) or 0,
    )
