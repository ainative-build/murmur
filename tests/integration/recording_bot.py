"""Bot shim that records outbound calls instead of hitting the Telegram API.

`RecordingBot` is a `telegram.Bot` subclass that overrides the methods our
production code awaits on (`send_message`, `set_webhook`, `delete_webhook`,
`get_file`, `delete_message`). Each call is appended to `self.calls`. Tests
inspect `outbox.replies_to(chat_id)` etc. for assertions.

Failure-injection knobs (composable):
- `fail_after_n_replies`: raise on the (N+1)-th `send_message` call
- `html_parse_fails`: raise on every HTML send_message (parse_mode set)
- `fail_all_replies`: raise on every send_message
"""

from datetime import datetime, timezone
from typing import Any, Optional
from unittest.mock import AsyncMock

from telegram import Bot, Chat, Message, User
from telegram.request import BaseRequest


class _NoopRequest(BaseRequest):
    """Request impl that never makes network calls. Used by RecordingBot so
    the underlying Bot has no httpx client trying to reach api.telegram.org."""

    @property
    def read_timeout(self) -> Optional[float]:
        return 5.0

    async def initialize(self) -> None:
        return None

    async def shutdown(self) -> None:
        return None

    async def do_request(self, *args: Any, **kwargs: Any) -> tuple[int, bytes]:
        # Production code that bypasses our overrides should not reach here.
        # If it does, fail loud — better than a silent network attempt.
        raise RuntimeError(
            f"RecordingBot received a real network request: args={args[:2]!r}"
        )


class _Recorder:
    """Sidecar holding mutable recording/failure state.

    Lives outside the Bot subclass because `TelegramObject.__setattr__`
    blocks ad-hoc instance attributes.
    """

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.fail_after_n_replies: Optional[int] = None
        self.html_parse_fails: bool = False
        self.fail_all_replies: bool = False
        self.next_message_id: int = 10_000

    def reset(self) -> None:
        self.calls.clear()
        self.fail_after_n_replies = None
        self.html_parse_fails = False
        self.fail_all_replies = False


class RecordingBot(Bot):
    """Bot subclass that records calls and never touches the network."""

    def __init__(self, token: str = "test:token", bot_id: int = 9999, bot_username: str = "test_bot"):
        super().__init__(token=token, request=_NoopRequest(), get_updates_request=_NoopRequest())
        # PTB's TelegramObject blocks plain attribute assignment; bypass with object.__setattr__.
        object.__setattr__(self, "_recorder", _Recorder())
        object.__setattr__(self, "_bot_user_override", User(
            id=bot_id, is_bot=True, first_name="TestBot", username=bot_username
        ))

    # ---------------------------- introspection ----------------------------

    @property
    def recorder(self) -> _Recorder:
        return object.__getattribute__(self, "_recorder")

    @property
    def calls(self) -> list[dict]:
        return self.recorder.calls

    @property
    def reply_count(self) -> int:
        return sum(1 for c in self.calls if c["method"] == "send_message")

    # Read-only convenience accessors. Tests set knobs via bot.recorder.X = value
    # because TelegramObject blocks ad-hoc attribute setters on the bot itself.
    @property
    def fail_after_n_replies(self) -> Optional[int]:
        return self.recorder.fail_after_n_replies

    @property
    def html_parse_fails(self) -> bool:
        return self.recorder.html_parse_fails

    @property
    def fail_all_replies(self) -> bool:
        return self.recorder.fail_all_replies

    def replies_to(self, chat_id: int) -> list[dict]:
        """All send_message calls targeting `chat_id`."""
        return [c for c in self.calls if c["method"] == "send_message" and c["chat_id"] == chat_id]

    def documents_sent_to(self, chat_id: int) -> list[dict]:
        return [c for c in self.calls if c["method"] == "send_document" and c["chat_id"] == chat_id]

    def deleted_messages(self) -> list[tuple[int, int]]:
        return [(c["chat_id"], c["message_id"]) for c in self.calls if c["method"] == "delete_message"]

    def reset(self) -> None:
        """Clear recording state between tests if the same bot is reused."""
        self.recorder.reset()

    # ---------------------------- overrides --------------------------------

    async def initialize(self) -> None:  # type: ignore[override]
        # Skip PTB's get_me network call.
        object.__setattr__(self, "_initialized", True)

    async def shutdown(self) -> None:  # type: ignore[override]
        object.__setattr__(self, "_initialized", False)

    async def get_me(self, *args: Any, **kwargs: Any) -> User:  # type: ignore[override]
        return object.__getattribute__(self, "_bot_user_override")

    @property
    def bot(self) -> User:  # type: ignore[override]
        return object.__getattribute__(self, "_bot_user_override")

    @property
    def id(self) -> int:  # type: ignore[override]
        return self.bot.id

    @property
    def username(self) -> str:  # type: ignore[override]
        return self.bot.username  # type: ignore[return-value]

    async def send_message(  # type: ignore[override]
        self,
        chat_id: int,
        text: str,
        parse_mode: Optional[str] = None,
        **kwargs: Any,
    ) -> Message:
        # Failure injection BEFORE recording: failed sends are not "deliveries".
        rec = self.recorder
        if rec.fail_all_replies:
            raise RuntimeError("RecordingBot: fail_all_replies enabled")
        if rec.html_parse_fails and parse_mode:
            raise RuntimeError("RecordingBot: html_parse_fails enabled (HTML attempt)")
        if rec.fail_after_n_replies is not None and self.reply_count >= rec.fail_after_n_replies:
            raise RuntimeError(
                f"RecordingBot: fail_after_n_replies={rec.fail_after_n_replies} reached"
            )

        rec.calls.append({
            "method": "send_message",
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "kwargs": kwargs,
        })
        return self._make_message(chat_id, text)

    async def send_document(  # type: ignore[override]
        self,
        chat_id: int,
        document: Any,
        filename: Optional[str] = None,
        **kwargs: Any,
    ) -> Message:
        self.recorder.calls.append({
            "method": "send_document",
            "chat_id": chat_id,
            "filename": filename or getattr(document, "name", None),
            "kwargs": kwargs,
        })
        return self._make_message(chat_id, text="")

    async def set_webhook(self, url: str, **kwargs: Any) -> bool:  # type: ignore[override]
        self.recorder.calls.append({"method": "set_webhook", "url": url, "kwargs": kwargs})
        return True

    async def delete_webhook(self, **kwargs: Any) -> bool:  # type: ignore[override]
        self.recorder.calls.append({"method": "delete_webhook", "kwargs": kwargs})
        return True

    async def delete_message(self, chat_id: int, message_id: int, **kwargs: Any) -> bool:  # type: ignore[override]
        self.recorder.calls.append({"method": "delete_message", "chat_id": chat_id, "message_id": message_id})
        return True

    async def get_file(self, file_id: str, **kwargs: Any) -> Any:  # type: ignore[override]
        self.recorder.calls.append({"method": "get_file", "file_id": file_id})
        mock_file = AsyncMock()
        mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"\x00\x00\x00"))
        return mock_file

    # ---------------------------- helpers ----------------------------------

    def _make_message(self, chat_id: int, text: str) -> Message:
        """Construct a minimal Message satisfying callers needing chat_id/message_id."""
        rec = self.recorder
        msg_id = rec.next_message_id
        rec.next_message_id += 1
        chat = Chat(id=chat_id, type="group" if chat_id < 0 else "private")
        msg = Message(
            message_id=msg_id,
            date=datetime.now(timezone.utc),
            chat=chat,
            from_user=self.bot,
            text=text,
        )
        msg.set_bot(self)
        return msg
