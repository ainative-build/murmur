"""Centralized configuration loaded from environment variables."""

import os
from dotenv import load_dotenv

load_dotenv(override=True)

# --- Telegram ---
BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
WEBHOOK_URL: str = os.getenv("WEBHOOK_URL", "")
WEBHOOK_SECRET_PATH: str = os.getenv("WEBHOOK_SECRET_PATH", "webhook")
WEBHOOK_SECRET_TOKEN: str = os.getenv("TELEGRAM_WEBHOOK_SECRET_TOKEN", "")
USE_POLLING: bool = os.getenv("USE_POLLING", "false").lower() == "true"

# --- Supabase ---
SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")

# --- Google / Gemini ---
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GOOGLE_CLOUD_PROJECT: str = os.getenv("GOOGLE_CLOUD_PROJECT", "")
GOOGLE_CLOUD_LOCATION: str = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")

# --- Server ---
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8080"))

# --- Cloud Run detection ---
IS_CLOUD_RUN: bool = bool(os.getenv("K_SERVICE"))
K_SERVICE: str = os.getenv("K_SERVICE", "")
K_REVISION: str = os.getenv("K_REVISION", "latest")
K_REGION: str = os.getenv("K_REGION", "unknown")

# Cloud Run: WEBHOOK_URL must be set explicitly (auto-inference can't produce
# the correct URL without the project hash). Log a warning if missing.
if IS_CLOUD_RUN and not WEBHOOK_URL:
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "Running in Cloud Run but WEBHOOK_URL not set. "
        "Set WEBHOOK_URL explicitly — auto-inference is unreliable."
    )
