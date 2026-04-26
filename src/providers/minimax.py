"""MiniMax concrete Provider implementation.

Text, image, and file generation use the OpenAI-compatible chat completions API.
Audio transcription delegates to minimax_stt (submit-then-poll pattern).
Video understanding is not supported — raises NotSupportedError.
"""
from __future__ import annotations

import base64
import io
import logging
import time

import httpx
from openai import APIConnectionError, APITimeoutError, InternalServerError, RateLimitError

from .base import Provider
from .retry import with_retry
from .types import Feature, FilePart, ImagePart, NotSupportedError, TextGenerationConfig

logger = logging.getLogger(__name__)

# Files larger than this are uploaded via the Files API instead of base64-inlined.
_FILE_INLINE_LIMIT = 5 * 1024 * 1024  # 5 MB


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient MiniMax / network errors worth retrying."""
    if isinstance(exc, (APITimeoutError, APIConnectionError, RateLimitError, InternalServerError)):
        return True
    if isinstance(exc, httpx.TimeoutException):
        return True
    # Fallback: check numeric status code attributes present on various error types
    code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if isinstance(code, int) and code in {429, 500, 502, 503, 504}:
        return True
    return False


class MiniMaxProvider(Provider):
    """AI provider backed by MiniMax's OpenAI-compatible API."""

    name = "minimax"

    def __init__(self) -> None:
        from .config import get_minimax_model
        self._model = get_minimax_model()

    # ------------------------------------------------------------------
    # Public Provider interface
    # ------------------------------------------------------------------

    async def generate_text(self, prompt: str | list[dict], cfg: TextGenerationConfig) -> str:
        messages = self._to_messages(prompt, cfg.system_instruction)
        t0 = time.monotonic()
        result = await with_retry(
            lambda: self._chat(messages, cfg),
            is_retryable=_is_retryable,
            label="minimax/text",
        )
        self._emit_usage(
            feature=Feature.TEXT.value, model=self._model,
            input_tokens=0, output_tokens=0,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
        return result

    async def generate_with_image(
        self, image: ImagePart, prompt: str, cfg: TextGenerationConfig
    ) -> str:
        b64 = base64.b64encode(image.data).decode()
        messages: list[dict] = [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{image.mime_type};base64,{b64}"}},
            ],
        }]
        if cfg.system_instruction:
            messages.insert(0, {"role": "system", "content": cfg.system_instruction})
        t0 = time.monotonic()
        result = await with_retry(
            lambda: self._chat(messages, cfg),
            is_retryable=_is_retryable,
            label="minimax/image",
        )
        self._emit_usage(
            feature=Feature.IMAGE.value, model=self._model,
            input_tokens=0, output_tokens=0,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
        return result

    async def generate_with_files(
        self, files: list[FilePart], prompt: str, cfg: TextGenerationConfig
    ) -> str:
        content_parts: list[dict] = [{"type": "text", "text": prompt}]
        for fp in files:
            if len(fp.data) <= _FILE_INLINE_LIMIT:
                b64 = base64.b64encode(fp.data).decode()
                content_parts.append({
                    "type": "file",
                    "file": {
                        "filename": fp.display_name or "document",
                        "file_data": f"data:{fp.mime_type};base64,{b64}",
                    },
                })
            else:
                # Large file: upload via Files API and reference by id
                file_id = await self._upload_file(fp)
                content_parts.append({"type": "file", "file": {"file_id": file_id}})

        messages: list[dict] = [{"role": "user", "content": content_parts}]
        if cfg.system_instruction:
            messages.insert(0, {"role": "system", "content": cfg.system_instruction})

        t0 = time.monotonic()
        result = await with_retry(
            lambda: self._chat(messages, cfg),
            is_retryable=_is_retryable,
            label="minimax/file",
        )
        self._emit_usage(
            feature=Feature.FILE.value, model=self._model,
            input_tokens=0, output_tokens=0,
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
        return result

    async def transcribe_audio(self, audio_bytes: bytes, mime: str = "audio/ogg") -> str | None:
        from .minimax_stt import transcribe_via_stt
        return await transcribe_via_stt(audio_bytes, mime)

    async def understand_video(self, video: bytes | str, prompt: str) -> str:
        raise NotSupportedError(
            "MiniMax does not support video understanding. "
            "Set AI_PROVIDER_VIDEO=gemini or leave VIDEO unset (default is gemini)."
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _chat(self, messages: list[dict], cfg: TextGenerationConfig) -> str:
        """Execute a chat completions request and return the response text."""
        from .minimax_client import get_minimax_client
        client = get_minimax_client()
        params: dict = {
            "model": self._model,
            "messages": messages,
            # MiniMax rejects temperature=0.0; clamp to 0.01 minimum
            "temperature": max(cfg.temperature if cfg.temperature is not None else 0.7, 0.01),
            "max_tokens": cfg.max_output_tokens,
            "stream": False,  # not configurable — streaming adds complexity with no benefit here
        }
        if cfg.response_mime_type == "application/json":
            params["response_format"] = {"type": "json_object"}
        resp = await client.chat.completions.create(**params)
        return resp.choices[0].message.content or ""

    async def _upload_file(self, fp: FilePart) -> str:
        """Upload a file to MiniMax Files API and return its file_id."""
        from .minimax_client import get_minimax_client
        client = get_minimax_client()
        buf = io.BytesIO(fp.data)
        buf.name = fp.display_name or "document"
        result = await client.files.create(
            file=(buf.name, buf, fp.mime_type),
            purpose="assistants",
        )
        return result.id

    @staticmethod
    def _to_messages(prompt: str | list[dict], system_instruction: str) -> list[dict]:
        """Convert a plain string or chat-history list to an OpenAI messages array."""
        messages: list[dict] = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        if isinstance(prompt, str):
            messages.append({"role": "user", "content": prompt})
        else:
            messages.extend(prompt)
        return messages
