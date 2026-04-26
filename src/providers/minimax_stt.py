"""MiniMax async Speech-to-Text via submit-then-poll pattern.

POST /stt/create  → receive generation_id
GET  /stt/{id}    → poll until success/failed or 30s deadline
"""
from __future__ import annotations

import asyncio
import logging
import time

logger = logging.getLogger(__name__)

STT_POLL_INTERVAL_S = 2.0
STT_POLL_DEADLINE_S = 30.0

# Terminal status strings returned by the MiniMax STT API
_STATUS_SUCCESS = {"success", "completed", "done"}
_STATUS_FAILED = {"failed", "error"}


async def transcribe_via_stt(audio_bytes: bytes, mime: str = "audio/ogg") -> str | None:
    """Submit an audio file to MiniMax STT and poll for the transcript.

    Args:
        audio_bytes: Raw audio data.
        mime: MIME type of the audio (default: audio/ogg for Telegram voice notes).

    Returns:
        Transcript string stripped of surrounding whitespace, or None when the
        transcript is empty or the job failed.

    Raises:
        TimeoutError: When the polling deadline (30 s) is exceeded.
            Caller should surface "transcription timed out, try again." to the user.
        httpx.HTTPStatusError: On non-2xx responses from the API.
    """
    from .minimax_client import get_stt_client
    from .config import get_minimax_stt_model

    client = get_stt_client()
    model = get_minimax_stt_model()

    # --- Submit job ---
    resp = await client.post(
        "/stt/create",
        data={"model": model},
        files={"audio": ("voice.ogg", audio_bytes, mime)},
    )
    resp.raise_for_status()
    payload = resp.json()

    gen_id = payload.get("generation_id") or payload.get("id")
    if not gen_id:
        logger.error("MiniMax STT: missing generation_id in response: %s", payload)
        return None

    logger.debug("MiniMax STT job submitted: %s", gen_id)

    # --- Poll for result ---
    deadline = time.monotonic() + STT_POLL_DEADLINE_S
    while time.monotonic() < deadline:
        await asyncio.sleep(STT_POLL_INTERVAL_S)

        poll = await client.get(f"/stt/{gen_id}")
        poll.raise_for_status()
        body = poll.json()

        status = body.get("status", "").lower()
        logger.debug("MiniMax STT job %s status: %s", gen_id, status)

        if status in _STATUS_SUCCESS:
            text = body.get("text") or body.get("transcript") or body.get("result")
            return text.strip() if text else None

        if status in _STATUS_FAILED:
            logger.warning("MiniMax STT failed for job %s: %s", gen_id, body)
            return None

        # pending / processing → keep polling

    raise TimeoutError(
        f"MiniMax STT polling exceeded {STT_POLL_DEADLINE_S}s for job {gen_id} — "
        "caller should surface 'transcription timed out, try again.'"
    )
