"""TinyFish Web Fetch — clean markdown extraction for URLs that fail Tavily/Playwright.

Primary use: Grok share links, X Articles (login-walled).
Fallback use: any URL where Tavily + Playwright both fail.
GitHub: use raw README fetch first, TinyFish only as fallback.

API: POST https://api.fetch.tinyfish.ai with X-API-Key header.
Free tier: 500 credits/month (~7,500 fetches).
"""

import logging

import httpx

import config

logger = logging.getLogger(__name__)

FETCH_URL = "https://api.fetch.tinyfish.ai"
MAX_CONTENT_CHARS = 10_000  # Truncate long content (e.g. 80K Grok conversations)


async def fetch_url_content(url: str, max_chars: int = MAX_CONTENT_CHARS) -> str | None:
    """Fetch URL content via TinyFish Web Fetch. Returns markdown text or None.

    Handles JS-rendered pages, login walls, and anti-bot protection.
    Truncates output to max_chars to avoid sending huge content to LLM.
    """
    if not config.TINYFISH_API_KEY:
        logger.debug("TinyFish API key not configured, skipping")
        return None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                FETCH_URL,
                headers={
                    "X-API-Key": config.TINYFISH_API_KEY,
                    "Content-Type": "application/json",
                },
                json={"urls": [url], "format": "markdown"},
            )
            data = resp.json()
            results = data.get("results", [])
            if results and results[0].get("text"):
                text = results[0]["text"]
                logger.info(f"TinyFish fetched {len(text)} chars from {url[:60]}")
                return text[:max_chars] if max_chars else text
            errors = data.get("errors", [])
            if errors:
                logger.warning(f"TinyFish errors for {url}: {errors}")
            return None
    except Exception as e:
        logger.error(f"TinyFish fetch failed for {url}: {e}")
        return None
