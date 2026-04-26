"""Group link-summary failure-mode tests.

Covers the bug class fixed in PR #3:
- Partial chunk delivery does NOT write the delivered signal.
- HTML→plain-text fallback IS captured (no duplicate resend on retry).
- YouTube agent failure does NOT fall through to TinyFish (footer-summary bug).
- Generic agent failure DOES fall through to TinyFish (non-YouTube).
"""

import pytest
from baml_client.types import ExtractorTool

from tests.integration.factories import group_text_update
from tests.integration.conftest import GROUP_CHAT_ID, DM_USER_ID


pytestmark = pytest.mark.integration


def _count_link_summaries(test_db) -> int:
    with test_db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM link_summaries")
        return cur.fetchone()[0]


# ----------------------------------------------------------------------------
# YouTube no-transcript: must skip TinyFish (the footer-summary bug)
# ----------------------------------------------------------------------------


def test_group_youtube_no_transcript_skips_tinyfish(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """YouTube URL with no transcript and failed AgentQL → bot must reply
    with the no-transcript error and NOT fall back to TinyFish (which
    would return YouTube site footer/nav and produce a meaningless summary).
    """
    mock_llms.set_route(ExtractorTool.YoutubeExtractor)
    # Both extraction routes fail
    mock_extractors.youtube_transcript = None  # transcript-api returned nothing
    mock_extractors.youtube_agentql = {}  # AgentQL fallback also empty
    # If TinyFish were called it would return this — assert it ISN'T.
    mock_extractors.tinyfish_content = "About | Press | Copyright | NFL Sunday Ticket | Google LLC"

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=30001,
        user_id=DM_USER_ID,
        text="check https://www.youtube.com/watch?v=NoCaptionsXYZ",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    replies = recording_bot.replies_to(GROUP_CHAT_ID)
    assert len(replies) == 1
    assert "YouTube" in replies[0]["text"] or "transcript" in replies[0]["text"].lower()
    # Critical: no link_summary written — the canned footer text was NOT summarised.
    assert _count_link_summaries(test_db) == 0


# ----------------------------------------------------------------------------
# Non-YouTube agent failure: TinyFish fallback IS allowed
# ----------------------------------------------------------------------------


def test_group_non_youtube_agent_error_falls_back_to_tinyfish(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Non-YouTube URL that fails primary extraction → TinyFish fallback runs."""
    mock_llms.set_route(ExtractorTool.WebpageExtractor)
    mock_llms.set_summary(title="Fallback Summary", key_points=["a"], summary="t")
    # Primary path fails
    mock_extractors.tavily_results = []
    mock_extractors.tavily_failed = [{"url": "https://example.com/page-that-fails"}]
    mock_extractors.playwright_text = None
    # TinyFish recovers
    mock_extractors.tinyfish_content = "Recovered article body. " * 30

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=30002,
        user_id=DM_USER_ID,
        text="check https://example.com/page-that-fails",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    replies = recording_bot.replies_to(GROUP_CHAT_ID)
    full_reply = "".join(r["text"] for r in replies)
    assert "Fallback Summary" in full_reply
    # link_summary written via the TinyFish-fallback path
    assert _count_link_summaries(test_db) == 1


# ----------------------------------------------------------------------------
# Total failure: agent fails AND TinyFish fails → user sees error, no signal
# ----------------------------------------------------------------------------


def test_group_total_extraction_failure_no_signal(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Both agent and TinyFish fail → generic error reply, no link_summary."""
    mock_llms.set_route(ExtractorTool.WebpageExtractor)
    mock_extractors.tavily_results = []
    mock_extractors.tavily_failed = [{"url": "https://example.com/total-fail"}]
    mock_extractors.playwright_text = None
    mock_extractors.tinyfish_content = None

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=30003,
        user_id=DM_USER_ID,
        text="check https://example.com/total-fail",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    replies = recording_bot.replies_to(GROUP_CHAT_ID)
    assert len(replies) == 1
    assert "couldn't extract" in replies[0]["text"].lower() or "⚠️" in replies[0]["text"]
    # No delivered signal — a retry can re-attempt
    assert _count_link_summaries(test_db) == 0


# ----------------------------------------------------------------------------
# Partial chunk delivery: must NOT write the delivered signal
# ----------------------------------------------------------------------------


def test_group_partial_chunk_delivery_no_signal(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Long summary that fails on the second chunk → fully_delivered=False
    → no link_summary stored → retry can redeliver completely.

    This is the bug fixed in 88c388a (the second-round review on PR #3).
    Reverting that fix should make this test fail.
    """
    mock_llms.set_route(ExtractorTool.WebpageExtractor)
    # Force a multi-chunk summary by making the BAML response very long
    mock_llms.set_summary(
        title="Long Summary Title",
        key_points=["kp1"],
        summary="X" * 8000,  # forces ≥2 chunks (MAX_TELEGRAM_MSG_LEN=4096)
    )
    mock_extractors.tavily_results = [
        {"url": "https://example.com/long", "raw_content": "Body. " * 100}
    ]
    # First chunk lands; later chunks fail (HTML and plain-text both raise)
    recording_bot.recorder.fail_after_n_replies = 1

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=30004,
        user_id=DM_USER_ID,
        text="check https://example.com/long",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    # First chunk delivered, second chunk failed → reply count = 1
    assert recording_bot.reply_count == 1
    # Critical: no link_summary, even though one chunk landed
    assert _count_link_summaries(test_db) == 0


# ----------------------------------------------------------------------------
# Plain-text fallback is captured (regression test for 88c388a P1-2)
# ----------------------------------------------------------------------------


def test_group_html_failure_plain_text_fallback_writes_signal(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """HTML reply raises (e.g. Telegram parse error) but plain-text retry
    succeeds → the plain-text send IS counted as delivery →
    link_summary IS written → retry will skip (no duplicate to user).

    This pins down the TinyFish-path drift fix from 88c388a (P1-2).
    """
    mock_llms.set_route(ExtractorTool.WebpageExtractor)
    mock_llms.set_summary(title="Summary", key_points=["a"], summary="text")
    mock_extractors.tavily_results = [
        {"url": "https://example.com/html-bad", "raw_content": "Body. " * 30}
    ]
    # HTML send raises; plain-text retry (no parse_mode) succeeds
    recording_bot.recorder.html_parse_fails = True

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=30005,
        user_id=DM_USER_ID,
        text="check https://example.com/html-bad",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    # Plain-text fallback succeeded — ≥1 reply landed without parse_mode
    plain_replies = [r for r in recording_bot.replies_to(GROUP_CHAT_ID) if r["parse_mode"] is None]
    assert len(plain_replies) >= 1, "plain-text fallback should have delivered"
    # link_summary IS written because the plain-text fallback was captured
    assert _count_link_summaries(test_db) == 1
