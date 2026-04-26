"""DM /catchup integration tests.

Covers all branches of `commands.catchup_handler`:
- No groups → friendly error
- Single group + new messages → digest reply, last_catchup advanced
- Single group + no new messages → "No new messages"
- Multiple groups, no arg → prompts for chat_id
- Multiple groups, with valid arg → digest for chosen
- Multiple groups, with invalid arg → prompts again
- Includes link_summaries when messages have links
"""

from datetime import datetime, timedelta, timezone

import pytest

from tests.integration.factories import dm_command_update
from tests.integration.conftest import DM_USER_ID, GROUP_CHAT_ID
from tests.integration import seeds


pytestmark = pytest.mark.integration


def _replies(recording_bot, user_id):
    return recording_bot.replies_to(user_id)


def test_dm_catchup_no_groups(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """User with no chat state → friendly 'haven't seen you in any groups'."""
    seeds.seed_user(DM_USER_ID, "alice")  # exists, but no chat_state

    update = dm_command_update(user_id=DM_USER_ID, command="catchup", bot=recording_bot)
    tg_client.post_update(update)

    msgs = _replies(recording_bot, DM_USER_ID)
    assert len(msgs) >= 1
    assert "haven't seen you" in msgs[0]["text"].lower()


def test_dm_catchup_single_group_with_messages(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Single group + new messages → digest reply, last_catchup advanced."""
    epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID, last_catchup=epoch)
    # Seed 5 messages timestamped after epoch
    for i in range(5):
        seeds.seed_message(
            tg_chat_id=GROUP_CHAT_ID,
            tg_msg_id=500 + i,
            tg_user_id=DM_USER_ID,
            username="alice",
            text=f"message {i} about something interesting",
            timestamp=datetime.now(timezone.utc) - timedelta(hours=1, minutes=i),
        )
    mock_llms.catchup = "Catchup digest mentioning @alice and 5 messages."

    update = dm_command_update(user_id=DM_USER_ID, command="catchup", bot=recording_bot)
    tg_client.post_update(update)

    msgs = _replies(recording_bot, DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    # First msg is the "⏳ Generating..." progress indicator
    assert any("Generating" in m["text"] or "⏳" in m["text"] for m in msgs)
    # Then the digest itself
    assert "Catchup digest" in full

    # last_catchup should have advanced past epoch
    new_last = test_db.execute(
        "SELECT last_catchup_at FROM user_chat_state WHERE tg_user_id = %s AND tg_chat_id = %s",
        (DM_USER_ID, GROUP_CHAT_ID),
    ).fetchone()[0]
    assert new_last > epoch


def test_dm_catchup_no_new_messages(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Single group with no new messages since last_catchup → friendly 'No new messages'."""
    # last_catchup = now means there are no messages newer than it
    now = datetime.now(timezone.utc)
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID, last_catchup=now)

    update = dm_command_update(user_id=DM_USER_ID, command="catchup", bot=recording_bot)
    tg_client.post_update(update)

    msgs = _replies(recording_bot, DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "No new messages" in full


def test_dm_catchup_multi_group_no_arg_prompts(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """User in 2 groups, /catchup with no arg → prompts for chat_id."""
    seeds.seed_user_chat_state(DM_USER_ID, -1001, username="alice")
    seeds.seed_user_chat_state(DM_USER_ID, -1002, username="alice")

    update = dm_command_update(user_id=DM_USER_ID, command="catchup", bot=recording_bot)
    tg_client.post_update(update)

    msgs = _replies(recording_bot, DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "multiple groups" in full.lower() or "Specify which" in full
    # Both chat IDs surface in the prompt
    assert "-1001" in full and "-1002" in full


def test_dm_catchup_multi_group_with_valid_arg(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """User in 2 groups, /catchup <valid-chat-id> → digest for chosen group only."""
    epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)
    seeds.seed_user_chat_state(DM_USER_ID, -1001, last_catchup=epoch)
    seeds.seed_user_chat_state(DM_USER_ID, -1002, last_catchup=epoch)
    # Only -1001 has messages
    seeds.seed_message(
        tg_chat_id=-1001,
        tg_msg_id=600,
        tg_user_id=DM_USER_ID,
        username="alice",
        text="something in chat -1001",
    )
    mock_llms.catchup = "Digest specifically for chat -1001."

    update = dm_command_update(
        user_id=DM_USER_ID, command="catchup", args="-1001", bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = _replies(recording_bot, DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "Digest specifically for chat -1001" in full

    # Only the chosen chat's last_catchup advanced
    chosen = test_db.execute(
        "SELECT last_catchup_at FROM user_chat_state WHERE tg_chat_id = -1001"
    ).fetchone()[0]
    other = test_db.execute(
        "SELECT last_catchup_at FROM user_chat_state WHERE tg_chat_id = -1002"
    ).fetchone()[0]
    assert chosen > epoch
    assert other == epoch  # untouched


def test_dm_catchup_multi_group_invalid_arg_reprompts(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """User in 2 groups, /catchup with non-member chat_id → prompts again."""
    seeds.seed_user_chat_state(DM_USER_ID, -1001)
    seeds.seed_user_chat_state(DM_USER_ID, -1002)

    update = dm_command_update(
        user_id=DM_USER_ID, command="catchup", args="-9999", bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = _replies(recording_bot, DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "multiple groups" in full.lower() or "Specify which" in full


def test_dm_catchup_includes_link_summaries(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """When messages have links, link_summaries are passed to the digest generator."""
    epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID, last_catchup=epoch)
    msg_id = seeds.seed_message(
        tg_chat_id=GROUP_CHAT_ID,
        tg_msg_id=700,
        tg_user_id=DM_USER_ID,
        username="alice",
        text="check https://example.com/article",
        has_links=True,
    )
    seeds.seed_link_summary(
        message_id=msg_id,
        url="https://example.com/article",
        title="Cool Article",
        summary="A great read.",
    )

    # Capture the args passed to generate_catchup
    captured = {"link_summaries": None, "messages": None}

    async def _capture(messages, link_summaries):
        captured["messages"] = messages
        captured["link_summaries"] = link_summaries
        return "digest with link"

    import summarizer
    from unittest.mock import patch

    with patch.object(summarizer, "generate_catchup", side_effect=_capture):
        update = dm_command_update(
            user_id=DM_USER_ID, command="catchup", bot=recording_bot
        )
        tg_client.post_update(update)

    assert captured["link_summaries"] is not None
    assert len(captured["link_summaries"]) == 1
    assert captured["link_summaries"][0]["title"] == "Cool Article"
