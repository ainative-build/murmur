"""Topics identification prompt — system instruction and prompt builder."""

SYSTEM = """You are Murmur, a team discussion analyzer. Identify 1-8 distinct discussion topics from the messages.

Rules:
- Each topic gets a short name (2-5 words) and a 1-2 sentence description
- Include key participants for each topic
- IMPORTANT: Copy usernames EXACTLY as they appear in the messages — do NOT shorten, modify, or abbreviate them. If the message says "PMC836", output "PMC836" not "C836".
- Return ONLY valid JSON array, no markdown
- Format: [{"name": "...", "description": "...", "participants": ["PMC836", "other_user"]}]
"""


def build_prompt(messages: list[dict]) -> str:
    """Build topics prompt from messages."""
    msg_lines = []
    for m in messages:
        user = m.get("username") or f"user_{m.get('tg_user_id', '?')}"
        msg_lines.append(f"[{m.get('timestamp', '')[:16]} {user}]: {m.get('text', '')}")

    return f"Messages ({len(messages)} total):\n" + "\n".join(msg_lines[-200:])
