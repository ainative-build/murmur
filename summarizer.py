"""Gemini 3 LLM calls via google-genai SDK — catchup, topics, draft, decide, reminders.

Uses API key locally, Vertex AI on Cloud Run (auto-detected via config.IS_CLOUD_RUN).
All calls async via .aio for non-blocking Telegram bot.
"""

import json
import logging
from typing import Optional

from google import genai
from google.genai import types

import config

logger = logging.getLogger(__name__)

# Singleton client — initialized lazily
_genai_client: Optional[genai.Client] = None

# Model IDs
MODEL_FLASH = "gemini-3-flash-preview"
MODEL_PRO = "gemini-3.1-pro-preview"


def get_genai_client() -> genai.Client:
    """Return singleton google-genai client."""
    global _genai_client
    if _genai_client is None:
        if config.IS_CLOUD_RUN and config.GOOGLE_CLOUD_PROJECT:
            # Production: Vertex AI with service account (auto-detected)
            _genai_client = genai.Client(
                vertexai=True,
                project=config.GOOGLE_CLOUD_PROJECT,
                location=config.GOOGLE_CLOUD_LOCATION,
            )
            logger.info("google-genai client initialized (Vertex AI)")
        elif config.GEMINI_API_KEY:
            # Local dev: API key
            _genai_client = genai.Client(api_key=config.GEMINI_API_KEY)
            logger.info("google-genai client initialized (API key)")
        else:
            raise RuntimeError("No Gemini credentials: set GEMINI_API_KEY or GOOGLE_CLOUD_PROJECT")
    return _genai_client


# ---------------------------------------------------------------------------
# Phase 2: Catchup digest
# ---------------------------------------------------------------------------

CATCHUP_SYSTEM = """You are Murmur, a team discussion summarizer. Create a concise catch-up digest from group messages.

Rules:
- Group messages by topic/thread
- For each topic: 1-2 sentence summary with the actual names of who said what
- Always use the EXACT usernames from the messages — copy them character-for-character (e.g. "@PMC836 said..." not "@C836" or "a user mentioned...")
- Mention shared links with brief description
- Format each topic as: "TOPIC NAME\nSummary with @username attributions\n"
- If links were shared, add: 🔗 link title/description
- Keep total digest under 2000 chars
- Write in the same language as the messages
- Do NOT use markdown formatting (no #, *, **, ```, etc.) — use plain text only
"""


async def generate_catchup(messages: list[dict], link_summaries: list[dict]) -> str:
    """Generate a catch-up digest from group messages and link summaries."""
    client = get_genai_client()

    # Build context from messages
    msg_lines = []
    for m in messages:
        user = m.get("username") or f"user_{m.get('tg_user_id', '?')}"
        text = m.get("text", "")
        ts = m.get("timestamp", "")[:16]  # trim to minute
        msg_lines.append(f"[{ts} {user}]: {text}")

    # Build link context
    link_lines = []
    for ls in link_summaries:
        title = ls.get("title") or ls.get("url", "")
        summary = ls.get("summary", "")[:200]
        link_lines.append(f"🔗 {title}: {summary}")

    prompt = f"Messages ({len(messages)} total):\n" + "\n".join(msg_lines[-200:])
    if link_lines:
        prompt += f"\n\nShared links ({len(link_lines)}):\n" + "\n".join(link_lines)

    try:
        response = await client.aio.models.generate_content(
            model=MODEL_FLASH,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=CATCHUP_SYSTEM,
                max_output_tokens=2048,
            ),
        )
        return response.text or "No digest generated."
    except Exception as e:
        logger.error(f"Catchup generation failed: {e}")
        return f"Sorry, I couldn't generate a digest right now. Error: {e}"


# ---------------------------------------------------------------------------
# Phase 3: Topics
# ---------------------------------------------------------------------------

TOPICS_SYSTEM = """You are Murmur, a team discussion analyzer. Identify 3-8 distinct discussion topics from the messages.

Rules:
- Each topic gets a short name (2-5 words) and a 1-2 sentence description
- Include key participants for each topic
- IMPORTANT: Copy usernames EXACTLY as they appear in the messages — do NOT shorten, modify, or abbreviate them. If the message says "PMC836", output "PMC836" not "C836".
- Return ONLY valid JSON array, no markdown
- Format: [{"name": "...", "description": "...", "participants": ["PMC836", "other_user"]}]
"""


