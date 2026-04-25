"""External-tool mock fixture configuration.

Patches every extractor / scraper / transcriber / file-extractor at its
import site so no test ever makes a real network call.

Tool seams covered:
- `tools.search.run_tavily_tool`
- `tools.tinyfish_fetcher.fetch_url_content`
- `tools.youtube_agentql_scraper.scrape_youtube`
- `tools.linkedin_agentql_scraper.scrape_linkedin_post`
- `tools.spotify_scraper.get_spotify_metadata`
- `tools.twitter_api_tool.fetch_tweet_thread`
- `tools.playwright_fallback.extract_page_text`
- `tools.voice_transcriber.transcribe_audio`
- `tools.file_extractor.extract_file_text`
- `tools.pdf_handler.get_pdf_text`
- `agent._get_youtube_transcript` (the YouTube transcript-api wrapper)
- `bot._analyze_image` (Gemini vision call)

Each tool is patched at BOTH the module-of-definition path AND at every known
import site (e.g., `bot.fetch_url_content` if bot did `from x import y`).
The integration tests' baseline is "all tools return empty/None"; tests
override per-fixture for the specific path under test.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
from unittest.mock import AsyncMock, MagicMock, patch


@dataclass
class ExtractorMockConfig:
    """Knobs each test can flip to inject extractor outputs."""

    tavily_results: list[dict] = field(default_factory=list)
    tavily_failed: list[dict] = field(default_factory=list)
    tinyfish_content: Optional[str] = None
    youtube_agentql: dict = field(default_factory=dict)
    linkedin_agentql: dict = field(default_factory=dict)
    spotify_metadata: Optional[dict] = None
    tweet_thread: str = ""
    playwright_text: Optional[str] = None
    voice_transcript: Optional[str] = None
    file_extract_text: Optional[str] = None
    pdf_text: Optional[str] = None
    youtube_transcript: Optional[str] = None
    image_description: Optional[str] = None

    # Failure injection
    raise_in_tavily: bool = False
    raise_in_tinyfish: bool = False
    raise_in_pdf: bool = False


def install_extractor_mocks(config: ExtractorMockConfig) -> list:
    """Install patches for every external tool. Returns patchers for teardown."""
    patches = []

    # ---- Tavily ----
    def _tavily(*args, **kwargs):
        if config.raise_in_tavily:
            raise RuntimeError("mock tavily failure")
        return {"results": config.tavily_results, "failed_results": config.tavily_failed}

    patches.append(patch("tools.search.run_tavily_tool", side_effect=_tavily))
    patches.append(patch("agent.run_tavily_tool", side_effect=_tavily))

    # ---- TinyFish ----
    async def _tinyfish(url, max_chars=10_000):
        if config.raise_in_tinyfish:
            raise RuntimeError("mock tinyfish failure")
        return config.tinyfish_content

    patches.append(patch("tools.tinyfish_fetcher.fetch_url_content", side_effect=_tinyfish))

    # ---- YouTube AgentQL scraper ----
    patches.append(patch(
        "tools.youtube_agentql_scraper.scrape_youtube",
        side_effect=lambda *a, **kw: config.youtube_agentql,
    ))
    patches.append(patch(
        "agent.scrape_youtube_agentql",
        side_effect=lambda *a, **kw: config.youtube_agentql,
    ))

    # ---- LinkedIn AgentQL scraper ----
    patches.append(patch(
        "tools.linkedin_agentql_scraper.scrape_linkedin_post",
        side_effect=lambda *a, **kw: config.linkedin_agentql,
    ))
    patches.append(patch(
        "agent.scrape_linkedin_post_agentql",
        side_effect=lambda *a, **kw: config.linkedin_agentql,
    ))

    # ---- Spotify ----
    patches.append(patch(
        "tools.spotify_scraper.get_spotify_metadata",
        side_effect=lambda *a, **kw: config.spotify_metadata,
    ))

    # ---- Twitter ----
    patches.append(patch(
        "tools.twitter_api_tool.fetch_tweet_thread",
        side_effect=lambda *a, **kw: config.tweet_thread,
    ))
    patches.append(patch(
        "agent.fetch_tweet_thread",
        side_effect=lambda *a, **kw: config.tweet_thread,
    ))

    # ---- Playwright fallback ----
    patches.append(patch(
        "tools.playwright_fallback.extract_page_text",
        side_effect=lambda *a, **kw: config.playwright_text,
    ))

    # ---- Voice transcriber ----
    async def _transcribe(audio_bytes, mime_type=None):
        return config.voice_transcript

    patches.append(patch("tools.voice_transcriber.transcribe_audio", side_effect=_transcribe))

    # ---- File extractor ----
    patches.append(patch(
        "tools.file_extractor.extract_file_text",
        side_effect=lambda *a, **kw: config.file_extract_text,
    ))

    # ---- PDF handler ----
    def _pdf(*args, **kwargs):
        if config.raise_in_pdf:
            raise RuntimeError("mock pdf failure")
        return config.pdf_text or ""

    patches.append(patch("tools.pdf_handler.get_pdf_text", side_effect=_pdf))
    patches.append(patch("agent.get_pdf_text", side_effect=_pdf))

    # ---- YouTube transcript-api (used inside agent._get_youtube_transcript) ----
    patches.append(patch(
        "agent._get_youtube_transcript",
        side_effect=lambda video_id: config.youtube_transcript,
    ))
    patches.append(patch(
        "agent._get_youtube_title",
        side_effect=lambda video_id: "Test YouTube Title",
    ))

    # ---- Gemini vision (bot._analyze_image) ----
    async def _analyze(*args, **kwargs):
        return config.image_description

    patches.append(patch("bot._analyze_image", side_effect=_analyze))

    for p in patches:
        p.start()

    return patches
