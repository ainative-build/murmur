"""Scheduler endpoint tests — endpoints called by Cloud Scheduler.

`/health` is the basic liveness probe.
`/api/check-reminders` triggers reminder digests for users with active prefs.
`/api/cleanup-messages` deletes Telegram messages whose `delete_after` has passed.
"""

from datetime import datetime, timedelta, timezone

import pytest

import db
from tests.integration.conftest import DM_USER_ID, GROUP_CHAT_ID
from tests.integration import seeds


pytestmark = pytest.mark.integration


# ----------------------------------------------------------------------------
# /health
# ----------------------------------------------------------------------------


def test_health_endpoint_returns_200(tg_client):
    resp = tg_client._client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


# ----------------------------------------------------------------------------
# /api/check-reminders
# ----------------------------------------------------------------------------


def test_check_reminders_empty_db(tg_client):
    """No users with active reminders → 0 sent, no errors."""
    resp = tg_client._client.post("/api/check-reminders")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert body.get("reminders_sent") == 0


def test_check_reminders_sends_to_due_user(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """User with daily reminder + recent messages in their group → reminder sent."""
    # Seed user with daily reminder, last_reminder back-dated
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID)
    epoch = datetime(2020, 1, 1, tzinfo=timezone.utc)
    db.update_user_reminder(DM_USER_ID, "daily")
    # Force last_reminder back so user is "due"
    test_db.execute(
        "UPDATE users SET last_reminder_at = %s WHERE tg_user_id = %s",
        (epoch, DM_USER_ID),
    )
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID, last_catchup=epoch)
    # New message after last_catchup
    seeds.seed_message(
        tg_chat_id=GROUP_CHAT_ID,
        tg_msg_id=90001,
        tg_user_id=DM_USER_ID,
        text="something new",
    )
    mock_llms.reminder = "📬 1 new message. Use /catchup for details."

    resp = tg_client._client.post("/api/check-reminders")
    assert resp.status_code == 200
    assert resp.json().get("reminders_sent") == 1

    # Bot sent a DM to the user
    dm_replies = recording_bot.replies_to(DM_USER_ID)
    assert len(dm_replies) == 1
    assert "new message" in dm_replies[0]["text"].lower() or "📬" in dm_replies[0]["text"]


def test_check_reminders_skips_off_users(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Users with reminder_frequency='off' don't get pinged."""
    seeds.seed_user_chat_state(DM_USER_ID, GROUP_CHAT_ID)
    db.update_user_reminder(DM_USER_ID, "off")

    resp = tg_client._client.post("/api/check-reminders")
    assert resp.json().get("reminders_sent") == 0
    assert recording_bot.replies_to(DM_USER_ID) == []


# ----------------------------------------------------------------------------
# /api/cleanup-messages
# ----------------------------------------------------------------------------


def test_cleanup_messages_empty(tg_client, test_db, recording_bot):
    """No scheduled deletions → processed=0."""
    resp = tg_client._client.post("/api/cleanup-messages")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("ok") is True
    assert body.get("processed") == 0


def test_cleanup_messages_deletes_due_only(
    tg_client, test_db, recording_bot
):
    """Past deletions are processed; future deletions are retained."""
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=1)
    future = now + timedelta(hours=1)

    # 2 due, 1 future
    db.schedule_message_deletion(GROUP_CHAT_ID, 11111, past)
    db.schedule_message_deletion(GROUP_CHAT_ID, 22222, past)
    db.schedule_message_deletion(GROUP_CHAT_ID, 33333, future)

    resp = tg_client._client.post("/api/cleanup-messages")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("processed") == 2

    # RecordingBot saw 2 delete_message calls
    deleted = recording_bot.deleted_messages()
    assert (GROUP_CHAT_ID, 11111) in deleted
    assert (GROUP_CHAT_ID, 22222) in deleted
    assert (GROUP_CHAT_ID, 33333) not in deleted

    # Future deletion still in DB
    remaining = test_db.execute(
        "SELECT tg_message_id FROM scheduled_deletions"
    ).fetchall()
    assert {r[0] for r in remaining} == {33333}
