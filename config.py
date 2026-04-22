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

# --- NotebookLM / Export ---
NOTEBOOKLM_NOTEBOOK_ID: str = os.getenv("NOTEBOOKLM_NOTEBOOK_ID", "")
GDRIVE_FOLDER_ID: str = os.getenv("GDRIVE_FOLDER_ID", "")
GOOGLE_CREDENTIALS_PATH: str = os.getenv("GOOGLE_CREDENTIALS_PATH", "")

# --- TinyFish ---
TINYFISH_API_KEY: str = os.getenv("TINYFISH_API_KEY", "")

# --- Spotify (optional — requires Spotify Developer premium for Web API) ---
# Without these: oEmbed fallback gives title + type (no episode descriptions)
SPOTIFY_CLIENT_ID: str = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET: str = os.getenv("SPOTIFY_CLIENT_SECRET", "")

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
