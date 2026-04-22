"""TinyFish Web Fetch spike — test link extraction for unsupported URLs.

Usage: uv run python scripts/tinyfish-spike.py
"""
import asyncio
import os
import httpx
from dotenv import load_dotenv

load_dotenv()

TINYFISH_API_KEY = os.getenv("TINYFISH_API_KEY", "")
FETCH_URL = "https://api.fetch.tinyfish.ai"

TEST_LINKS = {
    "grok_share": "https://grok.com/share/bGVnYWN5LWNvcHk_257b8a99-16a9-4722-abf4-1cf0a27e775c",
    "x_article": "https://x.com/intuitiveml/status/2043545596699750791?s=46",
    "x_regular": "https://x.com/shawmakesmagic/status/2046707773900313072?s=20",
    "github": "https://github.com/VectifyAI/OpenKB",
}


async def fetch_with_tinyfish(url: str, label: str) -> dict:
    """Fetch a URL via TinyFish and return results."""
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.post(
                FETCH_URL,
                headers={
                    "X-API-Key": TINYFISH_API_KEY,
                    "Content-Type": "application/json",
                },
                json={"urls": [url], "format": "markdown"},
            )
            data = resp.json()
            # TinyFish returns {results: [{url, title, text}], errors: []}
            content = ""
            if isinstance(data, dict):
                results = data.get("results", [])
                if results and isinstance(results, list) and len(results) > 0:
                    content = results[0].get("text", "") or results[0].get("content", "") or results[0].get("markdown", "")
                errors = data.get("errors", [])
                if errors:
                    content = content or f"ERRORS: {errors}"
            raw_errors = data.get("errors", []) if isinstance(data, dict) else []
            return {
                "label": label,
                "url": url,
                "status": resp.status_code,
                "content_length": len(content),
                "content_preview": content[:1000] if content else "",
                "success": bool(content and len(content) > 100),
                "raw_keys": list(data.keys()) if isinstance(data, dict) else str(type(data)),
                "raw_errors": raw_errors,
            }
        except Exception as e:
            return {"label": label, "url": url, "error": str(e), "success": False}


async def main():
    if not TINYFISH_API_KEY:
        print("ERROR: Set TINYFISH_API_KEY in .env")
        return

    print(f"Testing {len(TEST_LINKS)} URLs with TinyFish Web Fetch...\n")
    print(f"API Key: {TINYFISH_API_KEY[:15]}...{TINYFISH_API_KEY[-4:]}")
    print(f"Endpoint: {FETCH_URL}\n")

    for label, url in TEST_LINKS.items():
        print(f"--- {label} ---")
        result = await fetch_with_tinyfish(url, label)
        status = "OK" if result.get("success") else "FAIL"
        print(f"[{status}] {label}")
        print(f"  URL: {url}")
        print(f"  HTTP Status: {result.get('status', 'N/A')}")
        print(f"  Response keys: {result.get('raw_keys', 'N/A')}")
        print(f"  Content length: {result.get('content_length', 0)} chars")
        if result.get("raw_errors"):
            print(f"  API Errors: {result['raw_errors']}")
        if result.get("content_preview"):
            print(f"  Preview:\n{result['content_preview'][:500]}")
        if result.get("error"):
            print(f"  Error: {result['error']}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
