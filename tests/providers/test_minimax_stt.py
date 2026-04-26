"""Tests for MiniMax Speech-to-Text submit-then-poll pattern."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.providers.minimax_stt import transcribe_via_stt, STT_POLL_DEADLINE_S


@pytest.fixture
def mock_stt_client():
    """Mock httpx.AsyncClient for STT endpoints."""
    client = MagicMock()
    client.post = AsyncMock()
    client.get = AsyncMock()
    return client


class TestTranscribeViaStt:
    """Test submit-then-poll STT transcription."""

    async def test_happy_path_success_status(self, mock_stt_client):
        """Happy path: POST returns generation_id, GET returns success with text."""
        # POST /stt/create response
        post_response = MagicMock()
        post_response.json.return_value = {"generation_id": "abc123"}
        mock_stt_client.post.return_value = post_response

        # GET /stt/abc123 response with success
        get_response = MagicMock()
        get_response.json.return_value = {"status": "success", "text": "hello world"}
        mock_stt_client.get.return_value = get_response

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            result = await transcribe_via_stt(b"audio_data", "audio/ogg")

        assert result == "hello world"
        mock_stt_client.post.assert_called_once()
        mock_stt_client.get.assert_called_once()

    async def test_transcript_field_alternative(self, mock_stt_client):
        """GET response with 'transcript' field (alternative to 'text')."""
        post_response = MagicMock()
        post_response.json.return_value = {"generation_id": "xyz789"}
        mock_stt_client.post.return_value = post_response

        get_response = MagicMock()
        get_response.json.return_value = {"status": "completed", "transcript": "test transcript"}
        mock_stt_client.get.return_value = get_response

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            result = await transcribe_via_stt(b"audio", "audio/mp3")

        assert result == "test transcript"

    async def test_result_field_alternative(self, mock_stt_client):
        """GET response with 'result' field (alternative to 'text')."""
        post_response = MagicMock()
        post_response.json.return_value = {"id": "gen_456"}
        mock_stt_client.post.return_value = post_response

        get_response = MagicMock()
        get_response.json.return_value = {"status": "done", "result": "recognized speech"}
        mock_stt_client.get.return_value = get_response

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            result = await transcribe_via_stt(b"audio", "audio/wav")

        assert result == "recognized speech"

    async def test_whitespace_stripped(self, mock_stt_client):
        """Transcript is stripped of surrounding whitespace."""
        post_response = MagicMock()
        post_response.json.return_value = {"generation_id": "abc"}
        mock_stt_client.post.return_value = post_response

        get_response = MagicMock()
        get_response.json.return_value = {"status": "success", "text": "  hello world  "}
        mock_stt_client.get.return_value = get_response

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            result = await transcribe_via_stt(b"audio", "audio/ogg")

        assert result == "hello world"

    async def test_empty_transcript_returns_none(self, mock_stt_client):
        """Empty or None transcript returns None."""
        post_response = MagicMock()
        post_response.json.return_value = {"generation_id": "abc"}
        mock_stt_client.post.return_value = post_response

        get_response = MagicMock()
        get_response.json.return_value = {"status": "success", "text": None}
        mock_stt_client.get.return_value = get_response

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            result = await transcribe_via_stt(b"audio", "audio/ogg")

        assert result is None

    async def test_failed_status_returns_none(self, mock_stt_client):
        """GET returns status='failed' → returns None."""
        post_response = MagicMock()
        post_response.json.return_value = {"generation_id": "abc"}
        mock_stt_client.post.return_value = post_response

        get_response = MagicMock()
        get_response.json.return_value = {"status": "failed", "error": "audio too noisy"}
        mock_stt_client.get.return_value = get_response

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            result = await transcribe_via_stt(b"audio", "audio/ogg")

        assert result is None

    async def test_error_status_returns_none(self, mock_stt_client):
        """GET returns status='error' → returns None."""
        post_response = MagicMock()
        post_response.json.return_value = {"generation_id": "abc"}
        mock_stt_client.post.return_value = post_response

        get_response = MagicMock()
        get_response.json.return_value = {"status": "error"}
        mock_stt_client.get.return_value = get_response

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            result = await transcribe_via_stt(b"audio", "audio/ogg")

        assert result is None

    async def test_polling_pending_then_success(self, mock_stt_client):
        """Polling: first GET returns pending, second returns success."""
        post_response = MagicMock()
        post_response.json.return_value = {"generation_id": "abc"}
        mock_stt_client.post.return_value = post_response

        pending_response = MagicMock()
        pending_response.json.return_value = {"status": "pending"}

        success_response = MagicMock()
        success_response.json.return_value = {"status": "success", "text": "final result"}

        # First GET: pending, second GET: success
        mock_stt_client.get.side_effect = [pending_response, success_response]

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            result = await transcribe_via_stt(b"audio", "audio/ogg")

        assert result == "final result"
        assert mock_stt_client.get.call_count == 2

    async def test_timeout_exceeds_deadline(self, monkeypatch, mock_stt_client):
        """Timeout: polling exceeds 30s deadline → raises TimeoutError."""
        post_response = MagicMock()
        post_response.json.return_value = {"generation_id": "abc"}
        mock_stt_client.post.return_value = post_response

        pending_response = MagicMock()
        pending_response.json.return_value = {"status": "processing"}
        mock_stt_client.get.return_value = pending_response

        # Simulate time advancing: deadline is at 30s, so return times that exceed it
        # monotonic is called at deadline calc (0.0) and in the loop (0.0, then 31.0)
        times = [0.0, 0.0, 31.0, 31.0, 31.0]
        time_calls = iter(times)

        def fake_monotonic():
            return next(time_calls)

        monkeypatch.setattr("time.monotonic", fake_monotonic)

        # Disable sleep to speed up test
        async def fake_sleep(d):
            pass

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            with pytest.raises(TimeoutError, match="polling exceeded"):
                await transcribe_via_stt(b"audio", "audio/ogg")

    async def test_missing_generation_id_returns_none(self, mock_stt_client):
        """POST response missing generation_id → returns None."""
        post_response = MagicMock()
        post_response.json.return_value = {}  # No generation_id or id
        mock_stt_client.post.return_value = post_response

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            result = await transcribe_via_stt(b"audio", "audio/ogg")

        assert result is None
        # Should not call GET if POST didn't return a generation_id
        mock_stt_client.get.assert_not_called()

    async def test_default_mime_type(self, mock_stt_client):
        """Default mime type is audio/ogg."""
        post_response = MagicMock()
        post_response.json.return_value = {"generation_id": "abc"}
        mock_stt_client.post.return_value = post_response

        get_response = MagicMock()
        get_response.json.return_value = {"status": "success", "text": "result"}
        mock_stt_client.get.return_value = get_response

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            await transcribe_via_stt(b"audio")

        # Verify POST was called (no exception on default mime)
        assert mock_stt_client.post.called

    async def test_status_case_insensitive(self, mock_stt_client):
        """Status comparison is case-insensitive."""
        post_response = MagicMock()
        post_response.json.return_value = {"generation_id": "abc"}
        mock_stt_client.post.return_value = post_response

        get_response = MagicMock()
        get_response.json.return_value = {"status": "SUCCESS", "text": "result"}
        mock_stt_client.get.return_value = get_response

        with patch("src.providers.minimax_client.get_stt_client", return_value=mock_stt_client):
            result = await transcribe_via_stt(b"audio", "audio/ogg")

        assert result == "result"
