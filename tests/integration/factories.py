"""Synthetic Telegram update payload factories.

Each factory returns a `dict` shaped like a real Telegram webhook payload.
Pass to `tg_client.post_update(payload)` or `dispatcher.dispatch(payload)`.

Validated at construction time via `Update.de_json` so a factory bug surfaces
immediately, not during dispatch.
"""

from datetime import datetime, timezone
from typing import Any, Optional

from telegram import Update


# Counter for unique update_ids across a test session.
_update_counter = {"n": 1_000_000}


def _next_update_id() -> int:
    _update_counter["n"] += 1
    return _update_counter["n"]


def _ts() -> int:
    return int(datetime.now(timezone.utc).timestamp())


def _user(user_id: int, username: str = "alice", first_name: str = "Alice") -> dict:
    return {
        "id": user_id,
        "is_bot": False,
        "first_name": first_name,
        "username": username,
        "language_code": "en",
    }


def _chat_group(chat_id: int) -> dict:
    return {"id": chat_id, "type": "supergroup", "title": "Test Group"}


def _chat_private(user_id: int, username: str = "alice", first_name: str = "Alice") -> dict:
    return {
        "id": user_id,
        "type": "private",
        "first_name": first_name,
        "username": username,
    }


def _validate(payload: dict, bot) -> dict:
    """Validate by feeding through Update.de_json. Raises if shape is wrong."""
    Update.de_json(payload, bot)
    return payload


# ============================================================================
# Group updates
# ============================================================================


def group_text_update(
    *,
    chat_id: int,
    msg_id: int,
    user_id: int,
    username: str = "alice",
    first_name: str = "Alice",
    text: str,
    bot,
    reply_to_msg_id: Optional[int] = None,
    forward_from_username: Optional[str] = None,
) -> dict:
    """Group text message — the workhorse for link-summarisation tests."""
    msg = {
        "message_id": msg_id,
        "from": _user(user_id, username, first_name),
        "chat": _chat_group(chat_id),
        "date": _ts(),
        "text": text,
    }
    if reply_to_msg_id is not None:
        msg["reply_to_message"] = {
            "message_id": reply_to_msg_id,
            "from": _user(user_id + 1, "bob", "Bob"),
            "chat": _chat_group(chat_id),
            "date": _ts(),
            "text": "earlier message",
        }
    if forward_from_username is not None:
        msg["forward_origin"] = {
            "type": "user",
            "date": _ts(),
            "sender_user": _user(user_id + 99, forward_from_username, forward_from_username),
        }
    payload = {"update_id": _next_update_id(), "message": msg}
    return _validate(payload, bot)


def group_voice_update(
    *,
    chat_id: int,
    msg_id: int,
    user_id: int,
    username: str = "alice",
    duration: int = 8,
    file_id: str = "voice_file_id_001",
    mime_type: str = "audio/ogg",
    bot,
) -> dict:
    """Group voice message."""
    msg = {
        "message_id": msg_id,
        "from": _user(user_id, username),
        "chat": _chat_group(chat_id),
        "date": _ts(),
        "voice": {
            "duration": duration,
            "mime_type": mime_type,
            "file_id": file_id,
            "file_unique_id": f"unique_{file_id}",
            "file_size": 1024 * duration,
        },
    }
    payload = {"update_id": _next_update_id(), "message": msg}
    return _validate(payload, bot)


def group_audio_update(
    *,
    chat_id: int,
    msg_id: int,
    user_id: int,
    username: str = "alice",
    duration: int = 30,
    file_id: str = "audio_file_id_001",
    mime_type: str = "audio/mpeg",
    bot,
) -> dict:
    """Group audio message (mp3 etc.)."""
    msg = {
        "message_id": msg_id,
        "from": _user(user_id, username),
        "chat": _chat_group(chat_id),
        "date": _ts(),
        "audio": {
            "duration": duration,
            "mime_type": mime_type,
            "file_id": file_id,
            "file_unique_id": f"unique_{file_id}",
            "file_size": 4096 * duration,
            "title": "Audio Track",
        },
    }
    payload = {"update_id": _next_update_id(), "message": msg}
    return _validate(payload, bot)


def group_photo_update(
    *,
    chat_id: int,
    msg_id: int,
    user_id: int,
    username: str = "alice",
    caption: Optional[str] = None,
    bot,
    sizes: Optional[list[tuple[int, int]]] = None,
) -> dict:
    """Group photo message. `sizes` defaults to 3 sizes ending at 640x480."""
    sizes = sizes or [(90, 90), (320, 240), (640, 480)]
    photo_array = [
        {
            "file_id": f"photo_file_{i}",
            "file_unique_id": f"unique_photo_{i}",
            "width": w,
            "height": h,
            "file_size": w * h * 3,
        }
        for i, (w, h) in enumerate(sizes)
    ]
    msg = {
        "message_id": msg_id,
        "from": _user(user_id, username),
        "chat": _chat_group(chat_id),
        "date": _ts(),
        "photo": photo_array,
    }
    if caption is not None:
        msg["caption"] = caption
    payload = {"update_id": _next_update_id(), "message": msg}
    return _validate(payload, bot)


