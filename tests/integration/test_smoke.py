"""Phase 1 smoke test — confirms the integration harness boots end-to-end.

Verifies:
- The test Postgres is reachable and migrations applied (test_db fixture).
- The FastAPI app builds with RecordingBot wired in.
- The /health endpoint responds 200.
- The webhook secret enforcement is active (no header → 403).
- The disable_real_http backstop fires when a test attempts an httpx call.

If this passes, Phase 2 and Phase 3 can build on top.
"""

import pytest


pytestmark = pytest.mark.integration


def test_postgres_reachable_and_schema_applied(test_db):
    """All 9 user tables exist via the migration apply."""
    with test_db.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' ORDER BY table_name
        """)
        tables = {row[0] for row in cur.fetchall()}
    expected = {
        "draft_sessions",
        "exports",
        "feedback",
        "link_summaries",
        "messages",
        "personal_sources",
        "scheduled_deletions",
        "user_chat_state",
        "users",
    }
    assert expected <= tables, f"missing tables: {expected - tables}"


def test_health_endpoint_returns_200(tg_client):
    """/health is the simplest end-to-end signal that FastAPI + lifespan boots."""
    resp = tg_client._client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_webhook_rejects_missing_secret(tg_client):
    """Webhook auth: requests without the secret header get 403."""
    resp = tg_client._client.post(
        f"/{tg_client._webhook_path}",
        json={"update_id": 1},
        headers={},  # no X-Telegram-Bot-Api-Secret-Token
    )
    assert resp.status_code == 403


def test_webhook_accepts_correct_secret(tg_client):
    """Webhook auth: correct secret token returns 200 even if payload is empty-ish."""
    resp = tg_client.post_update({"update_id": 999_999})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_real_http_is_disabled(disable_real_http):
    """The autouse fixture should make any httpx.AsyncClient.send raise."""
    import asyncio
    import httpx

    async def _attempt():
        async with httpx.AsyncClient() as client:
            await client.get("https://example.com")

    with pytest.raises(RuntimeError, match="Real HTTP attempted"):
        asyncio.run(_attempt())


def test_recording_bot_captures_send_message(recording_bot):
    """RecordingBot records send_message calls without network access."""
    import asyncio

    async def _send():
        await recording_bot.send_message(chat_id=-1001, text="hello")
        await recording_bot.send_message(chat_id=-1001, text="world")

    asyncio.run(_send())
    assert recording_bot.reply_count == 2
    assert [c["text"] for c in recording_bot.replies_to(-1001)] == ["hello", "world"]
