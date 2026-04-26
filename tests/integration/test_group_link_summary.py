"""Group link-summary integration tests — happy paths per link type.

Each test:
1. Drives `tg_client.post_update(group_text(...))` with a URL of a specific type
2. Mocks the appropriate extractor + BAML
3. Asserts (a) the bot replied in the group with the summary
4. Asserts (b) `messages` and `link_summaries` rows landed in DB
"""

import pytest

from baml_client.types import ExtractorTool

from tests.integration.factories import group_text_update
from tests.integration.conftest import GROUP_CHAT_ID, DM_USER_ID


pytestmark = pytest.mark.integration


# ----------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------


def _query_messages(test_db, tg_chat_id: int):
    with test_db.cursor() as cur:
        cur.execute(
            "SELECT id, tg_msg_id, text, has_links, media_type FROM messages "
            "WHERE tg_chat_id = %s ORDER BY id",
            (tg_chat_id,),
        )
        return cur.fetchall()


def _query_link_summaries(test_db):
    with test_db.cursor() as cur:
        cur.execute(
            "SELECT message_id, url, link_type, title FROM link_summaries ORDER BY id"
        )
        return cur.fetchall()


# ----------------------------------------------------------------------------
# Generic webpage — the canonical happy path
# ----------------------------------------------------------------------------