def group_document_update(
    *,
    chat_id: int,
    msg_id: int,
    user_id: int,
    username: str = "alice",
    filename: str,
    mime_type: str = "application/pdf",
    file_size: int = 100_000,
    file_id: str = "doc_file_id_001",
    bot,
) -> dict:
    """Group document upload."""
    msg = {
        "message_id": msg_id,
        "from": _user(user_id, username),
        "chat": _chat_group(chat_id),
        "date": _ts(),
        "document": {
            "file_name": filename,
            "mime_type": mime_type,
            "file_id": file_id,
            "file_unique_id": f"unique_{file_id}",
            "file_size": file_size,
        },
    }
    payload = {"update_id": _next_update_id(), "message": msg}
    return _validate(payload, bot)


# ============================================================================
# DM updates
# ============================================================================


def dm_command_update(
    *,
    user_id: int,
    username: str = "alice",
    first_name: str = "Alice",
    command: str,
    args: Optional[str] = None,
    msg_id: Optional[int] = None,
    bot,
) -> dict:
    """DM /command [args] — `command` should be the bare command without slash."""
    text = f"/{command}"
    if args:
        text = f"{text} {args}"
    return _dm_text(
        user_id=user_id,
        username=username,
        first_name=first_name,
        text=text,
        msg_id=msg_id or (50_000 + _update_counter["n"] % 10_000),
        bot=bot,
        is_command=True,
    )


def dm_text_update(
    *,
    user_id: int,
    username: str = "alice",
    first_name: str = "Alice",
    text: str,
    msg_id: Optional[int] = None,
    bot,
    forward_from_username: Optional[str] = None,
) -> dict:
    """DM plain text or text-with-link."""
    return _dm_text(
        user_id=user_id,
        username=username,
        first_name=first_name,
        text=text,
        msg_id=msg_id or (60_000 + _update_counter["n"] % 10_000),
        bot=bot,
        is_command=False,
        forward_from_username=forward_from_username,
    )


def _dm_text(
    *,
    user_id: int,
    username: str,
    first_name: str,
    text: str,
    msg_id: int,
    bot,
    is_command: bool,
    forward_from_username: Optional[str] = None,
) -> dict:
    msg: dict[str, Any] = {
        "message_id": msg_id,
        "from": _user(user_id, username, first_name),
        "chat": _chat_private(user_id, username, first_name),
        "date": _ts(),
        "text": text,
    }
    if is_command and text.startswith("/"):
        # Telegram includes a `bot_command` entity for commands
        cmd_end = text.find(" ") if " " in text else len(text)
        msg["entities"] = [{"type": "bot_command", "offset": 0, "length": cmd_end}]
    if forward_from_username is not None:
        msg["forward_origin"] = {
            "type": "user",
            "date": _ts(),
            "sender_user": _user(user_id + 99, forward_from_username, forward_from_username),
        }
    payload = {"update_id": _next_update_id(), "message": msg}
    return _validate(payload, bot)


def dm_voice_update(
    *,
    user_id: int,
    username: str = "alice",
    duration: int = 8,
    file_id: str = "dm_voice_001",
    mime_type: str = "audio/ogg",
    msg_id: Optional[int] = None,
    bot,
) -> dict:
    msg = {
        "message_id": msg_id or (70_000 + _update_counter["n"] % 10_000),
        "from": _user(user_id, username),
        "chat": _chat_private(user_id, username),
        "date": _ts(),
        "voice": {
            "duration": duration,
            "mime_type": mime_type,
            "file_id": file_id,
            "file_unique_id": f"unique_{file_id}",
            "file_size": 1024 * duration,
        },
    }
    payload = {"update_id": _next_update_id(), "message": msg}
    return _validate(payload, bot)


def dm_document_update(
    *,
    user_id: int,
    username: str = "alice",
    filename: str,
    mime_type: str = "application/pdf",
    file_size: int = 100_000,
    file_id: str = "dm_doc_001",
    msg_id: Optional[int] = None,
    bot,
) -> dict:
    msg = {
        "message_id": msg_id or (80_000 + _update_counter["n"] % 10_000),
        "from": _user(user_id, username),
        "chat": _chat_private(user_id, username),
        "date": _ts(),
        "document": {
            "file_name": filename,
            "mime_type": mime_type,
            "file_id": file_id,
            "file_unique_id": f"unique_{file_id}",
            "file_size": file_size,
        },
    }
    payload = {"update_id": _next_update_id(), "message": msg}
    return _validate(payload, bot)
