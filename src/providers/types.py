"""Provider-agnostic request/response types, Feature enum, and exception hierarchy."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Feature(str, Enum):
    TEXT = "text"       # catchup, topics, topic_detail, decide, draft, reminder, link summary
    IMAGE = "image"     # analyze_image in bot.py
    FILE = "file"       # PDF/DOCX/TXT summarization
    VOICE = "voice"     # tools/voice_transcriber.py
    VIDEO = "video"     # YouTube / video — pinned to Gemini
    ROUTING = "routing" # BAML RouteRequest — stays Gemini in this plan


@dataclass
class TextGenerationConfig:
    """Provider-agnostic text generation params.

    temperature defaults to 0.7 — MiniMax requires > 0; Gemini also accepts this.
    model_chain: override the provider's default model fallback order. None = use
                 provider default. Example: (fallback, primary) for draft mode.
    """
    system_instruction: str = ""
    max_output_tokens: int = 4096
    temperature: float = 0.7
    response_mime_type: Optional[str] = None  # e.g. "application/json"
    response_schema: Optional[dict] = None
    model_chain: Optional[tuple[str, ...]] = None  # None = use provider default


@dataclass
class FilePart:
    """A file to be included in a multimodal prompt."""
    data: bytes
    mime_type: str
    display_name: str = ""


@dataclass
class ImagePart:
    """An image to be included in a multimodal prompt."""
    data: bytes
    mime_type: str


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------

class ProviderError(Exception):
    """Base class for all provider errors."""


class NotSupportedError(ProviderError):
    """Raised when a provider does not support the requested modality."""


class RetryableError(ProviderError):
    """Wraps a transient backend error — upstream retry logic may catch this."""

    def __init__(self, message: str, original: BaseException | None = None) -> None:
        super().__init__(message)
        self.original = original
