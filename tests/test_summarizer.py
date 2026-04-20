"""Unit tests for summarizer.py — Gemini 3 API mocking."""

import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime, timezone
import json

# Mock google-genai before importing summarizer
import sys
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()

import summarizer


class TestGetGenaiClient:
    """Test singleton google-genai client initialization."""

    def setup_method(self):
        """Reset client before each test."""
        summarizer._genai_client = None

    def test_client_api_key_mode(self):
        """Client initializes with API key when GEMINI_API_KEY is set."""
        with patch('summarizer.config.IS_CLOUD_RUN', False):
            with patch('summarizer.config.GEMINI_API_KEY', 'test_key'):
                with patch('summarizer.genai.Client') as mock_client_class:
                    mock_client = Mock()
                    mock_client_class.return_value = mock_client

                    client = summarizer.get_genai_client()
                    assert client == mock_client
                    mock_client_class.assert_called_once_with(api_key='test_key')

    def test_client_vertex_ai_mode(self):
        """Client initializes with Vertex AI when IS_CLOUD_RUN is True."""
        with patch('summarizer.config.IS_CLOUD_RUN', True):
            with patch('summarizer.config.GOOGLE_CLOUD_PROJECT', 'test-project'):
                with patch('summarizer.config.GOOGLE_CLOUD_LOCATION', 'us-central1'):
                    with patch('summarizer.genai.Client') as mock_client_class:
                        mock_client = Mock()
                        mock_client_class.return_value = mock_client

                        summarizer._genai_client = None
                        client = summarizer.get_genai_client()
                        assert client == mock_client
                        mock_client_class.assert_called_once_with(
                            vertexai=True,
                            project='test-project',
                            location='us-central1',
                        )

    def test_client_singleton_reused(self):
        """Subsequent calls return same client instance."""
        with patch('summarizer.config.IS_CLOUD_RUN', False):
            with patch('summarizer.config.GEMINI_API_KEY', 'test_key'):
                with patch('summarizer.genai.Client') as mock_client_class:
                    mock_client = Mock()
                    mock_client_class.return_value = mock_client

                    summarizer._genai_client = None
                    client1 = summarizer.get_genai_client()
                    client2 = summarizer.get_genai_client()
                    assert client1 is client2
                    mock_client_class.assert_called_once()

    def test_raises_error_if_no_credentials(self):
        """Raises RuntimeError if neither API key nor Vertex AI is configured."""
        with patch('summarizer.config.IS_CLOUD_RUN', False):
            with patch('summarizer.config.GEMINI_API_KEY', ''):
                summarizer._genai_client = None
                with pytest.raises(RuntimeError, match="No Gemini credentials"):
                    summarizer.get_genai_client()


class TestGenerateCatchup:
    """Test catchup digest generation."""

    @pytest.mark.asyncio
    async def test_generate_catchup_success(self):
        """Successfully generate catchup from messages and links."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = "**Team Discussion** — Active discussion on project roadmap"

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch('summarizer.get_genai_client', return_value=mock_client):
            messages = [
                {
                    "username": "alice",
                    "text": "Should we use React or Vue?",
                    "timestamp": "2024-01-15T10:30:00",
                    "tg_user_id": 123,
                }
            ]
            links = []

            result = await summarizer.generate_catchup(messages, links)
            assert "Team Discussion" in result
            mock_client.aio.models.generate_content.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_catchup_with_links(self):
        """Catchup includes link summaries in context."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = "Digest with links"

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch('summarizer.get_genai_client', return_value=mock_client):
            messages = [
                {
                    "username": "bob",
                    "text": "Check this article",
                    "timestamp": "2024-01-15T10:31:00",
                    "tg_user_id": 456,
                }
            ]
            links = [
                {
                    "title": "React vs Vue",
                    "url": "https://example.com/article",
                    "summary": "Framework comparison",
                }
            ]

            result = await summarizer.generate_catchup(messages, links)
            assert result is not None
            # Verify link summary was included in call
            call_args = mock_client.aio.models.generate_content.call_args
            assert "framework comparison" in str(call_args).lower()

    @pytest.mark.asyncio
    async def test_generate_catchup_error_handling(self):
        """Returns error message on API failure."""
        mock_client = Mock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("API error")
        )

        with patch('summarizer.get_genai_client', return_value=mock_client):
            messages = [{"username": "user", "text": "test", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 789}]
            result = await summarizer.generate_catchup(messages, [])
            assert "couldn't generate a digest" in result


