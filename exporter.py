"""Topic export orchestrator — exports to NotebookLM with Google Drive fallback.

Reuses topic detection from summarizer (same as /topics).
Dedup via content_hash in exports table.
"""

import logging
import os
from typing import Optional

import db
import summarizer
from export_formatter import format_topic_document, content_hash

logger = logging.getLogger(__name__)

NOTEBOOKLM_NOTEBOOK_ID = os.getenv("NOTEBOOKLM_NOTEBOOK_ID", "")
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "")


async def export_topics(tg_chat_id: Optional[int] = None) -> int:
    """Export new/updated topics to NotebookLM. Returns count exported.

    If tg_chat_id is None, exports from all chats with recent activity.
    """
    exported = 0

    # Get recent messages to identify topics
    if tg_chat_id:
        chat_ids = [tg_chat_id]
    else:
        # Get all chats with recent messages (simplification: query messages table)
        client = db.get_client()
        try:
            result = (
                client.table("messages")
                .select("tg_chat_id")
                .order("timestamp", desc=True)
                .limit(1)
                .execute()
            )
            chat_ids = list({r["tg_chat_id"] for r in (result.data or [])})
        except Exception as e:
            logger.error(f"Failed to get active chats: {e}")
            return 0

    for chat_id in chat_ids:
        messages = db.get_recent_messages(chat_id, hours=48)
        if not messages:
            continue

        # Detect topics via LLM
        topics = await summarizer.generate_topics(messages)
        if not topics:
            continue

        for topic_data in topics:
            topic_name = topic_data.get("name", "Untitled")

            # Get messages related to this topic
            topic_messages = db.get_messages_by_keyword(chat_id, topic_name, hours=72)
            if not topic_messages:
                topic_messages = messages  # fallback to all recent

            # Get related links
            msg_ids = [m["id"] for m in topic_messages if m.get("has_links")]
            links = db.get_link_summaries_for_messages(msg_ids)

            # Format document
            doc = format_topic_document(
                topic=topic_name,
                messages=topic_messages,
                links=links,
                summary=topic_data.get("description", ""),
            )

            # Check dedup
            doc_hash = content_hash(doc)
            if db.export_exists("notebooklm", doc_hash):
                logger.info(f"Topic '{topic_name}' unchanged, skipping export")
                continue

            # Try NotebookLM upload
            success = await _upload_to_notebooklm(topic_name, doc)
            target = "notebooklm"

            if not success:
                # Fallback to Google Drive
                success = _upload_to_gdrive(topic_name, doc)
                target = "gdrive"

            if not success:
                # Last resort: local markdown
                _export_to_markdown(topic_name, doc)
                target = "markdown"

            # Record export
            db.store_export(
                topic=topic_name,
                export_target=target,
                content_hash=doc_hash,
            )
            exported += 1
            logger.info(f"Exported topic '{topic_name}' to {target}")

    return exported


async def _upload_to_notebooklm(title: str, content: str) -> bool:
    """Upload a document to NotebookLM via notebooklm-py."""
    if not NOTEBOOKLM_NOTEBOOK_ID:
        logger.warning("NOTEBOOKLM_NOTEBOOK_ID not set, skipping NotebookLM upload")
        return False

    try:
        from notebooklm import NotebookLM
        nlm = NotebookLM()
        nlm.add_source(
            notebook_id=NOTEBOOKLM_NOTEBOOK_ID,
            source_type="text",
            title=title,
            content=content,
        )
        return True
    except ImportError:
        logger.warning("notebooklm-py not installed, skipping NotebookLM upload")
        return False
    except Exception as e:
        logger.error(f"NotebookLM upload failed: {e}")
        return False


def _upload_to_gdrive(title: str, content: str) -> bool:
    """Upload markdown to Google Drive as fallback."""
    if not GDRIVE_FOLDER_ID:
        logger.warning("GDRIVE_FOLDER_ID not set, skipping Google Drive upload")
        return False

    try:
        from googleapiclient.discovery import build
        from google.oauth2 import service_account

        creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "")
        if not creds_path:
            return False

        creds = service_account.Credentials.from_service_account_file(creds_path)
        service = build("drive", "v3", credentials=creds)

        file_metadata = {
            "name": f"{title}.md",
            "parents": [GDRIVE_FOLDER_ID],
            "mimeType": "text/markdown",
        }
        from googleapiclient.http import MediaInMemoryUpload
        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/markdown")
        service.files().create(body=file_metadata, media_body=media).execute()
        return True
    except Exception as e:
        logger.error(f"Google Drive upload failed: {e}")
        return False


def _export_to_markdown(title: str, content: str) -> None:
    """Local fallback: write markdown file."""
    os.makedirs("exports", exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in title)
    filepath = f"exports/{safe_name}.md"
    with open(filepath, "w") as f:
        f.write(content)
    logger.info(f"Exported topic to local file: {filepath}")
