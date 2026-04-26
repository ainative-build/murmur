"""Reminder digest prompt — system instruction and prompt builder."""

SYSTEM = """You are Murmur. Generate a brief reminder digest.

Rules:
- Mention new message count and active topics
- List stale topics (>3 days no activity) if any
- Keep under 500 chars
- End with: "Use /catchup for full details"
"""


def build_prompt(
    message_count: int,
    topic_names: list[str],
    stale_topics: list[str],
) -> str:
    """Build reminder digest prompt from message count and topic lists."""
    return (
        f"New messages: {message_count}\n"
        f"Active topics: {', '.join(topic_names) if topic_names else 'none identified'}\n"
        f"Stale topics (>3 days): {', '.join(stale_topics) if stale_topics else 'none'}"
    )
