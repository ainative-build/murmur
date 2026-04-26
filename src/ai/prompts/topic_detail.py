"""Topic detail synthesis prompt — system instruction and prompt builder."""

SYSTEM = """You are Murmur. Synthesize everything discussed about a specific topic.

Rules:
- Cite every point as [username, date] or [link: title]
- Include: key arguments, decisions, open questions
- If links were shared, summarize their relevance
- Keep under 3000 chars
"""


def build_prompt(messages: list[dict], links: list[dict], topic_name: str) -> str:
    """Build topic detail prompt from messages, links, and topic name."""
    msg_lines = [
        f"[{m.get('timestamp', '')[:16]} {m.get('username', '?')}]: {m.get('text', '')}"
        for m in messages
    ]
    link_lines = [
        f"🔗 [{ls.get('title', ls.get('url', ''))}]: {ls.get('summary', '')[:200]}"
        for ls in links
    ]

    prompt = f"Topic: {topic_name}\n\nMessages:\n" + "\n".join(msg_lines)
    if link_lines:
        prompt += "\n\nRelated links:\n" + "\n".join(link_lines)

    return prompt
