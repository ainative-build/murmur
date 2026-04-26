"""Concurrent webhook dispatch + transient-DB-failure tests.

These exercise the most fragile paths in the dedup contract: simultaneous
retries to multiple container instances, and the case where the atomic
INSERT fails but no row is actually present (transient DB error).
"""

import asyncio
from unittest.mock import patch

import pytest
from baml_client.types import ExtractorTool

from tests.integration.factories import group_text_update
from tests.integration.conftest import GROUP_CHAT_ID, DM_USER_ID


pytestmark = pytest.mark.integration


def _setup_webpage_path(mock_llms, mock_extractors):
    mock_llms.set_route(ExtractorTool.WebpageExtractor)
    mock_llms.set_summary(title="Test", key_points=["a"], summary="t")
    mock_extractors.tavily_results = [
        {"url": "https://example.com/race", "raw_content": "Body. " * 50}
    ]


def _count(test_db, table: str) -> int:
    return test_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ----------------------------------------------------------------------------
# Concurrent dispatch race (asyncio.Barrier ensures both reach the handler
# at the same event-loop tick — without the barrier, the first dispatch's
# in-memory dedup would always win on a sequential schedule)
# ----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_concurrent_dispatches_one_reply(
    bot_app, test_db, recording_bot, mock_llms, mock_extractors
):
    """Two coroutines dispatch the same update simultaneously → exactly one
    reply chain lands. The atomic INSERT...ON CONFLICT picks one winner;
    the other observes the existing row and skips via the no-link / has-
    link-summary branches."""
    import bot as bot_module

    _setup_webpage_path(mock_llms, mock_extractors)

    update_payload = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=70001,
        user_id=DM_USER_ID,
        text="check https://example.com/race",
        bot=recording_bot,
    )

    from telegram import Update
    update = Update.de_json(update_payload, recording_bot)

    # Initialize PTB once
    ptb_app = bot_module.app.state.ptb_app
    if not getattr(ptb_app, "_initialized", False):
        await ptb_app.initialize()
        await ptb_app.start()

    barrier = asyncio.Barrier(2)

    async def _hit():
        await barrier.wait()
        await bot_module.app.state.ptb_app.process_update(update)

    await asyncio.gather(_hit(), _hit())

    # Atomic claim ensures one winner: 1 message row, 1 link_summary, 1 reply chain
    assert _count(test_db, "messages") == 1
    assert _count(test_db, "link_summaries") == 1
    assert recording_bot.reply_count == 1


@pytest.mark.asyncio
async def test_concurrent_no_link_messages_one_store(
    bot_app, test_db, recording_bot, mock_llms, mock_extractors
):
    """Two coroutines dispatch the same no-link update simultaneously →
    exactly one messages row. No replies expected (no-link, no media)."""
    import bot as bot_module

    update_payload = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=70002,
        user_id=DM_USER_ID,
        text="just chatting, no urls here",
        bot=recording_bot,
    )

    from telegram import Update
    update = Update.de_json(update_payload, recording_bot)

    ptb_app = bot_module.app.state.ptb_app
    if not getattr(ptb_app, "_initialized", False):
        await ptb_app.initialize()
        await ptb_app.start()

    barrier = asyncio.Barrier(2)

    async def _hit():
        await barrier.wait()
        await bot_module.app.state.ptb_app.process_update(update)

    await asyncio.gather(_hit(), _hit())

    assert _count(test_db, "messages") == 1
    assert recording_bot.replies_to(GROUP_CHAT_ID) == []


# ----------------------------------------------------------------------------
# Transient DB write failure — store_message returns None AND get_message_id
# returns None → handler proceeds best-effort with message_id=None
# ----------------------------------------------------------------------------


def test_transient_db_write_failure_proceeds_best_effort(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """If store_message returns None but the row genuinely isn't in DB,
    the handler proceeds best-effort (better one duplicate later than
    silently dropping a valid summary)."""
    _setup_webpage_path(mock_llms, mock_extractors)

    # Force store_message to lie about success: return None even though the
    # row IS inserted. This simulates partial DB failure (e.g., write
    # succeeded but response lost). Then get_message_id returns None too,
    # mimicking a fully transient failure.
    with patch("bot.db.store_message", return_value=None):
        with patch("bot.db.get_message_id", return_value=None):
            update = group_text_update(
                chat_id=GROUP_CHAT_ID,
                msg_id=70003,
                user_id=DM_USER_ID,
                text="check https://example.com/transient",
                bot=recording_bot,
            )
            tg_client.post_update(update)

    # Proceeded best-effort: bot replied even with message_id=None
    assert recording_bot.reply_count >= 1
    full = "".join(r["text"] for r in recording_bot.replies_to(GROUP_CHAT_ID))
    assert "Test" in full  # canned BAML summary title leaked through
