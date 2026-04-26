"""Lazy singletons for MiniMax HTTP clients.

- get_minimax_client(): AsyncOpenAI (chat completions, file uploads)
- get_stt_client(): httpx.AsyncClient (custom STT endpoint)
"""
from __future__ import annotations

import httpx
from openai import AsyncOpenAI

import config

_openai_client: AsyncOpenAI | None = None
_stt_client: httpx.AsyncClient | None = None


def get_minimax_client() -> AsyncOpenAI:
    """Return (or create) the shared AsyncOpenAI client for MiniMax."""
    global _openai_client
    if _openai_client is None:
        api_key = config.MINIMAX_API_KEY
        if not api_key:
            raise RuntimeError("MINIMAX_API_KEY not set")
        _openai_client = AsyncOpenAI(
            api_key=api_key,
            base_url=config.MINIMAX_BASE_URL,
            timeout=60.0,
        )
    return _openai_client


def get_stt_client() -> httpx.AsyncClient:
    """Return (or create) the shared httpx client for MiniMax STT endpoints."""
    global _stt_client
    if _stt_client is None:
        api_key = config.MINIMAX_API_KEY
        if not api_key:
            raise RuntimeError("MINIMAX_API_KEY not set")
        _stt_client = httpx.AsyncClient(
            base_url=config.MINIMAX_BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=60.0,
        )
    return _stt_client


def _reset_clients_for_tests() -> None:
    """Reset both singletons. Call from conftest between test cases."""
    global _openai_client, _stt_client
    _openai_client = None
    _stt_client = None