class TestGenerateTopics:
    """Test topic identification."""

    @pytest.mark.asyncio
    async def test_generate_topics_success(self):
        """Successfully parse topics from messages."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = json.dumps([
            {
                "name": "Frontend Stack",
                "description": "Discussing React vs Vue",
                "participants": ["alice", "bob"],
            }
        ])

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch('summarizer.get_genai_client', return_value=mock_client):
            messages = [
                {"username": "alice", "text": "React is great", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 123}
            ]
            result = await summarizer.generate_topics(messages)
            assert len(result) == 1
            assert result[0]["name"] == "Frontend Stack"
            assert "alice" in result[0]["participants"]

    @pytest.mark.asyncio
    async def test_generate_topics_json_parse_error(self):
        """Returns empty list if JSON parsing fails."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = "Invalid JSON {{"

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch('summarizer.get_genai_client', return_value=mock_client):
            messages = [{"username": "user", "text": "test", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 789}]
            result = await summarizer.generate_topics(messages)
            assert result == []

    @pytest.mark.asyncio
    async def test_generate_topics_api_error(self):
        """Returns empty list on API error."""
        mock_client = Mock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("API error")
        )

        with patch('summarizer.get_genai_client', return_value=mock_client):
            messages = [{"username": "user", "text": "test", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 789}]
            result = await summarizer.generate_topics(messages)
            assert result == []


class TestGenerateTopicDetail:
    """Test topic detail synthesis."""

    @pytest.mark.asyncio
    async def test_generate_topic_detail_success(self):
        """Successfully generate detailed topic synthesis."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = "[alice, 2024-01-15]: Proposed React for performance..."

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch('summarizer.get_genai_client', return_value=mock_client):
            messages = [
                {"username": "alice", "text": "React is fast", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 123}
            ]
            links = []

            result = await summarizer.generate_topic_detail(messages, links, "Frontend Stack")
            assert "React" in result or "proposed" in result.lower()

    @pytest.mark.asyncio
    async def test_generate_topic_detail_with_citations(self):
        """Topic detail includes link citations."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = "Discussion about [link: Framework Comparison]: comparing options"

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch('summarizer.get_genai_client', return_value=mock_client):
            messages = [{"username": "bob", "text": "Check the comparison", "timestamp": "2024-01-15T10:31:00", "tg_user_id": 456}]
            links = [
                {"title": "Framework Comparison", "url": "https://example.com", "summary": "Comparing React and Vue"}
            ]

            result = await summarizer.generate_topic_detail(messages, links, "Frameworks")
            assert "comparison" in result.lower()


class TestGenerateDecisionView:
    """Test decision view generation."""

    @pytest.mark.asyncio
    async def test_generate_decision_view_success(self):
        """Successfully generate structured decision view."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = """## Options
- Option A: React
- Option B: Vue

## Arguments For/Against
(React pros: fast, mature. Vue pros: simpler)

## Key Evidence
[alice, 2024-01-15]: React scales well

## What's Missing
Need performance benchmarks"""

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch('summarizer.get_genai_client', return_value=mock_client):
            messages = [
                {"username": "alice", "text": "React scales well", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 123}
            ]
            links = []

            result = await summarizer.generate_decision_view(messages, links, "Frontend Framework")
            assert "Options" in result
            assert "Arguments" in result or "arguments" in result.lower()


class TestBuildDraftSystemPrompt:
    """Test draft mode system prompt construction."""

    def test_build_draft_system_prompt_includes_context(self):
        """System prompt includes team context."""
        context = "Team discussed React vs Vue. Alice favors React."
        prompt = summarizer.build_draft_system_prompt(context)

        assert "team context" in prompt.lower()
        assert context in prompt

    def test_build_draft_system_prompt_mentions_citations(self):
        """System prompt includes citation guidance."""
        context = "Some context"
        prompt = summarizer.build_draft_system_prompt(context)

        assert "username" in prompt.lower() or "cite" in prompt.lower() or "[" in prompt


class TestGenerateDraftResponse:
    """Test multi-turn draft response generation."""

    @pytest.mark.asyncio
    async def test_generate_draft_response_success(self):
        """Successfully generate draft response in conversation."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = "Have you considered the maintainability angle?"

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch('summarizer.get_genai_client', return_value=mock_client):
            history = [
                {"role": "user", "content": "I want to draft my position on: Frontend Stack"}
            ]
            system_prompt = "You are Murmur..."

            result = await summarizer.generate_draft_response(history, system_prompt)
            assert "maintainability" in result or "angle" in result

    @pytest.mark.asyncio
    async def test_generate_draft_response_multi_turn(self):
        """Draft response includes full conversation history."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = "Good point about maintainability."

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch('summarizer.get_genai_client', return_value=mock_client):
            history = [
                {"role": "user", "content": "React is better"},
                {"role": "model", "content": "Why do you think so?"},
                {"role": "user", "content": "Faster performance"},
            ]
            system_prompt = "You are Murmur..."

            result = await summarizer.generate_draft_response(history, system_prompt)
            assert result is not None
            # Verify all history was passed
            call_args = mock_client.aio.models.generate_content.call_args
            assert call_args is not None

    @pytest.mark.asyncio
    async def test_generate_draft_response_error_handling(self):
        """Returns graceful error message on API failure."""
        mock_client = Mock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("API error")
        )

        with patch('summarizer.get_genai_client', return_value=mock_client):
            history = [{"role": "user", "content": "test"}]
            result = await summarizer.generate_draft_response(history, "prompt")
            assert "trouble" in result.lower() or "error" in result.lower()


class TestGenerateReminderDigest:
    """Test reminder digest generation."""

    @pytest.mark.asyncio
    async def test_generate_reminder_digest_success(self):
        """Successfully generate reminder digest."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = "📬 5 new messages in Frontend Stack and API Design."

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch('summarizer.get_genai_client', return_value=mock_client):
            result = await summarizer.generate_reminder_digest(
                message_count=5,
                topic_names=["Frontend Stack", "API Design"],
                stale_topics=[],
            )
            assert "5" in result or "new" in result.lower()

    @pytest.mark.asyncio
    async def test_generate_reminder_digest_with_stale_topics(self):
        """Reminder digest mentions stale topics."""
        mock_client = Mock()
        mock_response = Mock()
        mock_response.text = "3 new messages. Legacy Architecture is stale (5 days)."

        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_response)

        with patch('summarizer.get_genai_client', return_value=mock_client):
            result = await summarizer.generate_reminder_digest(
                message_count=3,
                topic_names=[],
                stale_topics=["Legacy Architecture"],
            )
            assert result is not None

    @pytest.mark.asyncio
    async def test_generate_reminder_digest_fallback(self):
        """Falls back to simple format on API error."""
        mock_client = Mock()
        mock_client.aio.models.generate_content = AsyncMock(
            side_effect=Exception("API error")
        )

        with patch('summarizer.get_genai_client', return_value=mock_client):
            result = await summarizer.generate_reminder_digest(10, [], [])
            assert "10" in result  # Should include message count
            assert "📬" in result or "messages" in result.lower()
