"""Tests for provider factory singleton and provider instantiation."""

import pytest
from unittest.mock import patch, MagicMock

from src.providers.factory import get_provider, _reset_for_tests, _create_provider
from src.providers.types import Feature
from src.providers.config import GEMINI, MINIMAX


@pytest.fixture(autouse=True)
def reset_factory():
    """Reset factory singleton cache before each test."""
    _reset_for_tests()
    yield
    _reset_for_tests()


class TestGetProvider:
    """Test provider factory and singleton behavior."""

    def test_get_provider_returns_singleton(self):
        """Repeated get_provider(Feature.TEXT) returns same instance."""
        p1 = get_provider(Feature.TEXT)
        p2 = get_provider(Feature.TEXT)
        assert p1 is p2

    def test_get_provider_different_features_same_provider(self, monkeypatch):
        """With AI_PROVIDER=minimax, both TEXT and IMAGE use same minimax instance."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")
        p_text = get_provider(Feature.TEXT)
        p_image = get_provider(Feature.IMAGE)
        assert p_text is p_image
        assert p_text.name == MINIMAX

    def test_get_provider_video_always_gemini(self, monkeypatch):
        """VIDEO feature always uses gemini provider even when AI_PROVIDER=minimax."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")
        monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")

        p_text = get_provider(Feature.TEXT)
        p_video = get_provider(Feature.VIDEO)
        assert p_text.name == MINIMAX
        assert p_video.name == GEMINI
        assert p_text is not p_video

    def test_reset_for_tests_clears_cache(self, monkeypatch):
        """_reset_for_tests() clears the singleton cache."""
        monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")
        p1 = get_provider(Feature.TEXT)
        _reset_for_tests()
        p2 = get_provider(Feature.TEXT)
        assert p1 is not p2

    def test_gemini_provider_instantiation(self, monkeypatch):
        """get_provider returns GeminiProvider when AI_PROVIDER=gemini."""
        monkeypatch.setenv("AI_PROVIDER", GEMINI)
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        provider = get_provider(Feature.TEXT)
        assert provider.name == GEMINI

    def test_minimax_provider_instantiation(self, monkeypatch):
        """get_provider returns MiniMaxProvider when AI_PROVIDER=minimax."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")
        provider = get_provider(Feature.TEXT)
        assert provider.name == MINIMAX


class TestCreateProvider:
    """Test direct provider creation (private function)."""

    def test_create_provider_gemini(self, monkeypatch):
        """_create_provider('gemini') returns GeminiProvider."""
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")
        provider = _create_provider(GEMINI)
        assert provider.name == GEMINI

    def test_create_provider_minimax(self, monkeypatch):
        """_create_provider('minimax') returns MiniMaxProvider."""
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")
        provider = _create_provider(MINIMAX)
        assert provider.name == MINIMAX

    def test_create_provider_unknown_raises(self):
        """_create_provider with unknown name raises ValueError."""
        with pytest.raises(ValueError, match="Unknown provider"):
            _create_provider("unknown_provider")
