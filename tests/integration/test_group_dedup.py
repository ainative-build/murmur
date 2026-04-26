"""Webhook-retry dedup contract tests.

These exercise the bug class fixed in PR #3 (atomic claim + delivered-signal).
Each test is a mutation check candidate: reverting the corresponding fix in
bot.py / db.py should cause the matching test to fail.
"""

import asyncio

import pytest
from baml_client.types import ExtractorTool

from tests.integration.factories import group_text_update
from tests.integration.conftest import GROUP_CHAT_ID, DM_USER_ID


pytestmark = pytest.mark.integration


def _setup_webpage_path(mock_llms, mock_extractors, *, summary_title="Test Summary"):
    """Configure mocks for a successful webpage extraction."""
    mock_llms.set_route(ExtractorTool.WebpageExtractor)
    mock_llms.set_summary(title=summary_title, key_points=["a"], summary="text")
    mock_extractors.tavily_results = [
        {"url": "https://example.com/article", "raw_content": "Article body. " * 50}
    ]


def _count_link_summaries(test_db) -> int:
    with test_db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM link_summaries")
        return cur.fetchone()[0]


def _count_messages(test_db) -> int:
    with test_db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM messages")
        return cur.fetchone()[0]


def test_in_memory_dedup_blocks_concurrent_retry(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Same update sent twice in-process → second is short-circuited by
    `bot._processing_messages`, only one reply lands."""
    _setup_webpage_path(mock_llms, mock_extractors)

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=20001,
        user_id=DM_USER_ID,
        text="check https://example.com/article",
        bot=recording_bot,
    )

    # First dispatch
    resp1 = tg_client.post_update(update)
    assert resp1.status_code == 200

    # Same update (same chat_id, msg_id) again — webhook retry
    resp2 = tg_client.post_update(update)
    assert resp2.status_code == 200

    # Exactly one reply chain landed
    replies = recording_bot.replies_to(GROUP_CHAT_ID)
    assert len(replies) == 1, f"expected 1 reply, got {len(replies)}"
    assert _count_messages(test_db) == 1
    assert _count_link_summaries(test_db) == 1


def test_db_claim_blocks_cross_instance_retry(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Simulate a retry arriving at a fresh container instance:
    clear `bot._processing_messages` between dispatches. The DB-based
    delivered-signal check (has_link_summary on the existing message) blocks
    the duplicate reply."""
    import bot as bot_module

    _setup_webpage_path(mock_llms, mock_extractors)

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=20002,
        user_id=DM_USER_ID,
        text="check https://example.com/article",
        bot=recording_bot,
    )

    # First dispatch — full pipeline runs, link_summary stored
    tg_client.post_update(update)
    assert _count_link_summaries(test_db) == 1

    # Simulate cross-instance retry: in-memory dedup is gone
    bot_module._processing_messages.clear()

    # Retry the same update
    tg_client.post_update(update)

    # Still exactly one reply, one link_summary
    assert len(recording_bot.replies_to(GROUP_CHAT_ID)) == 1
    assert _count_link_summaries(test_db) == 1
    assert _count_messages(test_db) == 1


def test_retry_after_partial_failure_completes_delivery(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Cross-instance retry where the prior attempt died before delivery:
    `messages` row exists but no `link_summary` → retry re-runs the pipeline
    and completes delivery. Prevents the permanent-drop failure mode."""
    import bot as bot_module

    _setup_webpage_path(mock_llms, mock_extractors)

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=20003,
        user_id=DM_USER_ID,
        text="check https://example.com/article",
        bot=recording_bot,
    )

    # First dispatch — fail every reply so link_summary is NEVER stored.
    recording_bot.recorder.fail_all_replies = True
    tg_client.post_update(update)
    # Message stored, but no link_summary (delivered signal absent)
    assert _count_messages(test_db) == 1
    assert _count_link_summaries(test_db) == 0

    # Simulate cross-instance retry, this time replies succeed
    bot_module._processing_messages.clear()
    recording_bot.recorder.fail_all_replies = False
    recording_bot.recorder.calls.clear()  # clear failed-attempt records

    tg_client.post_update(update)

    # Retry produced the reply, link_summary now persisted
    replies = recording_bot.replies_to(GROUP_CHAT_ID)
    assert len(replies) >= 1, "retry should have delivered the summary"
    assert _count_link_summaries(test_db) == 1
    # Still one messages row — atomic upsert prevents duplicate
    assert _count_messages(test_db) == 1


def test_no_retry_for_no_link_message(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """A no-link message that's already in DB → duplicate webhook skips
    re-processing. Nothing user-visible to redeliver."""
    import bot as bot_module

    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=20004,
        user_id=DM_USER_ID,
        text="just a regular message, no urls",
        bot=recording_bot,
    )

    tg_client.post_update(update)
    assert _count_messages(test_db) == 1
    assert _count_link_summaries(test_db) == 0
    initial_call_count = len(recording_bot.calls)

    # Cross-instance retry
    bot_module._processing_messages.clear()
    tg_client.post_update(update)

    # Still one row, no new calls (no-link duplicates skip silently)
    assert _count_messages(test_db) == 1
    assert _count_link_summaries(test_db) == 0
    assert len(recording_bot.calls) == initial_call_count
