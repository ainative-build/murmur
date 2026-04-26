"""DM /search <keyword> integration tests.

Exercises the real Postgres FTS triggers from migration 002 — neither the
unit tests nor any prior integration test touched these triggers. If the
search_vector triggers regress, these tests are the only safety net.

Critical security test: personal source isolation between users.
"""

import pytest

from tests.integration.factories import dm_command_update
from tests.integration.conftest import DM_USER_ID, SECOND_USER_ID, GROUP_CHAT_ID
from tests.integration import seeds


pytestmark = pytest.mark.integration


def test_dm_search_finds_message(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Match a group message via FTS."""
    seeds.seed_message(
        tg_chat_id=GROUP_CHAT_ID,
        tg_msg_id=900,
        tg_user_id=DM_USER_ID,
        username="alice",
        text="we should refactor the authentication module next sprint",
    )

    update = dm_command_update(
        user_id=DM_USER_ID, command="search", args="authentication", bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "authentication" in full.lower() or "refactor" in full.lower()
    assert "[GROUP]" in full


def test_dm_search_finds_link_summary(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Match a link_summary via FTS — exercises migration 002 link trigger."""
    msg_id = seeds.seed_message(
        tg_chat_id=GROUP_CHAT_ID,
        tg_msg_id=901,
        tg_user_id=DM_USER_ID,
        text="check this out https://example.com/auth-api",
        has_links=True,
    )
    seeds.seed_link_summary(
        message_id=msg_id,
        url="https://example.com/auth-api",
        title="Auth API Documentation",
        summary="Comprehensive guide to the auth API.",
    )

    update = dm_command_update(
        user_id=DM_USER_ID, command="search", args="auth", bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "Auth API" in full or "🔗" in full


def test_dm_search_finds_personal_source(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Match a personal note via FTS — exercises migration 002 personal trigger."""
    seeds.seed_personal_source(
        tg_user_id=DM_USER_ID,
        source_type="note",
        content="quick note about the migration approach",
        title="Migration plan",
    )

    update = dm_command_update(
        user_id=DM_USER_ID, command="search", args="migration", bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "[PERSONAL]" in full


def test_dm_search_personal_isolation_between_users(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """SECURITY: User A's personal sources must not appear in User B's search.

    If this regresses, users can read each other's private notes.
    """
    # User A's secret
    seeds.seed_personal_source(
        tg_user_id=SECOND_USER_ID,
        source_type="note",
        content="sensitive private payroll info confidential",
        title="HR Notes",
    )
    # User B (DM_USER_ID) has no matching personal sources

    # User B searches for "payroll"
    update = dm_command_update(
        user_id=DM_USER_ID, command="search", args="payroll", bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    # User B must NOT see User A's note
    assert "HR Notes" not in full
    assert "payroll" not in full.lower() or "No results" in full


def test_dm_search_no_args_shows_usage(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    update = dm_command_update(user_id=DM_USER_ID, command="search", bot=recording_bot)
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    assert "Usage" in "".join(m["text"] for m in msgs)


def test_dm_search_no_results(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Empty result set → friendly 'No results' reply."""
    update = dm_command_update(
        user_id=DM_USER_ID, command="search", args="zzzunmatchablexyz", bot=recording_bot
    )
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    assert "No results" in "".join(m["text"] for m in msgs)
