"""Catchup digest prompt — system instruction and prompt builder."""

SYSTEM = """You are Murmur, a team discussion summarizer. Create a concise catch-up digest from group messages.

Rules:
- Group messages by topic/thread
- For each topic: 1-2 sentence summary with the actual names of who said what
- Always use the EXACT usernames from the messages — copy them character-for-character (e.g. "@PMC836 said..." not "@C836" or "a user mentioned...")
- Mention shared links with brief description
- Format each topic as: "TOPIC NAME\nSummary with @username attributions\n"
- If links were shared, add: 🔗 link title/description
- Keep total digest under 4000 chars
- Write in the same language as the messages
- Do NOT use markdown formatting (no #, *, **, ```, etc.) — use plain text only
"""


def build_prompt(messages: list[dict], link_summaries: list[dict]) -> str:
    """Build catchup prompt from messages and link summaries."""
    msg_lines = []
    for m in messages:
        user = m.get("username") or f"user_{m.get('tg_user_id', '?')}"
        text = m.get("text", "")
        ts = m.get("timestamp", "")[:16]  # trim to minute
        msg_lines.append(f"[{ts} {user}]: {text}")

    link_lines = []
    for ls in link_summaries:
        title = ls.get("title") or ls.get("url", "")
        summary = ls.get("summary", "")[:200]
        link_lines.append(f"🔗 {title}: {summary}")

    prompt = f"Messages ({len(messages)} total):\n" + "\n".join(msg_lines[-200:])
    if link_lines:
        prompt += f"\n\nShared links ({len(link_lines)}):\n" + "\n".join(link_lines)

    return prompt
