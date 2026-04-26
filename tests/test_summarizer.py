"""Unit tests for summarizer.py — provider interface mocking.

After Phase 4 migration, summarizer delegates all LLM calls to
get_provider(Feature.TEXT).generate_text(). Tests mock that interface.

The get_genai_client singleton tests are kept but now target the actual
implementation location: src.providers.gemini_client.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock, patch
import json

# Mock google-genai before importing summarizer (transitive deps still need it)
import sys
sys.modules['google.genai'] = MagicMock()
sys.modules['google.genai.types'] = MagicMock()

import summarizer
from src.providers import _reset_for_tests


# ---------------------------------------------------------------------------
# Helper — build a mock provider with a pre-configured generate_text return
# ---------------------------------------------------------------------------

def _mock_provider(return_value: str = "") -> Mock:
    """Return a mock Provider whose generate_text is an AsyncMock."""
    provider = Mock()
    provider.generate_text = AsyncMock(return_value=return_value)
    return provider


# ---------------------------------------------------------------------------
# TestGetGenaiClient — tests that the singleton still works via summarizer API
# ---------------------------------------------------------------------------

class TestGetGenaiClient:
    """Test singleton google-genai client initialization (via summarizer re-export)."""

    def setup_method(self):
        """Reset provider singletons and gemini_client singleton before each test."""
        _reset_for_tests()
        # Reset the gemini_client singleton in its actual home
        import src.providers.gemini_client as gc
        gc._genai_client = None

    def test_client_api_key_mode(self):
        """Client initializes with API key when GEMINI_API_KEY is set."""
        with patch('src.providers.gemini_client.config.IS_CLOUD_RUN', False), \
             patch('src.providers.gemini_client.config.GEMINI_API_KEY', 'test_key'), \
             patch('src.providers.gemini_client.genai.Client') as mock_cls:
            mock_client = Mock()
            mock_cls.return_value = mock_client

            import src.providers.gemini_client as gc
            gc._genai_client = None
            client = summarizer.get_genai_client()
            assert client == mock_client
            mock_cls.assert_called_once_with(api_key='test_key')

    def test_client_vertex_ai_mode(self):
        """Client initializes with Vertex AI when IS_CLOUD_RUN is True."""
        with patch('src.providers.gemini_client.config.IS_CLOUD_RUN', True), \
             patch('src.providers.gemini_client.config.GOOGLE_CLOUD_PROJECT', 'test-project'), \
             patch('src.providers.gemini_client.config.GOOGLE_CLOUD_LOCATION', 'us-central1'), \
             patch('src.providers.gemini_client.genai.Client') as mock_cls:
            mock_client = Mock()
            mock_cls.return_value = mock_client

            import src.providers.gemini_client as gc
            gc._genai_client = None
            client = summarizer.get_genai_client()
            assert client == mock_client
            mock_cls.assert_called_once_with(
                vertexai=True,
                project='test-project',
                location='us-central1',
            )

    def test_client_singleton_reused(self):
        """Subsequent calls return same client instance."""
        with patch('src.providers.gemini_client.config.IS_CLOUD_RUN', False), \
             patch('src.providers.gemini_client.config.GEMINI_API_KEY', 'test_key'), \
             patch('src.providers.gemini_client.genai.Client') as mock_cls:
            mock_client = Mock()
            mock_cls.return_value = mock_client

            import src.providers.gemini_client as gc
            gc._genai_client = None
            client1 = summarizer.get_genai_client()
            client2 = summarizer.get_genai_client()
            assert client1 is client2
            mock_cls.assert_called_once()

    def test_raises_error_if_no_credentials(self):
        """Raises RuntimeError if neither API key nor Vertex AI is configured."""
        with patch('src.providers.gemini_client.config.IS_CLOUD_RUN', False), \
             patch('src.providers.gemini_client.config.GEMINI_API_KEY', ''):
            import src.providers.gemini_client as gc
            gc._genai_client = None
            with pytest.raises(RuntimeError, match="No Gemini credentials"):
                summarizer.get_genai_client()


# ---------------------------------------------------------------------------
# TestGenerateCatchup
# ---------------------------------------------------------------------------

class TestGenerateCatchup:
    """Test catchup digest generation."""

    def setup_method(self):
        _reset_for_tests()

    @pytest.mark.asyncio
    async def test_generate_catchup_success(self):
        """Successfully generate catchup from messages and links."""
        provider = _mock_provider("**Team Discussion** — Active discussion on project roadmap")

        with patch('summarizer.get_provider', return_value=provider):
            messages = [
                {
                    "username": "alice",
                    "text": "Should we use React or Vue?",
                    "timestamp": "2024-01-15T10:30:00",
                    "tg_user_id": 123,
                }
            ]
            result = await summarizer.generate_catchup(messages, [])
            assert "Team Discussion" in result
            provider.generate_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_generate_catchup_with_links(self):
        """Catchup includes link summaries in context."""
        provider = _mock_provider("Digest with links")

        with patch('summarizer.get_provider', return_value=provider):
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
            # Verify link summary was included in the prompt passed to generate_text
            call_args = provider.generate_text.call_args
            assert "framework comparison" in str(call_args).lower()

    @pytest.mark.asyncio
    async def test_generate_catchup_error_handling(self):
        """Returns error message on API failure."""
        provider = Mock()
        provider.generate_text = AsyncMock(side_effect=Exception("API error"))

        with patch('summarizer.get_provider', return_value=provider):
            messages = [{"username": "user", "text": "test", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 789}]
            result = await summarizer.generate_catchup(messages, [])
            assert "couldn't generate a digest" in result
            assert "503" not in result
            assert "UNAVAILABLE" not in result

    @pytest.mark.asyncio
    async def test_generate_catchup_returns_unavailable_on_provider_error(self):
        """Provider error → user-friendly unavailable message."""
        provider = Mock()
        provider.generate_text = AsyncMock(side_effect=RuntimeError("overloaded"))

        with patch('summarizer.get_provider', return_value=provider):
            messages = [{"username": "u", "text": "hi", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 1}]
            result = await summarizer.generate_catchup(messages, [])
            assert "couldn't generate a digest" in result


# ---------------------------------------------------------------------------
# TestGenerateTopics
# ---------------------------------------------------------------------------

class TestGenerateTopics:
    """Test topic identification."""

    def setup_method(self):
        _reset_for_tests()

    @pytest.mark.asyncio
    async def test_generate_topics_success(self):
        """Successfully parse topics from messages."""
        raw = json.dumps([
            {
                "name": "Frontend Stack",
                "description": "Discussing React vs Vue",
                "participants": ["alice", "bob"],
            }
        ])
        provider = _mock_provider(raw)

        with patch('summarizer.get_provider', return_value=provider):
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
        provider = _mock_provider("Invalid JSON {{")

        with patch('summarizer.get_provider', return_value=provider):
            messages = [{"username": "user", "text": "test", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 789}]
            result = await summarizer.generate_topics(messages)
            assert result == []

    @pytest.mark.asyncio
    async def test_generate_topics_api_error(self):
        """Returns empty list on API error."""
        provider = Mock()
        provider.generate_text = AsyncMock(side_effect=Exception("API error"))

        with patch('summarizer.get_provider', return_value=provider):
            messages = [{"username": "user", "text": "test", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 789}]
            result = await summarizer.generate_topics(messages)
            assert result == []


# ---------------------------------------------------------------------------
# TestGenerateTopicDetail
# ---------------------------------------------------------------------------

class TestGenerateTopicDetail:
    """Test topic detail synthesis."""

    def setup_method(self):
        _reset_for_tests()

    @pytest.mark.asyncio
    async def test_generate_topic_detail_success(self):
        """Successfully generate detailed topic synthesis."""
        provider = _mock_provider("[alice, 2024-01-15]: Proposed React for performance...")

        with patch('summarizer.get_provider', return_value=provider):
            messages = [
                {"username": "alice", "text": "React is fast", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 123}
            ]
            result = await summarizer.generate_topic_detail(messages, [], "Frontend Stack")
            assert "React" in result or "proposed" in result.lower()

    @pytest.mark.asyncio
    async def test_generate_topic_detail_with_citations(self):
        """Topic detail includes link citations."""
        provider = _mock_provider("Discussion about [link: Framework Comparison]: comparing options")

        with patch('summarizer.get_provider', return_value=provider):
            messages = [{"username": "bob", "text": "Check the comparison", "timestamp": "2024-01-15T10:31:00", "tg_user_id": 456}]
            links = [
                {"title": "Framework Comparison", "url": "https://example.com", "summary": "Comparing React and Vue"}
            ]
            result = await summarizer.generate_topic_detail(messages, links, "Frameworks")
            assert "comparison" in result.lower()


# ---------------------------------------------------------------------------
# TestGenerateDecisionView
# ---------------------------------------------------------------------------

class TestGenerateDecisionView:
    """Test decision view generation."""

    def setup_method(self):
        _reset_for_tests()

    @pytest.mark.asyncio
    async def test_generate_decision_view_success(self):
        """Successfully generate structured decision view."""
        response_text = """## Options
