"""Playwright fallback extractor for JS-rendered pages (Grok, SPAs, etc.).

Used when Tavily fails to extract content. Renders the page in headless
Chromium and extracts visible text.
"""

import logging
from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)


def extract_page_text(url: str, timeout_ms: int = 30000) -> str | None:
    """Render a URL in headless Chromium and extract visible text content.

    Returns extracted text or None on failure.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright not installed — fallback extraction unavailable")
        return None

    console.print(f"Playwright fallback: rendering {url}", style="cyan")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            # Use domcontentloaded — networkidle never fires on heavy SPAs (Grok, etc.)
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

            # Wait for JS rendering to settle
            page.wait_for_timeout(5000)

            # Extract main content — try common content selectors first
            text = None
            for selector in ["main", "article", "[role='main']", ".content", "#content"]:
                try:
                    el = page.query_selector(selector)
                    if el:
                        text = el.inner_text()
                        if text and len(text) > 100:
                            break
                except Exception:
                    continue

            # Fallback: get all body text
            if not text or len(text) < 100:
                text = page.inner_text("body")

            browser.close()

            if text and len(text.strip()) > 50:
                trimmed = text.strip()[:15000]

                # Detect bot-check / security interstitial pages
                bot_check_signals = [
                    "verify you are human",
                    "security check",
                    "checking your browser",
                    "just a moment",
                    "enable javascript",
                    "cloudflare",
                    "confirm you are not a bot",
                    "verifying",
                ]
                lower = trimmed.lower()
                if any(s in lower for s in bot_check_signals) and len(trimmed) < 500:
                    console.print("Playwright: detected bot-check page, skipping", style="yellow")
                    return None

                console.print(f"Playwright extracted {len(trimmed)} chars", style="green")
                return trimmed
            else:
                console.print("Playwright: page had no meaningful text", style="yellow")
                return None

    except Exception as e:
        console.print(f"Playwright fallback failed: {e}", style="red")
        logger.error(f"Playwright fallback failed for {url}: {e}")
        return None
