"""Tests for resolve_provider_name and model config functions."""

import os
import pytest

from src.providers.config import (
    resolve_provider_name,
    get_gemini_models,
    get_minimax_model,
    get_minimax_stt_model,
    get_minimax_base_url,
    GEMINI,
    MINIMAX,
)
from src.providers.types import Feature


class TestResolveProviderName:
    """Test env-driven provider resolution with precedence rules."""

    def test_no_env_returns_gemini(self, monkeypatch):
        """When no AI_PROVIDER env set, all features default to gemini."""
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        monkeypatch.delenv("AI_PROVIDER_TEXT", raising=False)
        assert resolve_provider_name(Feature.TEXT) == GEMINI
        assert resolve_provider_name(Feature.IMAGE) == GEMINI
        assert resolve_provider_name(Feature.FILE) == GEMINI
        assert resolve_provider_name(Feature.VOICE) == GEMINI

    def test_video_always_gemini(self, monkeypatch):
        """VIDEO feature is hard-pinned to Gemini regardless of AI_PROVIDER."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        assert resolve_provider_name(Feature.VIDEO) == GEMINI

    def test_global_ai_provider_text(self, monkeypatch):
        """AI_PROVIDER=minimax sets global provider to minimax (except VIDEO)."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        assert resolve_provider_name(Feature.TEXT) == MINIMAX
        assert resolve_provider_name(Feature.IMAGE) == MINIMAX
        assert resolve_provider_name(Feature.FILE) == MINIMAX
        assert resolve_provider_name(Feature.VOICE) == MINIMAX
        assert resolve_provider_name(Feature.VIDEO) == GEMINI

    def test_per_feature_override_beats_global(self, monkeypatch):
        """AI_PROVIDER_TEXT=gemini overrides global AI_PROVIDER=minimax."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        monkeypatch.setenv("AI_PROVIDER_TEXT", GEMINI)
        assert resolve_provider_name(Feature.TEXT) == GEMINI
        assert resolve_provider_name(Feature.IMAGE) == MINIMAX

    def test_invalid_global_provider_fallback(self, monkeypatch, caplog):
        """Invalid AI_PROVIDER falls back to gemini with warning."""
        monkeypatch.setenv("AI_PROVIDER", "invalid_provider")
        result = resolve_provider_name(Feature.TEXT)
        assert result == GEMINI
        assert "Unknown AI_PROVIDER" in caplog.text

    def test_invalid_per_feature_provider_fallback(self, monkeypatch, caplog):
        """Invalid AI_PROVIDER_TEXT falls back to gemini with warning."""
        monkeypatch.setenv("AI_PROVIDER_TEXT", "bad_provider")
        result = resolve_provider_name(Feature.TEXT)
        assert result == GEMINI
        assert "Unknown provider" in caplog.text

    def test_whitespace_and_case_normalization(self, monkeypatch):
        """Env values are trimmed and lowercased."""
        monkeypatch.setenv("AI_PROVIDER", "  MINIMAX  ")
        assert resolve_provider_name(Feature.TEXT) == MINIMAX


class TestModelConfig:
    """Test model name getters from env or defaults."""

    def test_gemini_models_default(self, monkeypatch):
        """get_gemini_models returns defaults when env not set."""
        monkeypatch.delenv("GEMINI_MODEL_PRIMARY", raising=False)
        monkeypatch.delenv("GEMINI_MODEL_FALLBACK", raising=False)
        primary, fallback = get_gemini_models()
        assert primary == "gemini-3-flash-preview"
        assert fallback == "gemini-3.1-pro-preview"

    def test_gemini_models_from_env(self, monkeypatch):
        """get_gemini_models respects env overrides."""
        monkeypatch.setenv("GEMINI_MODEL_PRIMARY", "custom-flash")
        monkeypatch.setenv("GEMINI_MODEL_FALLBACK", "custom-pro")
        primary, fallback = get_gemini_models()
        assert primary == "custom-flash"
        assert fallback == "custom-pro"

    def test_minimax_model_default(self, monkeypatch):
        """get_minimax_model returns default when env not set."""
        monkeypatch.delenv("MINIMAX_MODEL", raising=False)
        assert get_minimax_model() == "minimax-m2.7"

    def test_minimax_model_from_env(self, monkeypatch):
        """get_minimax_model respects env override."""
        monkeypatch.setenv("MINIMAX_MODEL", "minimax-m4")
        assert get_minimax_model() == "minimax-m4"

    def test_minimax_stt_model_default(self, monkeypatch):
        """get_minimax_stt_model returns default when env not set."""
        monkeypatch.delenv("MINIMAX_STT_MODEL", raising=False)
        assert get_minimax_stt_model() == "#g1_whisper-large"

    def test_minimax_stt_model_from_env(self, monkeypatch):
        """get_minimax_stt_model respects env override."""
        monkeypatch.setenv("MINIMAX_STT_MODEL", "#g1_whisper-custom")
        assert get_minimax_stt_model() == "#g1_whisper-custom"

    def test_minimax_base_url_default(self, monkeypatch):
        """get_minimax_base_url returns default when env not set."""
        monkeypatch.delenv("MINIMAX_BASE_URL", raising=False)
        assert get_minimax_base_url() == "https://api.minimax.io/v1"

    def test_minimax_base_url_from_env(self, monkeypatch):
        """get_minimax_base_url respects env override."""
        monkeypatch.setenv("MINIMAX_BASE_URL", "https://custom.api/v2")
        assert get_minimax_base_url() == "https://custom.api/v2"
