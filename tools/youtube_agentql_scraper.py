"""
youtube_agentql_scraper.py

Scrape a YouTube video's title and full description using Playwright + AgentQL.

Prerequisites:
    pip install playwright agentql
    playwright install
    export AGENTQL_API_KEY=<your AgentQL API key>

Usage:
    python youtube_agentql_scraper.py --url "https://www.youtube.com/watch?v=DqXVfRkY-WA" [--headless]

The script will print the title and description for the given video URL.
"""

import argparse
import os
import textwrap
from dotenv import load_dotenv
import agentql
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

load_dotenv()


def scrape_youtube(url: str, headless: bool = True) -> dict[str, str]:
    """Return the video's title and full description."""

    # 0. Configure AgentQL
    agentql.configure(api_key=os.getenv("AGENTQL_API_KEY", ""))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = agentql.wrap(browser.new_page())

        # Navigate to the video URL and wait until the page is fully idle
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_page_ready_state()

        # 1. Accept cookies (EU banner)
        try:
            consent = page.query_elements(
                """
                {
                    accept_cookies_btn
                }
                """
            )
            consent.accept_cookies_btn.click(timeout=3000)
        except Exception:
            # Fallback for sites that use a different dialog text
            try:
                page.locator("button:has-text('Accept all')").click(timeout=3000)
            except PlaywrightTimeoutError:
                pass  # No consent dialog present

        # 2. Expand the description (click “Show more”)
        try:
            controls = page.query_elements(
                """
                {
                    expand_description_btn
                }
                """
            )
            controls.expand_description_btn.click(timeout=3000)
        except Exception:
            # Fallback selector if AgentQL can’t find the button
            try:
                page.locator("tp-yt-paper-button:has-text('more')").first.click(timeout=3000)
            except PlaywrightTimeoutError:
                pass

        # 3. Extract the title and the full description using AgentQL
        data = page.query_data(
            """
            {
                video_title
                description_text
            }
            """
        )

        browser.close()

        return {
            "title": data["video_title"],
            "description": textwrap.dedent(data["description_text"]).strip(),
        }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Scrape YouTube title and description via Playwright + AgentQL."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Full YouTube video URL",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (default: GUI).",
    )
    args = parser.parse_args()

    result = scrape_youtube(args.url, headless=args.headless)
    print("\n=== RESULT ===")
    print("Title:", result["title"])
    print("\nDescription:\n", result["description"])
