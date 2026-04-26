"""Env-driven provider/model selection with per-feature override precedence.

Resolution order (highest to lowest):
  1. AI_PROVIDER_<FEATURE>   e.g. AI_PROVIDER_TEXT=minimax
  2. AI_PROVIDER             global fallback
  3. "gemini"                hard default

VIDEO is always forced to "gemini" — MiniMax has no video input capability.
"""
from __future__ import annotations

import logging
import os

from .types import Feature

logger = logging.getLogger(__name__)

GEMINI = "gemini"
MINIMAX = "minimax"
_VALID_PROVIDERS = {GEMINI, MINIMAX}

# VIDEO hard-pinned regardless of env
_VIDEO_FORCED_PROVIDER = GEMINI

# Model defaults (each overridable via env)
_GEMINI_MODEL_PRIMARY = "gemini-3-flash-preview"
_GEMINI_MODEL_FALLBACK = "gemini-3.1-pro-preview"
_MINIMAX_MODEL = "minimax-m2.7"
_MINIMAX_STT_MODEL = "#g1_whisper-large"
_MINIMAX_BASE_URL = "https://api.minimax.io/v1"


def resolve_provider_name(feature: Feature) -> str:
    """Return the provider name configured for the given feature.

    VIDEO is always "gemini". Unknown names in env fall back to "gemini" with a warning.
    """
    if feature == Feature.VIDEO:
        return _VIDEO_FORCED_PROVIDER

    # Per-feature override (highest precedence)
    per_feature = os.getenv(f"AI_PROVIDER_{feature.value.upper()}", "").strip().lower()
    if per_feature:
        if per_feature not in _VALID_PROVIDERS:
            logger.warning(
                "Unknown provider '%s' for feature '%s', falling back to '%s'",
                per_feature, feature.value, GEMINI,
            )
            return GEMINI
        return per_feature

    # Global fallback
    global_provider = os.getenv("AI_PROVIDER", "").strip().lower()
    if global_provider:
        if global_provider not in _VALID_PROVIDERS:
            logger.warning(
                "Unknown AI_PROVIDER '%s', falling back to '%s'",
                global_provider, GEMINI,
            )
            return GEMINI
        return global_provider

    return GEMINI


def get_gemini_models() -> tuple[str, str]:
    """Return (primary_model, fallback_model) for Gemini."""
    primary = os.getenv("GEMINI_MODEL_PRIMARY", _GEMINI_MODEL_PRIMARY)
    fallback = os.getenv("GEMINI_MODEL_FALLBACK", _GEMINI_MODEL_FALLBACK)
    return primary, fallback


def get_minimax_model() -> str:
    return os.getenv("MINIMAX_MODEL", _MINIMAX_MODEL)


def get_minimax_stt_model() -> str:
    return os.getenv("MINIMAX_STT_MODEL", _MINIMAX_STT_MODEL)


def get_minimax_base_url() -> str:
    return os.getenv("MINIMAX_BASE_URL", _MINIMAX_BASE_URL)
