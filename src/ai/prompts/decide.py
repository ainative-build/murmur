"""Decision view prompt — system instruction and prompt builder."""

SYSTEM = """You are Murmur. Compile a structured decision view from team discussions.

Format your response EXACTLY as:
## Options
(list each option identified from discussions)

## Arguments For/Against
(for each option: pros and cons, cited as [username, date])

## Key Evidence
(links and quotes that inform the decision, cited)

## What's Missing
(information gaps that need to be filled before deciding)

Rules:
- Every claim must cite [username, date] or [link: title]
- Be objective — present all sides
- Keep under 3000 chars
"""


def build_prompt(messages: list[dict], links: list[dict], topic: str) -> str:
    """Build decision view prompt from messages, links, and topic."""
    msg_lines = [
        f"[{m.get('timestamp', '')[:16]} {m.get('username', '?')}]: {m.get('text', '')}"
        for m in messages
    ]
    link_lines = [
        f"🔗 [{ls.get('title', ls.get('url', ''))}]: {ls.get('summary', '')[:200]}"
        for ls in links
    ]

    prompt = f"Decision topic: {topic}\n\nDiscussion:\n" + "\n".join(msg_lines)
    if link_lines:
        prompt += "\n\nShared evidence:\n" + "\n".join(link_lines)

    return prompt
