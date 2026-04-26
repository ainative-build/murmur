"""Tests for MiniMaxProvider with mocked OpenAI SDK."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import base64

from src.providers.minimax import MiniMaxProvider
from src.providers.types import (
    Feature,
    TextGenerationConfig,
    ImagePart,
    FilePart,
    NotSupportedError,
)


@pytest.fixture
def mock_minimax_client():
    """Mock AsyncOpenAI client for MiniMax."""
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock()
    client.files = MagicMock()
    client.files.create = AsyncMock()
    return client


@pytest.fixture
def minimax_provider(monkeypatch, mock_minimax_client):
    """MiniMaxProvider instance with mocked client."""
    monkeypatch.setenv("MINIMAX_API_KEY", "fake_key")
    monkeypatch.setenv("MINIMAX_MODEL", "minimax-m2.7")
    monkeypatch.setattr("src.providers.minimax_client.get_minimax_client", lambda: mock_minimax_client)
    return MiniMaxProvider()


class TestMiniMaxProviderGenerateText:
    """Test text generation."""

    async def test_generate_text_string_prompt(self, minimax_provider, mock_minimax_client):
        """generate_text with string prompt calls SDK."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message = MagicMock()
        mock_response.choices[0].message.content = "Generated text"
        mock_minimax_client.chat.completions.create.return_value = mock_response

        cfg = TextGenerationConfig(system_instruction="Be helpful")
        result = await minimax_provider.generate_text("hello", cfg)

        assert result == "Generated text"
        assert mock_minimax_client.chat.completions.create.called

    async def test_generate_text_chat_history(self, minimax_provider, mock_minimax_client):
        """generate_text with chat history list."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Response"
        mock_minimax_client.chat.completions.create.return_value = mock_response

        chat_history = [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "hi there"},
        ]
        cfg = TextGenerationConfig()
        result = await minimax_provider.generate_text(chat_history, cfg)

        assert result == "Response"

    async def test_generate_text_with_system_instruction(
        self, minimax_provider, mock_minimax_client
    ):
        """System instruction is included in messages."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "result"
        mock_minimax_client.chat.completions.create.return_value = mock_response

        cfg = TextGenerationConfig(system_instruction="You are helpful")
        await minimax_provider.generate_text("test", cfg)

        call_args = mock_minimax_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "You are helpful"

    async def test_generate_text_temperature_zero_clamped(
        self, minimax_provider, mock_minimax_client
    ):
        """Temperature 0.0 is clamped to 0.01 minimum."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "result"
        mock_minimax_client.chat.completions.create.return_value = mock_response

        cfg = TextGenerationConfig(temperature=0.0)
        await minimax_provider.generate_text("test", cfg)

        call_args = mock_minimax_client.chat.completions.create.call_args
        temperature = call_args[1]["temperature"]
        assert temperature >= 0.01

    async def test_generate_text_temperature_preserved(
        self, minimax_provider, mock_minimax_client
    ):
        """Non-zero temperature is preserved."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "result"
        mock_minimax_client.chat.completions.create.return_value = mock_response

        cfg = TextGenerationConfig(temperature=0.7)
        await minimax_provider.generate_text("test", cfg)

        call_args = mock_minimax_client.chat.completions.create.call_args
        assert call_args[1]["temperature"] == 0.7

    async def test_generate_text_json_response_format(
        self, minimax_provider, mock_minimax_client
    ):
        """response_mime_type='application/json' sets response_format."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"key": "value"}'
        mock_minimax_client.chat.completions.create.return_value = mock_response

        cfg = TextGenerationConfig(response_mime_type="application/json")
        result = await minimax_provider.generate_text("generate json", cfg)

        call_args = mock_minimax_client.chat.completions.create.call_args
        assert call_args[1]["response_format"] == {"type": "json_object"}
        assert result == '{"key": "value"}'

    async def test_generate_text_max_tokens_passed(
        self, minimax_provider, mock_minimax_client
    ):
        """max_output_tokens is passed to SDK."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "result"
        mock_minimax_client.chat.completions.create.return_value = mock_response

        cfg = TextGenerationConfig(max_output_tokens=2048)
        await minimax_provider.generate_text("test", cfg)

        call_args = mock_minimax_client.chat.completions.create.call_args
        assert call_args[1]["max_tokens"] == 2048

    async def test_generate_text_stream_false(self, minimax_provider, mock_minimax_client):
        """stream parameter is always False."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "result"
        mock_minimax_client.chat.completions.create.return_value = mock_response

        cfg = TextGenerationConfig()
        await minimax_provider.generate_text("test", cfg)

        call_args = mock_minimax_client.chat.completions.create.call_args
        assert call_args[1]["stream"] is False


class TestMiniMaxProviderImage:
    """Test image analysis."""

    async def test_generate_with_image(self, minimax_provider, mock_minimax_client):
        """generate_with_image encodes image as base64 data URI."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Image shows a cat"
        mock_minimax_client.chat.completions.create.return_value = mock_response

        image = ImagePart(data=b"fake_jpeg_data", mime_type="image/jpeg")
        cfg = TextGenerationConfig()
        result = await minimax_provider.generate_with_image(image, "What's in this?", cfg)

        assert result == "Image shows a cat"

        call_args = mock_minimax_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        user_msg = messages[-1]
        assert user_msg["role"] == "user"
        content = user_msg["content"]
        assert any(part["type"] == "image_url" for part in content)

    async def test_generate_with_image_data_uri(self, minimax_provider, mock_minimax_client):
        """Image is encoded as data:mime_type;base64,... URI."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "result"
        mock_minimax_client.chat.completions.create.return_value = mock_response

        image_data = b"test_image"
        image = ImagePart(data=image_data, mime_type="image/png")
        cfg = TextGenerationConfig()
        await minimax_provider.generate_with_image(image, "analyze", cfg)

        call_args = mock_minimax_client.chat.completions.create.call_args
        messages = call_args[1]["messages"]
        user_msg = messages[-1]
        content = user_msg["content"]
        image_part = next(p for p in content if p["type"] == "image_url")
        uri = image_part["image_url"]["url"]
        assert uri.startswith("data:image/png;base64,")
        expected_b64 = base64.b64encode(image_data).decode()
        assert uri == f"data:image/png;base64,{expected_b64}"


class TestMiniMaxProviderFiles:
    """Test file analysis."""

    async def test_generate_with_files_small(self, minimax_provider, mock_minimax_client):
        """generate_with_files with small file inlines as base64."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Summary"
        mock_minimax_client.chat.completions.create.return_value = mock_response

        file_data = b"small pdf content"
        file = FilePart(data=file_data, mime_type="application/pdf", display_name="doc.pdf")
        cfg = TextGenerationConfig()
        result = await minimax_provider.generate_with_files([file], "Summarize", cfg)

        assert result == "Summary"
        assert mock_minimax_client.chat.completions.create.called

    async def test_generate_with_files_large_upload(
        self, minimax_provider, mock_minimax_client
    ):
        """generate_with_files with large file uploads via Files API."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = "Summary"
        mock_minimax_client.chat.completions.create.return_value = mock_response

        file_result = MagicMock()
        file_result.id = "file_123"
        mock_minimax_client.files.create.return_value = file_result

        # Create a file larger than 5MB limit
        large_data = b"x" * (6 * 1024 * 1024)
        file = FilePart(data=large_data, mime_type="application/pdf", display_name="large.pdf")
        cfg = TextGenerationConfig()
        result = await minimax_provider.generate_with_files([file], "Summarize", cfg)

        assert result == "Summary"
        assert mock_minimax_client.files.create.called


class TestMiniMaxProviderAudio:
    """Test audio transcription."""

    async def test_transcribe_audio_delegates_to_stt(self, minimax_provider):
        """transcribe_audio delegates to minimax_stt.transcribe_via_stt."""
        with patch("src.providers.minimax_stt.transcribe_via_stt", new_callable=AsyncMock) as mock_stt:
            mock_stt.return_value = "Hello world"
            result = await minimax_provider.transcribe_audio(b"audio_bytes", "audio/ogg")
            assert result == "Hello world"
            mock_stt.assert_called_once_with(b"audio_bytes", "audio/ogg")


class TestMiniMaxProviderVideo:
    """Test video understanding."""

    async def test_understand_video_raises_not_supported(self, minimax_provider):
        """understand_video raises NotSupportedError."""
        with pytest.raises(NotSupportedError, match="MiniMax does not support video"):
            await minimax_provider.understand_video(b"video", "analyze")

    async def test_understand_video_url_raises_not_supported(self, minimax_provider):
        """understand_video with URL raises NotSupportedError."""
        with pytest.raises(NotSupportedError, match="MiniMax does not support video"):
            await minimax_provider.understand_video("https://example.com/video.mp4", "analyze")


class TestMiniMaxProviderMetadata:
    """Test provider metadata."""

    def test_provider_name(self, minimax_provider):
        """Provider name is 'minimax'."""
        assert minimax_provider.name == "minimax"
