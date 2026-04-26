"""DM voice / document personal-source integration tests.

Voice DM → transcribed → saved as `personal_sources` row (source_type='voice').
Document DM → text extracted → saved (source_type='file').
Plus the CRUD command flow: /note, /sources, /delete.
"""

import pytest

from tests.integration.factories import (
    dm_voice_update,
    dm_document_update,
    dm_command_update,
)
from tests.integration.conftest import DM_USER_ID, SECOND_USER_ID
from tests.integration import seeds


pytestmark = pytest.mark.integration


def _personal_sources_for(test_db, user_id: int):
    return test_db.execute(
        "SELECT source_type, content, title FROM personal_sources WHERE tg_user_id = %s ORDER BY id",
        (user_id,),
    ).fetchall()


# ----------------------------------------------------------------------------
# Voice DM
# ----------------------------------------------------------------------------


def test_dm_voice_transcribed_and_saved(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_extractors.voice_transcript = "this is the transcribed voice content"

    update = dm_voice_update(user_id=DM_USER_ID, bot=recording_bot)
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "✅" in full or "saved" in full.lower()

    rows = _personal_sources_for(test_db, DM_USER_ID)
    assert len(rows) == 1
    source_type, content, title = rows[0]
    assert source_type == "voice"
    assert "transcribed voice content" in content


def test_dm_voice_transcription_fails_warns_user(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_extractors.voice_transcript = None

    update = dm_voice_update(user_id=DM_USER_ID, bot=recording_bot)
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "⚠️" in full or "Couldn't transcribe" in full
    # No row written
    assert _personal_sources_for(test_db, DM_USER_ID) == []


# ----------------------------------------------------------------------------
# Document DM
# ----------------------------------------------------------------------------


def test_dm_document_extracted_and_saved(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    mock_extractors.file_extract_text = "Document body. " * 80  # ~1200 chars

    update = dm_document_update(
        user_id=DM_USER_ID,
        filename="proposal.docx",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "✅" in full or "saved" in full.lower()
    assert "proposal.docx" in full

    rows = _personal_sources_for(test_db, DM_USER_ID)
    assert len(rows) == 1
    source_type, content, title = rows[0]
    assert source_type == "file"
    assert title == "proposal.docx"


def test_dm_document_unsupported_type_rejected(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Unsupported file type → extractor returns None → friendly warning."""
    mock_extractors.file_extract_text = None

    update = dm_document_update(
        user_id=DM_USER_ID,
        filename="random.exe",
        mime_type="application/x-msdownload",
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "⚠️" in full or "Couldn't extract" in full
    assert _personal_sources_for(test_db, DM_USER_ID) == []


def test_dm_document_oversized_rejected_pre_extract(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """Document >5MB → reject without invoking extractor."""
    update = dm_document_update(
        user_id=DM_USER_ID,
        filename="huge.pdf",
        file_size=6 * 1024 * 1024,
        bot=recording_bot,
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "too large" in full.lower() or "5MB" in full or "⚠️" in full
    assert _personal_sources_for(test_db, DM_USER_ID) == []


# ----------------------------------------------------------------------------
# /note, /sources, /delete CRUD
# ----------------------------------------------------------------------------


def test_dm_note_saved(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    update = dm_command_update(
        user_id=DM_USER_ID, command="note", args="this is important", bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "✅" in full or "saved" in full.lower()

    rows = _personal_sources_for(test_db, DM_USER_ID)
    assert len(rows) == 1
    assert rows[0][0] == "note"
    assert "this is important" in rows[0][1]


def test_dm_note_no_args_shows_usage(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    update = dm_command_update(user_id=DM_USER_ID, command="note", bot=recording_bot)
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    assert "Usage" in "".join(m["text"] for m in msgs)


def test_dm_sources_lists_recent(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    seeds.seed_personal_source(DM_USER_ID, source_type="note", content="first note")
    seeds.seed_personal_source(DM_USER_ID, source_type="note", content="second note")
    seeds.seed_personal_source(DM_USER_ID, source_type="note", content="third note")

    update = dm_command_update(user_id=DM_USER_ID, command="sources", bot=recording_bot)
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "Personal Sources" in full or "3 total" in full


def test_dm_sources_empty(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    update = dm_command_update(user_id=DM_USER_ID, command="sources", bot=recording_bot)
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "No personal sources" in full


def test_dm_delete_own_source(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    src_id = seeds.seed_personal_source(
        DM_USER_ID, source_type="note", content="to be deleted"
    )

    update = dm_command_update(
        user_id=DM_USER_ID, command="delete", args=str(src_id), bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "✅" in full or "deleted" in full.lower()
    # Row gone
    assert _personal_sources_for(test_db, DM_USER_ID) == []


def test_dm_delete_not_owner_rejected(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    """SECURITY: deleting someone else's source must fail with not-found error."""
    other_src_id = seeds.seed_personal_source(
        SECOND_USER_ID, source_type="note", content="other user's data"
    )

    update = dm_command_update(
        user_id=DM_USER_ID, command="delete", args=str(other_src_id), bot=recording_bot
    )
    tg_client.post_update(update)

    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "not found" in full.lower() or "not yours" in full.lower() or "❌" in full
    # Other user's row preserved
    other_rows = _personal_sources_for(test_db, SECOND_USER_ID)
    assert len(other_rows) == 1


# ----------------------------------------------------------------------------
# /start
# ----------------------------------------------------------------------------


def test_dm_start_sends_welcome(
    tg_client, test_db, recording_bot, mock_llms, mock_extractors
):
    update = dm_command_update(user_id=DM_USER_ID, command="start", bot=recording_bot)
    tg_client.post_update(update)
    msgs = recording_bot.replies_to(DM_USER_ID)
    full = "".join(m["text"] for m in msgs)
    assert "Murmur" in full
    assert "/catchup" in full  # command list present
