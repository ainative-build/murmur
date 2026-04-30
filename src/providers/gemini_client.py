"""Singleton google-genai Client — Vertex AI only.

API-key (AI Studio) path was removed: Gemini is reserved for features MiniMax
cannot handle (VOICE, VIDEO) and runs through Vertex AI to keep cost on the
GCP bill instead of separate AI Studio billing.

Auth:
  - Cloud Run: default service account (needs roles/aiplatform.user).
  - Local dev: Application Default Credentials via
        gcloud auth application-default login
    plus GOOGLE_CLOUD_PROJECT in .env.
"""
from __future__ import annotations

import logging
from typing import Optional

from google import genai

import config

logger = logging.getLogger(__name__)

_genai_client: Optional[genai.Client] = None


def get_gemini_client() -> genai.Client:
    """Return singleton Vertex-AI-backed google-genai client.

    Raises RuntimeError when GOOGLE_CLOUD_PROJECT is unset — the API-key path
    has been removed.
    """
    global _genai_client
    if _genai_client is None:
        if not config.GOOGLE_CLOUD_PROJECT:
            raise RuntimeError(
                "GOOGLE_CLOUD_PROJECT is required for Vertex AI. "
                "Locally: gcloud auth application-default login + set GOOGLE_CLOUD_PROJECT."
            )
        _genai_client = genai.Client(
            vertexai=True,
            project=config.GOOGLE_CLOUD_PROJECT,
            location=config.GOOGLE_CLOUD_LOCATION,
        )
        logger.info(
            "google-genai client initialized (Vertex AI, project=%s, location=%s)",
            config.GOOGLE_CLOUD_PROJECT, config.GOOGLE_CLOUD_LOCATION,
        )
    return _genai_client
