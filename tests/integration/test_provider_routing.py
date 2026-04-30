"""Integration tests for provider routing via env config and factory."""

import pytest
from unittest.mock import AsyncMock, patch

from src.providers.factory import get_provider, _reset_for_tests
from src.providers.types import Feature, TextGenerationConfig
from src.providers.config import GEMINI, MINIMAX


@pytest.fixture(autouse=True)
def reset_factory_between_tests():
    """Reset factory singleton before/after each test."""
    _reset_for_tests()
    yield
    _reset_for_tests()


class TestProviderRouting:
    """Integration tests for provider resolution and routing."""

    async def test_text_routes_to_minimax_when_configured(self, monkeypatch):
        """When AI_PROVIDER=minimax, TEXT routes to MiniMaxProvider."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")

        provider = get_provider(Feature.TEXT)
        assert provider.name == MINIMAX

    async def test_text_routes_to_minimax_by_default(self, monkeypatch):
        """When AI_PROVIDER not set, TEXT routes to MiniMaxProvider (project default)."""
        monkeypatch.delenv("AI_PROVIDER", raising=False)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")

        provider = get_provider(Feature.TEXT)
        assert provider.name == MINIMAX

    async def test_per_feature_override_routing(self, monkeypatch):
        """AI_PROVIDER_TEXT=gemini overrides global AI_PROVIDER=minimax."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        monkeypatch.setenv("AI_PROVIDER_TEXT", GEMINI)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")

        text_provider = get_provider(Feature.TEXT)
        image_provider = get_provider(Feature.IMAGE)

        assert text_provider.name == GEMINI
        assert image_provider.name == MINIMAX

    async def test_video_always_gemini_regardless_of_config(self, monkeypatch):
        """VIDEO always uses Gemini even when AI_PROVIDER=minimax."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")
        monkeypatch.setenv("GEMINI_API_KEY", "test_key")

        text_provider = get_provider(Feature.TEXT)
        video_provider = get_provider(Feature.VIDEO)

        assert text_provider.name == MINIMAX
        assert video_provider.name == GEMINI

    async def test_singleton_per_provider_name(self, monkeypatch):
        """Different features using same provider return same singleton."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")

        text_provider = get_provider(Feature.TEXT)
        image_provider = get_provider(Feature.IMAGE)
        file_provider = get_provider(Feature.FILE)

        assert text_provider is image_provider
        assert image_provider is file_provider

    async def test_text_generation_minimax_provider(self, monkeypatch):
        """generate_text routes through MiniMax when configured."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")

        provider = get_provider(Feature.TEXT)

        # Mock the chat completions call
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "minimax response"

        with patch("src.providers.minimax_client.get_minimax_client") as mock_client_factory:
            mock_client = MagicMock()
            mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
            mock_client_factory.return_value = mock_client

            cfg = TextGenerationConfig()
            result = await provider.generate_text("test prompt", cfg)

            assert result == "minimax response"

    async def test_text_generation_gemini_provider(self, monkeypatch):
        """generate_text routes through Gemini when explicitly opted-in."""
        monkeypatch.setenv("AI_PROVIDER", GEMINI)

        provider = get_provider(Feature.TEXT)

        # Mock the Gemini SDK call
        mock_response = MagicMock()
        mock_response.text = "gemini response"
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 5

        mock_client = MagicMock()
        mock_client.aio = MagicMock()
        mock_client.aio.models = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        # Patch at the right location where it's imported
        monkeypatch.setattr("src.providers.gemini.get_gemini_client", lambda: mock_client)

        cfg = TextGenerationConfig()
        result = await provider.generate_text("test prompt", cfg)

        assert result == "gemini response"

    async def test_reset_creates_new_instance(self, monkeypatch):
        """After _reset_for_tests, get_provider returns a new instance."""
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")

        provider1 = get_provider(Feature.TEXT)
        _reset_for_tests()
        provider2 = get_provider(Feature.TEXT)

        assert provider1 is not provider2
        assert provider1.name == provider2.name == MINIMAX

    async def test_multiple_features_same_provider(self, monkeypatch):
        """TEXT/IMAGE/FILE share the MiniMax singleton; VOICE is forced to Gemini."""
        monkeypatch.setenv("AI_PROVIDER", MINIMAX)
        monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")

        text = get_provider(Feature.TEXT)
        image = get_provider(Feature.IMAGE)
        file = get_provider(Feature.FILE)
        voice = get_provider(Feature.VOICE)

        # TEXT/IMAGE/FILE share one MiniMax instance; VOICE is hard-pinned to Gemini.
        assert text is image is file
        assert voice.name == GEMINI
        assert voice is not text


# Import for MagicMock reference
from unittest.mock import MagicMock
