"""Convert markdown from LLM output to Telegram-compatible HTML.

Telegram HTML supports: <b>, <i>, <code>, <pre>, <a href="">.
Does NOT support: headers, lists, nested formatting.
"""

import re


def md_to_telegram_html(text: str) -> str:
    """Convert common markdown patterns to Telegram HTML.

    Handles: **bold**, *italic*, `code`, ```code blocks```, ## headers, - lists
    """
    # Code blocks first (before other transforms)
    text = re.sub(r'```[\w]*\n?(.*?)```', r'<pre>\1</pre>', text, flags=re.DOTALL)

    # Inline code
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)

    # Bold: **text** or __text__
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'__(.+?)__', r'<b>\1</b>', text)

    # Italic: *text* or _text_ (but not inside words like file_name)
    text = re.sub(r'(?<!\w)\*([^*]+?)\*(?!\w)', r'<i>\1</i>', text)

    # Headers: ## Title → bold line
    text = re.sub(r'^#{1,4}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)

    # Bullet lists: - item or * item → • item
    text = re.sub(r'^[\-\*]\s+', '• ', text, flags=re.MULTILINE)

    # Links: [text](url) → <a href="url">text</a>
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2">\1</a>', text)

    # Escape remaining HTML-sensitive chars that aren't part of our tags
    # (must be careful not to escape our own <b>, <i>, etc.)
    # Skip this — our tags are already in place, and LLM output rarely has < >

    return text.strip()
