"""Format topic documents as structured markdown for NotebookLM export."""

import hashlib
from datetime import datetime, timezone


def format_topic_document(
    topic: str,
    messages: list[dict],
    links: list[dict],
    summary: str = "",
) -> str:
    """Build a structured markdown document for a topic.

    Returns markdown string suitable for NotebookLM ingestion.
    """
    lines = [f"# Topic: {topic}\n"]

    if summary:
        lines.append(f"## Summary\n{summary}\n")

    # Discussion timeline
    lines.append("## Discussion Timeline")
    for m in messages:
        user = m.get("username") or f"user_{m.get('tg_user_id', '?')}"
        ts = (m.get("timestamp") or "")[:16]
        text = m.get("text", "")
        lines.append(f"- [{ts} {user}]: {text}")
    lines.append("")

    # Key links
    if links:
        lines.append("## Key Links")
        for ls in links:
            url = ls.get("url", "")
            title = ls.get("title") or url
            link_summary = ls.get("summary", "")[:200]
            lines.append(f"- [{title}]({url}): {link_summary}")
        lines.append("")

    # Status heuristic: stale if no messages in last 3 days
    if messages:
        last_ts = messages[-1].get("timestamp", "")
        try:
            last_dt = datetime.fromisoformat(last_ts)
            days_ago = (datetime.now(timezone.utc) - last_dt).days
            if days_ago > 3:
                status = "Stale"
            else:
                status = "Active"
        except (ValueError, TypeError):
            status = "Unknown"
    else:
        status = "Unknown"

    lines.append(f"## Status: {status}")
    return "\n".join(lines)


def content_hash(content: str) -> str:
    """SHA256 hash of content for dedup."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()
