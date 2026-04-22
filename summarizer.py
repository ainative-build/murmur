"""Gemini 3 LLM calls via google-genai SDK — catchup, topics, draft, decide, reminders.

Uses API key locally, Vertex AI on Cloud Run (auto-detected via config.IS_CLOUD_RUN).
All calls async via .aio for non-blocking Telegram bot.
"""

import asyncio
import json
import logging
from typing import Optional

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

import config

logger = logging.getLogger(__name__)

# Singleton client — initialized lazily
_genai_client: Optional[genai.Client] = None

# Model IDs
MODEL_FLASH = "gemini-3-flash-preview"
MODEL_PRO = "gemini-3.1-pro-preview"

# Resilience tunables
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 1.0  # seconds; doubled each attempt → 1s, 2s, 4s
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_USER_FACING_UNAVAILABLE = (
    "Sorry, I couldn't generate a digest right now — Gemini is temporarily "
    "overloaded. Please try again in a minute."
)


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


def _is_retryable(exc: BaseException) -> bool:
    """True if the exception is a transient Gemini error worth retrying."""
    # google-genai raises ServerError (5xx) and ClientError (4xx) with .code
    code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if isinstance(code, int) and code in _RETRYABLE_STATUSES:
        return True
    # Last-resort string sniff for SDKs that don't expose .code cleanly
    msg = str(exc).upper()
    return "UNAVAILABLE" in msg or "RESOURCE_EXHAUSTED" in msg or " 503" in msg or " 429" in msg


async def _generate_with_resilience(
    *,
    contents,
    system_instruction: str,
    max_output_tokens: int,
    response_mime_type: Optional[str] = None,
    models: tuple[str, ...] = (MODEL_FLASH, MODEL_PRO),
) -> str:
    """Call Gemini with exponential backoff on transient errors and model fallback.

    Tries each model in order; for each, retries up to _RETRY_ATTEMPTS times on
    503/429/etc. with exponential backoff. Falls back to the next model only
    after exhausting retries on a transient error. Non-retryable errors abort
    the current model and move on to the fallback. Returns response.text on
    success; raises the last exception if every attempt fails.
    """
    client = get_genai_client()
    cfg_kwargs = {
        "system_instruction": system_instruction,
        "max_output_tokens": max_output_tokens,
    }
    if response_mime_type:
        cfg_kwargs["response_mime_type"] = response_mime_type
    cfg = types.GenerateContentConfig(**cfg_kwargs)

    last_exc: Optional[BaseException] = None
    for model in models:
        for attempt in range(_RETRY_ATTEMPTS):
            try:
                response = await client.aio.models.generate_content(
                    model=model,
                    contents=contents,
                    config=cfg,
                )
                return response.text or ""
            except Exception as exc:  # noqa: BLE001 — SDK raises various error types
                last_exc = exc
                if _is_retryable(exc) and attempt < _RETRY_ATTEMPTS - 1:
                    delay = _RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        f"Gemini {model} transient error (attempt {attempt+1}/"
                        f"{_RETRY_ATTEMPTS}), retrying in {delay}s: {exc}"
                    )
                    await asyncio.sleep(delay)
                    continue
                logger.warning(
                    f"Gemini {model} failed (attempt {attempt+1}): {exc}"
                )
                break  # Non-retryable or out of retries → try next model
        if len(models) > 1:
            logger.info(f"Falling back from {model} to next model")
    raise last_exc if last_exc else RuntimeError("Gemini call failed with no exception")


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
        text = await _generate_with_resilience(
            contents=prompt,
            system_instruction=CATCHUP_SYSTEM,
            max_output_tokens=2048,
        )
        return text or "No digest generated."
    except Exception as e:
        logger.error(f"Catchup generation failed after retries+fallback: {e}")
        # User-friendly: don't expose raw API JSON. Phrase kept stable so
        # existing tests that match "couldn't generate a digest" still pass.
        return _USER_FACING_UNAVAILABLE


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
    msg_lines = []
    for m in messages:
        user = m.get("username") or f"user_{m.get('tg_user_id', '?')}"
        msg_lines.append(f"[{m.get('timestamp', '')[:16]} {user}]: {m.get('text', '')}")

    prompt = f"Messages ({len(messages)} total):\n" + "\n".join(msg_lines[-200:])

    raw = ""
    try:
        raw = await _generate_with_resilience(
            contents=prompt,
            system_instruction=TOPICS_SYSTEM,
            max_output_tokens=2048,
            response_mime_type="application/json",
        )
        return json.loads(raw or "[]")
    except json.JSONDecodeError:
        logger.error(f"Topics JSON parse failed: {raw[:200]}")
        return []
    except Exception as e:
        logger.error(f"Topics generation failed after retries+fallback: {e}")
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
        text = await _generate_with_resilience(
            contents=prompt,
            system_instruction=TOPIC_DETAIL_SYSTEM,
            max_output_tokens=3072,
        )
        return text or "No detail generated."
    except Exception as e:
        logger.error(f"Topic detail generation failed after retries+fallback: {e}")
        return (
            "Sorry, I couldn't generate topic detail right now — Gemini is "
            "temporarily overloaded. Please try again in a minute."
        )


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
        text = await _generate_with_resilience(
            contents=prompt,
            system_instruction=DECIDE_SYSTEM,
            max_output_tokens=3072,
        )
        return text or "No decision view generated."
    except Exception as e:
        logger.error(f"Decision view generation failed after retries+fallback: {e}")
        return (
            "Sorry, I couldn't generate a decision view right now — Gemini is "
            "temporarily overloaded. Please try again in a minute."
        )


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
    contents = []
    for msg in conversation_history:
        role = "user" if msg["role"] == "user" else "model"
        contents.append(types.Content(
            role=role,
            parts=[types.Part(text=msg["content"])],
        ))

    try:
        text = await _generate_with_resilience(
            contents=contents,
            system_instruction=system_prompt,
            max_output_tokens=1024,
            models=(MODEL_PRO, MODEL_FLASH),  # Pro preferred for nuanced drafting
        )
        return text or "..."
    except Exception as e:
        logger.error(f"Draft generation failed after retries+fallback: {e}")
        return "Sorry, I had trouble generating a response. Please try again later."


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
    prompt = (
        f"New messages: {message_count}\n"
        f"Active topics: {', '.join(topic_names) if topic_names else 'none identified'}\n"
        f"Stale topics (>3 days): {', '.join(stale_topics) if stale_topics else 'none'}"
    )

    try:
        text = await _generate_with_resilience(
            contents=prompt,
            system_instruction=REMINDER_SYSTEM,
            max_output_tokens=512,
        )
        return text or f"📬 {message_count} new messages. Use /catchup for details."
    except Exception as e:
        logger.error(f"Reminder digest generation failed after retries+fallback: {e}")
        return f"📬 {message_count} new messages. Use /catchup for details."