def test_group_generic_webpage_link(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Group text with a generic article URL → reply with summary + DB rows."""
    # Configure mocks
    mock_llms.set_route(ExtractorTool.WebpageExtractor)
    mock_llms.set_summary(
        title="LLM-powered Autonomous Agents",
        key_points=["Planning", "Memory", "Tool use"],
        summary="A thorough overview of agentic LLM systems.",
    )
    mock_extractors.tavily_results = [
        {
            "url": "https://lilianweng.github.io/posts/2023-06-23-agent/",
            "raw_content": "Article body about LLM agents — planning, memory, tool use, examples." * 50,
        }
    ]

    # Drive the webhook
    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=10001,
        user_id=DM_USER_ID,
        text="check this out https://lilianweng.github.io/posts/2023-06-23-agent/",
        bot=recording_bot,
    )
    resp = tg_client.post_update(update)
    assert resp.status_code == 200

    # The user got a reply containing the summary
    replies = recording_bot.replies_to(GROUP_CHAT_ID)
    assert len(replies) >= 1, f"expected ≥1 reply, got {len(replies)}: {recording_bot.calls}"
    full_reply = "".join(r["text"] for r in replies)
    assert "LLM-powered Autonomous Agents" in full_reply

    # The message landed in DB
    msgs = _query_messages(test_db, GROUP_CHAT_ID)
    assert len(msgs) == 1
    assert msgs[0][3] is True  # has_links
    assert "lilianweng.github.io" in msgs[0][2]  # text

    # The link summary landed in DB AFTER the reply (delivered-signal contract)
    summaries = _query_link_summaries(test_db)
    assert len(summaries) == 1
    msg_id, url, link_type, title = summaries[0]
    assert msg_id == msgs[0][0]
    assert link_type == "webpage"
    assert title == "LLM-powered Autonomous Agents"
    assert "lilianweng.github.io" in url


# ----------------------------------------------------------------------------
# YouTube — happy path with transcript
# ----------------------------------------------------------------------------


def test_group_youtube_link_with_transcript(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_llms.set_route(ExtractorTool.YoutubeExtractor)
    mock_llms.set_summary(
        title="Never Gonna Give You Up",
        key_points=["intro", "chorus"],
        summary="A music video.",
    )
    mock_extractors.youtube_transcript = (
        "We're no strangers to love. " * 200
    )  # mocked transcript text

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=11001,
        user_id=DM_USER_ID,
        text="check https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    summaries = _query_link_summaries(test_db)
    assert len(summaries) == 1
    assert summaries[0][2] == "youtube"
    assert summaries[0][3] == "Never Gonna Give You Up"


def test_group_youtu_be_short_url(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_llms.set_route(ExtractorTool.YoutubeExtractor)
    mock_llms.set_summary(title="Short URL Video", key_points=["k"], summary="s")
    mock_extractors.youtube_transcript = "Transcript " * 100

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=11002,
        user_id=DM_USER_ID,
        text="check https://youtu.be/dQw4w9WgXcQ",
        bot=recording_bot,
    )
    tg_client.post_update(update)
    summaries = _query_link_summaries(test_db)
    assert len(summaries) == 1
    assert summaries[0][2] == "youtube"


# ----------------------------------------------------------------------------
# Twitter / X
# ----------------------------------------------------------------------------


def test_group_twitter_link(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_llms.set_route(ExtractorTool.TwitterExtractor)
    mock_llms.set_summary(title="Tweet Thread", key_points=["a"], summary="t")
    mock_extractors.tweet_thread = "@elon: Excited about Mars\n@reply: Same here. " * 20

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=11003,
        user_id=DM_USER_ID,
        text="check https://twitter.com/elonmusk/status/1234567890123456789",
        bot=recording_bot,
    )
    tg_client.post_update(update)
    summaries = _query_link_summaries(test_db)
    assert len(summaries) == 1
    assert summaries[0][2] == "tweet"


def test_group_x_domain_link(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_llms.set_route(ExtractorTool.TwitterExtractor)
    mock_llms.set_summary(title="X Tweet", key_points=["a"], summary="t")
    mock_extractors.tweet_thread = "@user: hello world. " * 20

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=11004,
        user_id=DM_USER_ID,
        text="check https://x.com/elonmusk/status/1234567890123456789",
        bot=recording_bot,
    )
    tg_client.post_update(update)
    assert _query_link_summaries(test_db)[0][2] == "tweet"


# ----------------------------------------------------------------------------
# LinkedIn
# ----------------------------------------------------------------------------


def test_group_linkedin_link(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_llms.set_route(ExtractorTool.LinkedInExtractor)
    mock_llms.set_summary(title="LinkedIn Post", key_points=["a"], summary="t")
    mock_extractors.linkedin_agentql = {
        "author": "Jane Doe",
        "content": "Long-form LinkedIn post body. " * 30,
    }

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=11005,
        user_id=DM_USER_ID,
        text="check https://www.linkedin.com/posts/jane-doe_some-post-activity-1234",
        bot=recording_bot,
    )
    tg_client.post_update(update)
    summaries = _query_link_summaries(test_db)
    assert len(summaries) == 1
    assert summaries[0][2] == "linkedin"


# ----------------------------------------------------------------------------
# Grok — TinyFish pre-agent path (no BAML route for Grok)
# ----------------------------------------------------------------------------


def test_group_grok_link(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_llms.set_summary(title="Grok Conversation", key_points=["a"], summary="t")
    mock_extractors.tinyfish_content = "Grok conversation markdown. " * 30

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=11006,
        user_id=DM_USER_ID,
        text="check https://grok.com/share/c2hhcmUtaWQ",
        bot=recording_bot,
    )
    tg_client.post_update(update)
    summaries = _query_link_summaries(test_db)
    assert len(summaries) == 1
    assert summaries[0][2] == "grok"


# ----------------------------------------------------------------------------
# Spotify — pre-agent metadata, no LLM
# ----------------------------------------------------------------------------


def test_group_spotify_episode(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Spotify episodes use Web API/oEmbed metadata directly — no BAML call."""
    mock_extractors.spotify_metadata = {
        "type": "episode",
        "title": "Lex Fridman #350",
        "description": "Interview with someone interesting. " * 5,
        "show_name": "Lex Fridman Podcast",
    }

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=11007,
        user_id=DM_USER_ID,
        text="check https://open.spotify.com/episode/4rOoJ6Egrf8K2IrywzwOMk",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    replies = recording_bot.replies_to(GROUP_CHAT_ID)
    full = "".join(r["text"] for r in replies)
    assert "Lex Fridman" in full
    summaries = _query_link_summaries(test_db)
    assert len(summaries) == 1
    assert summaries[0][2] == "spotify"


def test_group_spotify_show(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_extractors.spotify_metadata = {
        "type": "show",
        "title": "The Daily",
        "description": "A daily news podcast. " * 5,
    }

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=11008,
        user_id=DM_USER_ID,
        text="check https://open.spotify.com/show/3IM0lmZxpFAY7CwMuv9H4g",
        bot=recording_bot,
    )
    tg_client.post_update(update)
    assert _query_link_summaries(test_db)[0][2] == "spotify"


# ----------------------------------------------------------------------------
# GitHub
# ----------------------------------------------------------------------------


def test_group_github_link(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_llms.set_route(ExtractorTool.WebpageExtractor)
    mock_llms.set_summary(title="Anthropic SDK", key_points=["a"], summary="Python SDK")
    mock_extractors.tavily_results = [
        {"url": "https://github.com/anthropics/anthropic-sdk-python", "raw_content": "README content. " * 30}
    ]

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=11009,
        user_id=DM_USER_ID,
        text="check https://github.com/anthropics/anthropic-sdk-python",
        bot=recording_bot,
    )
    tg_client.post_update(update)
    summaries = _query_link_summaries(test_db)
    assert len(summaries) == 1
    assert summaries[0][2] == "github"


# ----------------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------------


def test_group_pdf_link(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_llms.set_route(ExtractorTool.PDFExtractor)
    mock_llms.set_summary(title="Paper Title", key_points=["abstract"], summary="...")
    mock_extractors.pdf_text = "Abstract: ... " * 100

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=11010,
        user_id=DM_USER_ID,
        text="check https://arxiv.org/pdf/2305.15334.pdf",
        bot=recording_bot,
    )
    tg_client.post_update(update)
    summaries = _query_link_summaries(test_db)
    assert len(summaries) == 1
    assert summaries[0][2] == "pdf"
