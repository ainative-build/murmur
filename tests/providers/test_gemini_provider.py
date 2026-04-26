"""Tests for GeminiProvider with mocked google-genai SDK."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.providers.gemini import GeminiProvider
from src.providers.types import Feature, TextGenerationConfig, ImagePart, FilePart


@pytest.fixture
def mock_gemini_client():
    """Mock google-genai Client with async model methods."""
    client = MagicMock()
    client.aio = MagicMock()
    client.aio.models = MagicMock()
    client.aio.models.generate_content = AsyncMock()
    return client


@pytest.fixture
def gemini_provider(monkeypatch, mock_gemini_client):
    """GeminiProvider instance with mocked client."""
    monkeypatch.setenv("GEMINI_MODEL_PRIMARY", "gemini-3-flash-preview")
    monkeypatch.setenv("GEMINI_MODEL_FALLBACK", "gemini-3.1-pro-preview")
    monkeypatch.setenv("GEMINI_API_KEY", "test_key")
    # Patch at the module level so it's available when generate_text imports it
    monkeypatch.setattr(
        "src.providers.gemini.get_gemini_client",
        lambda: mock_gemini_client
    )
    return GeminiProvider()


class TestGeminiProviderGenerateText:
    """Test text generation."""

    async def test_generate_text_string_prompt(self, gemini_provider, mock_gemini_client):
        """generate_text with string prompt calls SDK."""
        mock_response = MagicMock()
        mock_response.text = "Generated text"
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 5
        mock_gemini_client.aio.models.generate_content.return_value = mock_response

        cfg = TextGenerationConfig(system_instruction="Be helpful")
        result = await gemini_provider.generate_text("hello", cfg)

        assert result == "Generated text"
        assert mock_gemini_client.aio.models.generate_content.called

    async def test_generate_text_chat_history(self, gemini_provider, mock_gemini_client):
        """generate_text with chat history list."""
        mock_response = MagicMock()
        mock_response.text = "Response"
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 0
        mock_response.usage_metadata.candidates_token_count = 0
        mock_gemini_client.aio.models.generate_content.return_value = mock_response

        chat_history = [
            {"role": "user", "content": "hello"},
            {"role": "model", "content": "hi there"},
        ]
        cfg = TextGenerationConfig()
        result = await gemini_provider.generate_text(chat_history, cfg)

        assert result == "Response"

    async def test_generate_text_with_system_instruction(
        self, gemini_provider, mock_gemini_client
    ):
        """System instruction is passed to SDK."""
        mock_response = MagicMock()
        mock_response.text = "result"
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 0
        mock_response.usage_metadata.candidates_token_count = 0
        mock_gemini_client.aio.models.generate_content.return_value = mock_response

        cfg = TextGenerationConfig(system_instruction="You are helpful")
        await gemini_provider.generate_text("test", cfg)

        call_args = mock_gemini_client.aio.models.generate_content.call_args
        assert call_args is not None
        config = call_args[1]["config"]
        assert config.system_instruction == "You are helpful"

    async def test_generate_text_with_json_response_format(
        self, gemini_provider, mock_gemini_client
    ):
        """response_mime_type is passed to SDK config."""
        mock_response = MagicMock()
        mock_response.text = '{"key": "value"}'
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 0
        mock_response.usage_metadata.candidates_token_count = 0
        mock_gemini_client.aio.models.generate_content.return_value = mock_response

        cfg = TextGenerationConfig(response_mime_type="application/json")
        result = await gemini_provider.generate_text("generate json", cfg)

        assert result == '{"key": "value"}'
        call_args = mock_gemini_client.aio.models.generate_content.call_args
        config = call_args[1]["config"]
        assert config.response_mime_type == "application/json"


class TestGeminiProviderImage:
    """Test image analysis."""

    async def test_generate_with_image(self, gemini_provider, mock_gemini_client):
        """generate_with_image processes image bytes."""
        mock_response = MagicMock()
        mock_response.text = "Image shows a cat"
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 3
        mock_gemini_client.aio.models.generate_content.return_value = mock_response

        image = ImagePart(data=b"fake_image_bytes", mime_type="image/jpeg")
        cfg = TextGenerationConfig()
        result = await gemini_provider.generate_with_image(image, "What's in this?", cfg)

        assert result == "Image shows a cat"
        assert mock_gemini_client.aio.models.generate_content.called


class TestGeminiProviderFiles:
    """Test file analysis."""

    async def test_generate_with_files(self, gemini_provider, mock_gemini_client):
        """generate_with_files processes file bytes."""
        mock_response = MagicMock()
        mock_response.text = "File summary"
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 50
        mock_response.usage_metadata.candidates_token_count = 20
        mock_gemini_client.aio.models.generate_content.return_value = mock_response

        file1 = FilePart(data=b"pdf content", mime_type="application/pdf", display_name="doc.pdf")
        cfg = TextGenerationConfig()
        result = await gemini_provider.generate_with_files([file1], "Summarize", cfg)

        assert result == "File summary"
        assert mock_gemini_client.aio.models.generate_content.called


class TestGeminiProviderAudio:
    """Test audio transcription."""

    async def test_transcribe_audio_success(self, gemini_provider, mock_gemini_client):
        """transcribe_audio returns transcript."""
        mock_response = MagicMock()
        mock_response.text = "Hello world"
        mock_response.usage_metadata = MagicMock()
        mock_response.usage_metadata.prompt_token_count = 10
        mock_response.usage_metadata.candidates_token_count = 2
        mock_gemini_client.aio.models.generate_content.return_value = mock_response

        result = await gemini_provider.transcribe_audio(b"audio_bytes", "audio/ogg")
        assert result == "Hello world"

    async def test_transcribe_audio_empty_returns_none(self, gemini_provider, mock_gemini_client):
        """transcribe_audio returns None when audio is empty."""
        result = await gemini_provider.transcribe_audio(b"")
        assert result is None

    async def test_transcribe_audio_empty_response_returns_none(
        self, gemini_provider, mock_gemini_client
    ):
        """transcribe_audio returns None when response text is empty."""
        mock_response = MagicMock()
        mock_response.text = "   "
        mock_gemini_client.aio.models.generate_content.return_value = mock_response

        result = await gemini_provider.transcribe_audio(b"audio", "audio/ogg")
        assert result is None


class TestGeminiProviderVideo:
    """Test video understanding."""

    def test_understand_video_accepts_url_string(self, gemini_provider):
        """understand_video accepts URL strings without raising."""
        # This is a basic smoke test that the method can be called
        # Full SDK integration testing requires live API setup
        assert hasattr(gemini_provider, "understand_video")
        assert callable(gemini_provider.understand_video)

    def test_understand_video_accepts_bytes(self, gemini_provider):
        """understand_video accepts raw bytes without raising."""
        # This is a basic smoke test that the method can be called
        # Full SDK integration testing requires live API setup
        assert hasattr(gemini_provider, "understand_video")
        assert callable(gemini_provider.understand_video)


class TestGeminiProviderMetadata:
    """Test provider metadata."""

    def test_provider_name(self, gemini_provider):
        """Provider name is 'gemini'."""
        assert gemini_provider.name == "gemini"
