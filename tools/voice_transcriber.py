"""Voice/audio transcription — delegates to AI provider.

Public signature is unchanged: transcribe_audio(audio_bytes, mime_type, max_output_tokens).
Internally routes through get_provider(Feature.VOICE) so the active provider
(Gemini or MiniMax) handles the actual SDK call.
"""

import logging

logger = logging.getLogger(__name__)


async def transcribe_audio(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
    max_output_tokens: int = 4096,  # noqa: ARG001 — kept for signature compat; provider uses its own default
) -> str | None:
    """Transcribe audio bytes using the configured voice provider.

    Args:
        audio_bytes: Raw audio data (OGG Opus, MP3, WAV, etc.)
        mime_type: MIME type of the audio. Telegram voice = "audio/ogg".
        max_output_tokens: Accepted for API compat; provider uses its own limit.

    Returns:
        Transcription text, or None on failure.
    """
    if not audio_bytes:
        return None

    from src.providers import Feature, get_provider
    try:
        return await get_provider(Feature.VOICE).transcribe_audio(audio_bytes, mime_type)
    except Exception as e:
        logger.error("Audio transcription failed: %s", e)
        return None