async def generate_topics(messages: list[dict]) -> list[dict]:
    """Identify discussion topics from recent messages. Returns structured topic list."""
    client = get_genai_client()

    msg_lines = []
    for m in messages:
        user = m.get("username") or f"user_{m.get('tg_user_id', '?')}"
        msg_lines.append(f"[{m.get('timestamp', '')[:16]} {user}]: {m.get('text', '')}")

    prompt = f"Messages ({len(messages)} total):\n" + "\n".join(msg_lines[-200:])

    try:
        response = await client.aio.models.generate_content(
            model=MODEL_FLASH,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=TOPICS_SYSTEM,
                response_mime_type="application/json",
                max_output_tokens=2048,
            ),
        )
        return json.loads(response.text or "[]")
    except json.JSONDecodeError:
        logger.error(f"Topics JSON parse failed: {response.text[:200] if response else 'no response'}")
        return []
    except Exception as e:
        logger.error(f"Topics generation failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Phase 3: Topic detail
# ---------------------------------------------------------------------------

TOPIC_DETAIL_SYSTEM = """You are Murmur. Synthesize everything discussed about a specific topic.

Rules:
- Cite every point as [username, date] or [link: title]
- Include: key arguments, decisions, open questions
- If links were shared, summarize their relevance
- Keep under 3000 chars
"""


async def generate_topic_detail(
    messages: list[dict], links: list[dict], topic_name: str
) -> str:
    """Generate detailed synthesis of a specific topic with citations."""
    client = get_genai_client()

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

    try:
        response = await client.aio.models.generate_content(
            model=MODEL_FLASH,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=TOPIC_DETAIL_SYSTEM,
                max_output_tokens=3072,
            ),
        )
        return response.text or "No detail generated."
    except Exception as e:
        logger.error(f"Topic detail generation failed: {e}")
        return f"Sorry, I couldn't generate topic detail. Error: {e}"


# ---------------------------------------------------------------------------
# Phase 3: Decision view
# ---------------------------------------------------------------------------

DECIDE_SYSTEM = """You are Murmur. Compile a structured decision view from team discussions.

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


async def generate_decision_view(
    messages: list[dict], links: list[dict], topic: str
) -> str:
    """Generate structured decision view with citations."""
    client = get_genai_client()

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

    try:
        response = await client.aio.models.generate_content(
            model=MODEL_FLASH,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=DECIDE_SYSTEM,
                max_output_tokens=3072,
            ),
        )
        return response.text or "No decision view generated."
    except Exception as e:
        logger.error(f"Decision view generation failed: {e}")
        return f"Sorry, I couldn't generate a decision view. Error: {e}"


# ---------------------------------------------------------------------------
# Phase 3: Draft mode (multi-turn)
# ---------------------------------------------------------------------------

def build_draft_system_prompt(context: str) -> str:
    """Build system instruction for draft mode with team context."""
    return f"""You are Murmur, helping the user prepare their position on a topic.

Here's the team context:
{context}

Rules:
- Challenge the user's assumptions constructively
- Suggest angles they may have missed
- Reference specific team discussions: [username, date]
- Help them articulate clearly and persuasively
- Keep responses concise (under 500 chars per turn)
"""


async def generate_draft_response(
    conversation_history: list[dict], system_prompt: str
) -> str:
    """Generate a draft response in multi-turn conversation using Gemini 3.1 Pro."""
    client = get_genai_client()

    # Build contents list for multi-turn
    contents = []
    for msg in conversation_history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(types.Content(
            role=role,
            parts=[types.Part(text=msg["content"])],
        ))

    try:
        response = await client.aio.models.generate_content(
            model=MODEL_PRO,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                max_output_tokens=1024,
            ),
        )
        return response.text or "..."
    except Exception as e:
        logger.error(f"Draft response generation failed: {e}")
        return f"Sorry, I had trouble generating a response. Error: {e}"


# ---------------------------------------------------------------------------
# Phase 4: Reminder digest
# ---------------------------------------------------------------------------

REMINDER_SYSTEM = """You are Murmur. Generate a brief reminder digest.

Rules:
- Mention new message count and active topics
- List stale topics (>3 days no activity) if any
- Keep under 500 chars
- End with: "Use /catchup for full details"
"""


async def generate_reminder_digest(
    message_count: int, topic_names: list[str], stale_topics: list[str]
) -> str:
    """Generate a brief reminder digest for DM."""
    client = get_genai_client()

    prompt = (
        f"New messages: {message_count}\n"
        f"Active topics: {', '.join(topic_names) if topic_names else 'none identified'}\n"
        f"Stale topics (>3 days): {', '.join(stale_topics) if stale_topics else 'none'}"
    )

    try:
        response = await client.aio.models.generate_content(
            model=MODEL_FLASH,
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=REMINDER_SYSTEM,
                max_output_tokens=512,
            ),
        )
        return response.text or f"📬 {message_count} new messages. Use /catchup for details."
    except Exception as e:
        logger.error(f"Reminder digest generation failed: {e}")
        return f"📬 {message_count} new messages. Use /catchup for details."
