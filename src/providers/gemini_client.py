"""Singleton google-genai Client — shared by GeminiProvider and any legacy callers."""
from __future__ import annotations

import logging
from typing import Optional

from google import genai

import config

logger = logging.getLogger(__name__)

_genai_client: Optional[genai.Client] = None


def get_gemini_client() -> genai.Client:
    """Return singleton google-genai client.

    Uses Vertex AI on Cloud Run (project auto-detected), API key locally.
    Raises RuntimeError when no credentials are configured.
    """
    global _genai_client
    if _genai_client is None:
        if config.IS_CLOUD_RUN and config.GOOGLE_CLOUD_PROJECT:
            _genai_client = genai.Client(
                vertexai=True,
                project=config.GOOGLE_CLOUD_PROJECT,
                location=config.GOOGLE_CLOUD_LOCATION,
            )
            logger.info("google-genai client initialized (Vertex AI)")
        elif config.GEMINI_API_KEY:
            _genai_client = genai.Client(api_key=config.GEMINI_API_KEY)
            logger.info("google-genai client initialized (API key)")
        else:
            raise RuntimeError("No Gemini credentials: set GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT")
    return _genai_client
