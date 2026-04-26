"""DM link summary integration tests — `personal.extract_link_summary`.

DMs treat links differently from groups: the summary is shown to the user
(preview-only) but NOT auto-saved as a personal source. The
YouTube-TinyFish-skip fix from PR #3 also applies on this path.
"""

import pytest
from baml_client.types import ExtractorTool

from tests.integration.factories import dm_text_update
from tests.integration.conftest import DM_USER_ID
from tests.integration import seeds


pytestmark = pytest.mark.integration


def _count_personal_sources(test_db) -> int:
    return test_db.execute("SELECT COUNT(*) FROM personal_sources").fetchone()[0]


def test_dm_link_summary_e2e_webpage(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Generic webpage DM → bot replies with summary, NO personal_source row."""
    mock_llms.set_route(ExtractorTool.WebpageExtractor)
    mock_llms.set_summary(
        title="LLM Agents", key_points=["a", "b"], summary="Overview."
    )
    mock_extractors.tavily_results = [
        {"url": "https://example.com/article", "raw_content": "Article body. " * 50}
    ]

    update = dm_text_update(
        user_id=DM_USER_ID,
        text="https://example.com/article what do you think?",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "LLM Agents" in full
    # DM link path is preview-only — no auto-save
    assert _count_personal_sources(test_db) == 0


def test_dm_link_youtube_no_transcript_skips_tinyfish(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """DM YouTube with no transcript must NOT fall back to TinyFish.

    Mirrors the group-side fix (PR #3) for `personal.extract_link_summary`.
    Reverting the skip in personal.py should make this test fail.
    """
    mock_llms.set_route(ExtractorTool.YoutubeExtractor)
    mock_extractors.youtube_transcript = None
    mock_extractors.youtube_agentql = {}
    # Sentinel: if TinyFish were called it would return this — assert it isn't.
    # Long enough to pass `_extract_via_tinyfish`'s len(content) > 100 threshold,
    # so a regression where TinyFish IS called would feed this to BAML.
    mock_extractors.tinyfish_content = (
        "About | Press | Copyright | Contact us | Creators | Advertise | Developers | "
        "Terms | Privacy | Policy & Safety | NFL Sunday Ticket | How YouTube works | "
        "Test new features | Google LLC 2026"
    )

    update = dm_text_update(
        user_id=DM_USER_ID,
        text="https://www.youtube.com/watch?v=NoCaptionsXYZ",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    # Friendly error, NOT a footer-summary
    assert "couldn't extract" in full.lower() or "⚠️" in full
    assert "NFL Sunday Ticket" not in full
    assert "Copyright" not in full


def test_dm_link_youtu_be_short_url_skips_tinyfish(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """youtu.be variant of the YouTube no-transcript path."""
    mock_llms.set_route(ExtractorTool.YoutubeExtractor)
    mock_extractors.youtube_transcript = None
    mock_extractors.youtube_agentql = {}
    mock_extractors.tinyfish_content = "Footer noise"

    update = dm_text_update(
        user_id=DM_USER_ID,
        text="https://youtu.be/NoCaptionsXYZ",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "Footer noise" not in full


def test_dm_forwarded_message_saved_as_personal_source(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Forwarded message → saved as personal_source (source_type='forwarded_message')."""
    update = dm_text_update(
        user_id=DM_USER_ID,
        text="forwarded content here",
        forward_from_username="originaluser",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "Forwarded message saved" in full or "✅" in full

    rows = test_db.execute(
        "SELECT source_type, content, title FROM personal_sources WHERE tg_user_id = %s",
        (DM_USER_ID,),
    ).fetchall()
    assert len(rows) == 1
    source_type, content, title = rows[0]
    assert source_type == "forwarded_message"
    assert "forwarded content here" in content
    assert "originaluser" in (title or "")


def test_dm_plain_text_prompts_for_note(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Plain text DM (no URL, not forwarded) → prompts user to use /note."""
    update = dm_text_update(
        user_id=DM_USER_ID, text="just a thought", bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "/note" in full
    # Plain text is NOT auto-saved
    assert _count_personal_sources(test_db) == 0
