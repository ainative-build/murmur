"""Webhook authentication and transport tests.

The `X-Telegram-Bot-Api-Secret-Token` check is the only thing standing
between the bot's webhook and the public internet. If the auth check
regresses, anyone can post fake updates and trigger the bot to act.
"""

import pytest

from tests.integration.factories import group_text_update
from tests.integration.conftest import GROUP_CHAT_ID, DM_USER_ID


pytestmark = pytest.mark.integration


def test_webhook_missing_secret_token_403(tg_client, test_db, recording_bot):
    """No header → 403, no DB writes, no bot calls."""
    payload = {"update_id": 1, "message": {"message_id": 1, "date": 0}}
    resp = tg_client._client.post(
        f"/{tg_client._webhook_path}", json=payload, headers={}
    )
    assert resp.status_code == 403
    # No side effects
    count = test_db.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
    assert count == 0
    assert recording_bot.calls == []


def test_webhook_wrong_secret_token_403(tg_client, test_db, recording_bot):
    """Wrong header value → 403."""
    resp = tg_client._client.post(
        f"/{tg_client._webhook_path}",
        json={"update_id": 2},
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-token-xyz"},
    )
    assert resp.status_code == 403
    assert recording_bot.calls == []


def test_webhook_correct_secret_returns_200(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Correct secret + valid update → 200."""
    update = group_text_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=80001,
        user_id=DM_USER_ID,
        text="hello world",
        bot=recording_bot,
    )
    resp = tg_client.post_update(update)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_webhook_invalid_json_returns_error_body(tg_client):
    """Invalid JSON body → 200 with error body (PTB doesn't 4xx — Telegram retries on 4xx)."""
    resp = tg_client._client.post(
        f"/{tg_client._webhook_path}",
        content=b"not-valid-json{{{",
        headers={
            "X-Telegram-Bot-Api-Secret-Token": tg_client._secret,
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is False
    assert "Invalid JSON" in body.get("error", "") or "JSON" in body.get("error", "")


def test_webhook_handler_exception_swallowed(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Handler crash inside `process_update` is logged and swallowed by
    `_safe_process_update`; webhook still returns 200 ok:true so Telegram
    doesn't retry. The user's update is dropped — caller's responsibility
    to monitor logs / metrics for handler errors.
    """
    import bot as bot_module
    from unittest.mock import patch

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated handler crash")

    with patch.object(bot_module.ptb_app, "process_update", side_effect=_boom):
        update = group_text_update(
            chat_id=GROUP_CHAT_ID,
            msg_id=80002,
            user_id=DM_USER_ID,
            text="trigger crash",
            bot=recording_bot,
        )
        resp = tg_client.post_update(update)

    # _safe_process_update swallowed the exception → webhook returns 200 ok:true
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
