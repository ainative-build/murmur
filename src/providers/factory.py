"""Provider factory — returns singletons keyed by provider name.

Usage:
    provider = get_provider(Feature.TEXT)
    result = await provider.generate_text(prompt, cfg)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .config import GEMINI, MINIMAX, resolve_provider_name
from .types import Feature

if TYPE_CHECKING:
    from .base import Provider

logger = logging.getLogger(__name__)

_instances: dict[str, "Provider"] = {}


def get_provider(feature: Feature) -> "Provider":
    """Return the configured provider for the given feature (singleton per name).

    VIDEO always returns the Gemini provider — MiniMax has no video input.
    Provider instances are lazily initialized on first use.
    """
    provider_name = resolve_provider_name(feature)
    if provider_name not in _instances:
        _instances[provider_name] = _create_provider(provider_name)
    return _instances[provider_name]


def _create_provider(name: str) -> "Provider":
    """Instantiate a provider by name. Imports are deferred to avoid circular deps."""
    if name == GEMINI:
        from .gemini import GeminiProvider
        logger.info("Initializing Gemini provider")
        return GeminiProvider()
    if name == MINIMAX:
        from .minimax import MiniMaxProvider
        logger.info("Initializing MiniMax provider")
        return MiniMaxProvider()
    raise ValueError(f"Unknown provider: '{name}'")


def _reset_for_tests() -> None:
    """Clear singleton cache. Call from conftest between test cases."""
    _instances.clear()
