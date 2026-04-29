"""GeminiProvider — wraps google-genai SDK behind the Provider ABC.

Ports existing logic from summarizer.py, tools/voice_transcriber.py, and
bot.py._analyze_image() with zero behavior change. Retry/fallback/config-building
helpers live in gemini_helpers.py.
"""
from __future__ import annotations

import logging
import time

from google.genai import types as genai_types

from .base import Provider
from .config import get_gemini_models
from .gemini_client import get_gemini_client
from .gemini_helpers import (
    TRANSCRIPTION_PROMPT,
    build_generate_cfg,
    build_text_contents,
    extract_usage,
    is_retryable_gemini,
    run_with_chain,
)
from .retry import with_retry
from .types import Feature, FilePart, ImagePart, TextGenerationConfig

logger = logging.getLogger(__name__)


class GeminiProvider(Provider):
    """Concrete Gemini provider. Flash = primary model, Pro = fallback."""

    name = "gemini"

    def __init__(self) -> None:
        self._primary, self._fallback = get_gemini_models()

    # ------------------------------------------------------------------
    # Provider ABC
    # ------------------------------------------------------------------

    async def generate_text(self, prompt: str | list[dict], cfg: TextGenerationConfig) -> str:
        """Generate text from a string prompt or chat-history list of dicts."""
        client = get_gemini_client()
        contents = build_text_contents(prompt)
        model_chain: tuple[str, ...] = cfg.model_chain or (self._primary, self._fallback)
        gen_cfg = build_generate_cfg(cfg)

        t0 = time.monotonic()

        async def _call(model: str, gcfg):
            return await client.aio.models.generate_content(
                model=model, contents=contents, config=gcfg
            )

        response = await run_with_chain(_call, model_chain, gen_cfg)
        latency_ms = int((time.monotonic() - t0) * 1000)
        in_tok, out_tok = extract_usage(response)
        self._emit_usage(
            feature=Feature.TEXT.value, model=model_chain[0],
            input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency_ms,
        )
        if not response.text:
            finish_reasons = [str(c.finish_reason) for c in (response.candidates or [])]
            logger.warning("Gemini empty response; finish_reasons=%s model=%s", finish_reasons, model_chain[0])
        return response.text or ""

    async def generate_with_image(self, image: ImagePart, prompt: str, cfg: TextGenerationConfig) -> str:
        """Analyze an image and respond to the prompt. Single Flash call + retry."""
        client = get_gemini_client()
        gen_cfg = genai_types.GenerateContentConfig(max_output_tokens=cfg.max_output_tokens)
        contents = [genai_types.Content(
            role="user",
            parts=[
                genai_types.Part(text=prompt),
                genai_types.Part.from_bytes(data=image.data, mime_type=image.mime_type),
            ],
        )]

        t0 = time.monotonic()
        response = await with_retry(
            lambda: client.aio.models.generate_content(
                model=self._primary, contents=contents, config=gen_cfg,
            ),
            is_retryable=is_retryable_gemini,
            label=f"gemini/{self._primary}/image",
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        in_tok, out_tok = extract_usage(response)
        self._emit_usage(
            feature=Feature.IMAGE.value, model=self._primary,
            input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency_ms,
        )
        return (response.text or "").strip()

    async def generate_with_files(self, files: list[FilePart], prompt: str, cfg: TextGenerationConfig) -> str:
        """Summarize/answer questions about one or more files. Single Flash call."""
        client = get_gemini_client()
        parts: list[genai_types.Part] = [
            genai_types.Part.from_bytes(data=f.data, mime_type=f.mime_type) for f in files
        ]
        parts.append(genai_types.Part(text=prompt))
        gen_cfg = build_generate_cfg(cfg)

        t0 = time.monotonic()
        response = await with_retry(
            lambda: client.aio.models.generate_content(
                model=self._primary,
                contents=[genai_types.Content(role="user", parts=parts)],
                config=gen_cfg,
            ),
            is_retryable=is_retryable_gemini,
            label=f"gemini/{self._primary}/files",
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        in_tok, out_tok = extract_usage(response)
        self._emit_usage(
            feature=Feature.FILE.value, model=self._primary,
            input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency_ms,
        )
        return response.text or ""

    async def transcribe_audio(self, audio_bytes: bytes, mime: str = "audio/ogg") -> str | None:
        """Transcribe audio bytes using Gemini Flash. Returns None on failure."""
        if not audio_bytes:
            return None

        client = get_gemini_client()
        try:
            t0 = time.monotonic()
            response = await client.aio.models.generate_content(
                model=self._primary,
                contents=[genai_types.Content(
                    role="user",
                    parts=[
                        genai_types.Part.from_bytes(data=audio_bytes, mime_type=mime),
                        genai_types.Part(text=TRANSCRIPTION_PROMPT),
                    ],
                )],
                config=genai_types.GenerateContentConfig(max_output_tokens=4096),
            )
            latency_ms = int((time.monotonic() - t0) * 1000)
            transcript = response.text
            if transcript and transcript.strip():
                logger.info("Audio transcribed: %d chars", len(transcript))
                in_tok, out_tok = extract_usage(response)
                self._emit_usage(
                    feature=Feature.VOICE.value, model=self._primary,
                    input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency_ms,
                )
                return transcript.strip()
            return None
        except Exception as exc:  # noqa: BLE001
            logger.error("Audio transcription failed: %s", exc)
            return None

    async def understand_video(self, video: bytes | str, prompt: str) -> str:
        """Summarize/answer questions about a video (URL string or raw bytes)."""
        client = get_gemini_client()
        video_part = (
            genai_types.Part.from_uri(file_uri=video, mime_type="video/mp4")
            if isinstance(video, str)
            else genai_types.Part.from_bytes(data=video, mime_type="video/mp4")
        )

        t0 = time.monotonic()
        response = await with_retry(
            lambda: client.aio.models.generate_content(
                model=self._primary,
                contents=[genai_types.Content(
                    role="user",
                    parts=[video_part, genai_types.Part(text=prompt)],
                )],
                config=genai_types.GenerateContentConfig(max_output_tokens=4096),
            ),
            is_retryable=is_retryable_gemini,
            label=f"gemini/{self._primary}/video",
        )
        latency_ms = int((time.monotonic() - t0) * 1000)
        in_tok, out_tok = extract_usage(response)
        self._emit_usage(
            feature=Feature.VIDEO.value, model=self._primary,
            input_tokens=in_tok, output_tokens=out_tok, latency_ms=latency_ms,
        )
        return response.text or ""
