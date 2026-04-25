"""LLM mock fixture configuration.

Patches BAML (`baml_client.b.SummarizeContent`, `b.RouteRequest`) and the four
`summarizer.generate_*` Gemini call sites with deterministic responses.

Usage in tests:
    def test_x(mock_llms):
        mock_llms.set_summary(title="My Title", key_points=["a"], summary="...")
        mock_llms.set_route(ExtractorTool.WebpageExtractor)
        # ...

The default responses (when not overridden per-test) are listed in `DEFAULTS`.
"""

from dataclasses import dataclass, field
from typing import Optional
from unittest.mock import patch

from baml_client.types import ContentType, ExtractorTool, Summary


DEFAULTS = {
    "summary": Summary(
        title="Test Webpage",
        key_points=["First key point.", "Second key point."],
        concise_summary="A concise summary of the webpage content for testing.",
    ),
    "route": ExtractorTool.WebpageExtractor,
    "catchup": "Test catchup digest with @alice mentioning links.",
    "topics": [
        {"name": "auth", "description": "Authentication discussion.", "participants": ["alice", "bob"]},
        {"name": "deploys", "description": "Deployment plan.", "participants": ["alice"]},
    ],
    "topic_detail": "Detailed synthesis of the topic with [alice, 2026-04-22] citations.",
    "decision_view": (
        "## Options\n- Option A\n- Option B\n\n"
        "## Arguments For/Against\nOption A: pros [alice]; cons [bob]\n\n"
        "## Key Evidence\nLink: relevant article\n\n"
        "## What's Missing\nLatency benchmarks."
    ),
    "draft": "Draft response turn.",
    "reminder": "📬 5 new messages. Use /catchup for details.",
}


@dataclass
class LLMMockConfig:
    """Mutable configuration for LLM mocks. Tests adjust this per-test."""

    summary: Summary = field(default_factory=lambda: DEFAULTS["summary"])
    route: ExtractorTool = ExtractorTool.WebpageExtractor
    catchup: str = DEFAULTS["catchup"]
    topics: list[dict] = field(default_factory=lambda: list(DEFAULTS["topics"]))
    topic_detail: str = DEFAULTS["topic_detail"]
    decision_view: str = DEFAULTS["decision_view"]
    draft: str = DEFAULTS["draft"]
    reminder: str = DEFAULTS["reminder"]

    def set_summary(
        self,
        title: str = "Test Webpage",
        key_points: Optional[list[str]] = None,
        summary: str = "A concise summary.",
    ) -> None:
        self.summary = Summary(
            title=title,
            key_points=key_points or ["kp1"],
            concise_summary=summary,
        )

    def set_route(self, route: ExtractorTool) -> None:
        self.route = route


def install_llm_mocks(config: LLMMockConfig) -> list:
    """Install the patches and return the list of patcher objects.

    Caller is responsible for `.stop()`-ing each patcher in teardown. The
    `mock_llms` fixture in conftest handles this.
    """
    patches = []

    # ---- BAML ----
    p_summary = patch("baml_client.b.SummarizeContent", side_effect=lambda **kwargs: config.summary)
    patches.append(p_summary)

    p_route = patch("baml_client.b.RouteRequest", side_effect=lambda **kwargs: config.route)
    patches.append(p_route)

    # ---- Gemini direct calls in summarizer.py ----
    async def _async_return(value):
        return value

    p_catchup = patch(
        "summarizer.generate_catchup",
        side_effect=lambda *a, **kw: _async_return(config.catchup),
    )
    patches.append(p_catchup)

    p_topics = patch(
        "summarizer.generate_topics",
        side_effect=lambda *a, **kw: _async_return(config.topics),
    )
    patches.append(p_topics)

    p_topic = patch(
        "summarizer.generate_topic_detail",
        side_effect=lambda *a, **kw: _async_return(config.topic_detail),
    )
    patches.append(p_topic)

    p_decide = patch(
        "summarizer.generate_decision_view",
        side_effect=lambda *a, **kw: _async_return(config.decision_view),
    )
    patches.append(p_decide)

    p_draft = patch(
        "summarizer.generate_draft_response",
        side_effect=lambda *a, **kw: _async_return(config.draft),
    )
    patches.append(p_draft)

    p_reminder = patch(
        "summarizer.generate_reminder_digest",
        side_effect=lambda *a, **kw: _async_return(config.reminder),
    )
    patches.append(p_reminder)

    for p in patches:
        p.start()

    return patches
