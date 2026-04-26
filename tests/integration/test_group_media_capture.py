"""Group voice / photo / document capture tests.

Voice: silent transcription (stored, no reply).
Photo: silent description via Gemini vision (stored, no reply).
Document: extracted; replied with summary IFF text ≥ 1000 chars.
"""

import pytest

from tests.integration.factories import (
    group_voice_update,
    group_audio_update,
    group_photo_update,
    group_document_update,
)
from tests.integration.conftest import GROUP_CHAT_ID, DM_USER_ID


pytestmark = pytest.mark.integration


def _query_messages(test_db, tg_chat_id: int):
    with test_db.cursor() as cur:
        cur.execute(
            "SELECT text, media_type, source_filename FROM messages WHERE tg_chat_id = %s ORDER BY id",
            (tg_chat_id,),
        )
        return cur.fetchall()


# ----------------------------------------------------------------------------
# Voice / audio — silent capture
# ----------------------------------------------------------------------------


def test_group_voice_transcribed_silent(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Voice → transcribed by Gemini, stored. NO reply in group."""
    mock_extractors.voice_transcript = "hi there from the test fixture"

    update = group_voice_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=40001,
        user_id=DM_USER_ID,
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = _query_messages(test_db, GROUP_CHAT_ID)
    assert len(msgs) == 1
    text, media_type, _ = msgs[0]
    assert "[Voice: hi there from the test fixture]" in text
    assert media_type == "voice"
    # No reply sent — voice is silent
    assert recording_bot.replies_to(GROUP_CHAT_ID) == []


def test_group_voice_transcription_failure_silent(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Transcription returns None → message NOT stored (no text), no reply."""
    mock_extractors.voice_transcript = None

    update = group_voice_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=40002,
        user_id=DM_USER_ID,
        bot=recording_bot,
    )
    tg_client.post_update(update)

    # No text → no message row, no reply
    assert _query_messages(test_db, GROUP_CHAT_ID) == []
    assert recording_bot.replies_to(GROUP_CHAT_ID) == []


def test_group_audio_mp3_transcribed_silent(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Audio file (mp3) is treated like voice — transcribed silently."""
    mock_extractors.voice_transcript = "transcribed mp3 content"

    update = group_audio_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=40003,
        user_id=DM_USER_ID,
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = _query_messages(test_db, GROUP_CHAT_ID)
    assert len(msgs) == 1
    assert "[Voice: transcribed mp3 content]" in msgs[0][0]
    assert msgs[0][1] == "audio"
    assert recording_bot.replies_to(GROUP_CHAT_ID) == []


# ----------------------------------------------------------------------------
# Photo — silent description via Gemini vision
# ----------------------------------------------------------------------------


def test_group_photo_described_silent(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Photo → Gemini-vision description, stored as text. No reply."""
    mock_extractors.image_description = "A whiteboard sketch of a system architecture."

    update = group_photo_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=40004,
        user_id=DM_USER_ID,
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = _query_messages(test_db, GROUP_CHAT_ID)
    assert len(msgs) == 1
    text, media_type, _ = msgs[0]
    assert "[Image: A whiteboard sketch" in text
    assert media_type == "photo"
    assert recording_bot.replies_to(GROUP_CHAT_ID) == []


def test_group_photo_with_caption_includes_caption_in_text(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Photo with caption → caption is preserved alongside the description."""
    mock_extractors.image_description = "A graph showing latency over time."

    update = group_photo_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=40005,
        user_id=DM_USER_ID,
        caption="check this metric",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = _query_messages(test_db, GROUP_CHAT_ID)
    assert len(msgs) == 1
    text = msgs[0][0]
    assert "[Image: A graph" in text
    assert "check this metric" in text


def test_group_photo_analysis_failure_no_message_stored(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Vision returns None and no caption → no text → no message row."""
    mock_extractors.image_description = None

    update = group_photo_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=40006,
        user_id=DM_USER_ID,
        bot=recording_bot,
    )
    tg_client.post_update(update)

    assert _query_messages(test_db, GROUP_CHAT_ID) == []


# ----------------------------------------------------------------------------
# Document — extracted; reply IFF text ≥ 1000 chars
# ----------------------------------------------------------------------------


def test_group_document_long_text_summarised_with_reply(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Document ≥1000 chars → BAML summary, reply in group, message stored."""
    mock_extractors.file_extract_text = "Long document body. " * 100  # ~2000 chars
    mock_llms.set_summary(
        title="Whitepaper", key_points=["abstract", "results"], summary="..."
    )

    update = group_document_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=40007,
        user_id=DM_USER_ID,
        filename="whitepaper.pdf",
        mime_type="application/pdf",
        file_size=200_000,
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = _query_messages(test_db, GROUP_CHAT_ID)
    assert len(msgs) == 1
    _, media_type, source_filename = msgs[0]
    assert media_type == "file"
    assert source_filename == "whitepaper.pdf"

    replies = recording_bot.replies_to(GROUP_CHAT_ID)
    assert len(replies) >= 1
    assert "Whitepaper" in "".join(r["text"] for r in replies)


def test_group_document_short_text_no_summary_reply(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Document <1000 chars → message stored, NO summary reply."""
    mock_extractors.file_extract_text = "Brief note. ~50 chars."

    update = group_document_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=40008,
        user_id=DM_USER_ID,
        filename="note.pdf",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = _query_messages(test_db, GROUP_CHAT_ID)
    assert len(msgs) == 1
    assert msgs[0][1] == "file"
    # No reply because text < 1000 chars
    assert recording_bot.replies_to(GROUP_CHAT_ID) == []


def test_group_document_oversized_skipped_entirely(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Document >5MB → extraction skipped pre-BAML, no reply, message-only-if-text."""
    # Don't return extract — production path skips it for oversized files
    mock_extractors.file_extract_text = None

    update = group_document_update(
        chat_id=GROUP_CHAT_ID,
        msg_id=40009,
        user_id=DM_USER_ID,
        filename="huge.pdf",
        file_size=6 * 1024 * 1024,  # 6MB
        bot=recording_bot,
    )
    tg_client.post_update(update)

    # No message text → no row, no reply
    assert _query_messages(test_db, GROUP_CHAT_ID) == []
    assert recording_bot.replies_to(GROUP_CHAT_ID) == []
