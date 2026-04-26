"""DM /topics, /topic <name>, /decide <topic> integration tests."""

import pytest

from tests.integration.factories import dm_command_update
from tests.integration.conftest import DM_USER_ID, GROUP_CHAT_ID
from tests.integration import seeds


pytestmark = pytest.mark.integration


# ----------------------------------------------------------------------------
# /topics
# ----------------------------------------------------------------------------


def test_dm_topics_returns_topic_list(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Recent messages → mocked generate_topics returns 4 topics → reply lists them."""
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID)
    seeds.seed_messages_for_topics(GROUP_CHAT_ID)

    mock_llms.topics = [
        {"name": "auth", "description": "OAuth vs JWT.", "participants": ["alice", "bob"]},
        {"name": "deploys", "description": "Migration runbook.", "participants": ["carol", "dave"]},
        {"name": "latency", "description": "API p99 spike.", "participants": ["alice", "bob"]},
        {"name": "planning", "description": "Sprint priorities.", "participants": ["dave", "carol"]},
    ]

    update = dm_command_update(user_id=DM_USER_ID, command="topics", bot=recording_bot)
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "auth" in full and "deploys" in full and "latency" in full and "planning" in full
    # Footer hint
    assert "/topic" in full


def test_dm_topics_no_groups(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    seeds.seed_user(DM_USER_ID, "alice")  # exists but no chat_state

    update = dm_command_update(user_id=DM_USER_ID, command="topics", bot=recording_bot)
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    assert "haven't seen you" in "".join(m["text"] for m in msgs).lower()


def test_dm_topics_no_recent_messages(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Chat exists but no messages in last 48h → 'No messages in the last 48 hours'."""
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID)
    # No messages seeded

    update = dm_command_update(user_id=DM_USER_ID, command="topics", bot=recording_bot)
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    assert "No messages" in "".join(m["text"] for m in msgs)


def test_dm_topics_llm_returns_empty_list(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Messages exist but LLM identifies no topics → friendly fallback."""
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID)
    seeds.seed_messages_for_topics(GROUP_CHAT_ID)
    mock_llms.topics = []

    update = dm_command_update(user_id=DM_USER_ID, command="topics", bot=recording_bot)
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "Couldn't identify" in full or "no distinct" in full.lower()


# ----------------------------------------------------------------------------
# /topic <name>
# ----------------------------------------------------------------------------


def test_dm_topic_detail_with_messages(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID)
    seeds.seed_messages_for_topics(GROUP_CHAT_ID)
    mock_llms.topic_detail = "Synthesis of the auth thread with [alice, 2026-04-22] cite."

    update = dm_command_update(
        user_id=DM_USER_ID, command="topic", args="auth", bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "auth" in full
    assert "Synthesis of the auth thread" in full


def test_dm_topic_detail_no_args(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    update = dm_command_update(user_id=DM_USER_ID, command="topic", bot=recording_bot)
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    assert "Usage" in "".join(m["text"] for m in msgs)


def test_dm_topic_detail_no_match(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Keyword that matches no messages → 'No messages found about ...'"""
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID)
    seeds.seed_messages_for_topics(GROUP_CHAT_ID)

    update = dm_command_update(
        user_id=DM_USER_ID, command="topic", args="zzznothingmatching", bot=recording_bot
    )
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "No messages found" in full


# ----------------------------------------------------------------------------
# /decide <topic>
# ----------------------------------------------------------------------------


def test_dm_decide_returns_structured_view(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID)
    seeds.seed_messages_for_decide(GROUP_CHAT_ID, topic_keyword="auth")

    mock_llms.decision_view = (
        "## Options\n- OAuth\n- Magic links\n\n"
        "## Arguments For/Against\nOAuth: standard, redirect [alice]\n"
        "Magic links: simpler [bob]\n\n"
        "## Key Evidence\n[link: auth library docs]\n\n"
        "## What's Missing\nLatency benchmarks."
    )

    update = dm_command_update(
        user_id=DM_USER_ID, command="decide", args="auth", bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "Decision: auth" in full or "auth" in full
    assert "Options" in full
    assert "Magic links" in full


def test_dm_decide_no_args(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    update = dm_command_update(user_id=DM_USER_ID, command="decide", bot=recording_bot)
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    assert "Usage" in "".join(m["text"] for m in msgs)


def test_dm_decide_no_match(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID)
    seeds.seed_messages_for_topics(GROUP_CHAT_ID)

    update = dm_command_update(
        user_id=DM_USER_ID, command="decide", args="zzznothingmatching", bot=recording_bot
    )
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    assert "No discussion found" in "".join(m["text"] for m in msgs)
