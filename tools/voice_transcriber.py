"""Voice/audio transcription via Gemini 3 Flash.

Transcribes audio bytes (OGG Opus from Telegram, MP3, WAV, etc.) using the
google-genai SDK. Same pattern as _analyze_image() in bot.py.

Telegram voice messages are OGG with Opus codec. Gemini docs list OGG Vorbis
as supported — OGG Opus works empirically but add WAV fallback if it breaks.
"""

import logging

from google.genai import types as genai_types

from summarizer import get_genai_client, MODEL_FLASH

logger = logging.getLogger(__name__)

TRANSCRIPTION_PROMPT = (
    "Transcribe this audio accurately. Return only the transcription text, "
    "no commentary, timestamps, or formatting. If the audio is not speech "
    "or is unintelligible, return 'Unable to transcribe'."
)


async def transcribe_audio(
    audio_bytes: bytes,
    mime_type: str = "audio/ogg",
    max_output_tokens: int = 4096,
) -> str | None:
    """Transcribe audio bytes using Gemini 3 Flash.

    Args:
        audio_bytes: Raw audio data (OGG Opus, MP3, WAV, etc.)
        mime_type: MIME type of the audio. Telegram voice = "audio/ogg".
        max_output_tokens: Max tokens for transcription output.

    Returns:
        Transcription text, or None on failure.
    """
    if not audio_bytes:
        return None

    try:
        client = get_genai_client()
        response = await client.aio.models.generate_content(
            model=MODEL_FLASH,
            contents=[
                genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part.from_bytes(
                            data=audio_bytes, mime_type=mime_type
                        ),
                        genai_types.Part(text=TRANSCRIPTION_PROMPT),
                    ],
                )
            ],
            config=genai_types.GenerateContentConfig(
                max_output_tokens=max_output_tokens,
            ),
        )
        transcript = response.text
        if transcript and transcript.strip():
            logger.info(f"Audio transcribed: {len(transcript)} chars")
            return transcript.strip()
        return None
    except Exception as e:
        logger.error(f"Audio transcription failed: {e}")
        return None