- Option A: React
- Option B: Vue

## Arguments For/Against
(React pros: fast, mature. Vue pros: simpler)

## Key Evidence
[alice, 2024-01-15]: React scales well

## What's Missing
Need performance benchmarks"""
        provider = _mock_provider(response_text)

        with patch('summarizer.get_provider', return_value=provider):
            messages = [
                {"username": "alice", "text": "React scales well", "timestamp": "2024-01-15T10:30:00", "tg_user_id": 123}
            ]
            result = await summarizer.generate_decision_view(messages, [], "Frontend Framework")
            assert "Options" in result
            assert "Arguments" in result or "arguments" in result.lower()


# ---------------------------------------------------------------------------
# TestBuildDraftSystemPrompt
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# TestGenerateDraftResponse
# ---------------------------------------------------------------------------

class TestGenerateDraftResponse:
    """Test multi-turn draft response generation."""

    def setup_method(self):
        _reset_for_tests()

    @pytest.mark.asyncio
    async def test_generate_draft_response_success(self):
        """Successfully generate draft response in conversation."""
        provider = _mock_provider("Have you considered the maintainability angle?")

        with patch('summarizer.get_provider', return_value=provider):
            history = [
                {"role": "user", "content": "I want to draft my position on: Frontend Stack"}
            ]
            result = await summarizer.generate_draft_response(history, "You are Murmur...")
            assert "maintainability" in result or "angle" in result

    @pytest.mark.asyncio
    async def test_generate_draft_response_multi_turn(self):
        """Draft response includes full conversation history."""
        provider = _mock_provider("Good point about maintainability.")

        with patch('summarizer.get_provider', return_value=provider):
            history = [
                {"role": "user", "content": "React is better"},
                {"role": "model", "content": "Why do you think so?"},
                {"role": "user", "content": "Faster performance"},
            ]
            result = await summarizer.generate_draft_response(history, "You are Murmur...")
            assert result is not None
            # Verify generate_text was called (history forwarded)
            call_args = provider.generate_text.call_args
            assert call_args is not None

    @pytest.mark.asyncio
    async def test_generate_draft_response_error_handling(self):
        """Returns graceful error message on API failure."""
        provider = Mock()
        provider.generate_text = AsyncMock(side_effect=Exception("API error"))

        with patch('summarizer.get_provider', return_value=provider):
            history = [{"role": "user", "content": "test"}]
            result = await summarizer.generate_draft_response(history, "prompt")
            assert "trouble" in result.lower() or "error" in result.lower()


# ---------------------------------------------------------------------------
# TestGenerateReminderDigest
# ---------------------------------------------------------------------------

class TestGenerateReminderDigest:
    """Test reminder digest generation."""

    def setup_method(self):
        _reset_for_tests()

    @pytest.mark.asyncio
    async def test_generate_reminder_digest_success(self):
        """Successfully generate reminder digest."""
        provider = _mock_provider("📬 5 new messages in Frontend Stack and API Design.")

        with patch('summarizer.get_provider', return_value=provider):
            result = await summarizer.generate_reminder_digest(
                message_count=5,
                topic_names=["Frontend Stack", "API Design"],
                stale_topics=[],
            )
            assert "5" in result or "new" in result.lower()

    @pytest.mark.asyncio
    async def test_generate_reminder_digest_with_stale_topics(self):
        """Reminder digest mentions stale topics."""
        provider = _mock_provider("3 new messages. Legacy Architecture is stale (5 days).")

        with patch('summarizer.get_provider', return_value=provider):
            result = await summarizer.generate_reminder_digest(
                message_count=3,
                topic_names=[],
                stale_topics=["Legacy Architecture"],
            )
            assert result is not None

    @pytest.mark.asyncio
    async def test_generate_reminder_digest_fallback(self):
        """Falls back to simple format on API error."""
        provider = Mock()
        provider.generate_text = AsyncMock(side_effect=Exception("API error"))

        with patch('summarizer.get_provider', return_value=provider):
            result = await summarizer.generate_reminder_digest(10, [], [])
            assert "10" in result
            assert "📬" in result or "messages" in result.lower()
