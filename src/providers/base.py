"""Abstract Provider base class with usage telemetry hook."""
from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod

from .types import Feature, FilePart, ImagePart, TextGenerationConfig

logger = logging.getLogger(__name__)


class Provider(ABC):
    """Abstract AI provider. Each concrete impl handles retry+fallback internally."""

    name: str  # "gemini" | "minimax"

    @abstractmethod
    async def generate_text(
        self,
        prompt: str | list[dict],
        cfg: TextGenerationConfig,
    ) -> str:
        """Generate text from a text prompt or chat-history list of dicts."""

    @abstractmethod
    async def generate_with_image(
        self,
        image: ImagePart,
        prompt: str,
        cfg: TextGenerationConfig,
    ) -> str:
        """Analyze an image and respond to the prompt."""

    @abstractmethod
    async def generate_with_files(
        self,
        files: list[FilePart],
        prompt: str,
        cfg: TextGenerationConfig,
    ) -> str:
        """Summarize or answer questions about one or more files (PDF, DOCX, TXT)."""

    @abstractmethod
    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        mime: str = "audio/ogg",
    ) -> str | None:
        """Transcribe audio bytes to text. Returns None when transcription is empty."""

    @abstractmethod
    async def understand_video(
        self,
        video: bytes | str,
        prompt: str,
    ) -> str:
        """Summarize or answer questions about a video (bytes or URL).

        Raises NotSupportedError on providers without video input capability.
        """

    def _emit_usage(
        self,
        *,
        feature: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
        latency_ms: int,
    ) -> None:
        """Log one structured JSON line to stdout — Cloud Logging captures it."""
        logger.info(json.dumps({
            "event": "provider_usage",
            "provider": self.name,
            "feature": feature,
            "model": model,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "latency_ms": latency_ms,
        }))
