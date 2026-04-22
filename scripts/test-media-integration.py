"""Integration test for all media types — TinyFish, YouTube transcripts, Spotify, voice, files.

Usage: TINYFISH_API_KEY=... GEMINI_API_KEY=... uv run python scripts/test-media-integration.py
"""

import asyncio
import os
import sys

# Add project root to path so tools/ imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv

load_dotenv(override=True)

# Force config reload after dotenv to pick up env vars
import importlib
import config
importlib.reload(config)

# Test links
TEST_LINKS = {
    "grok": "https://grok.com/share/bGVnYWN5LWNvcHk_257b8a99-16a9-4722-abf4-1cf0a27e775c",
    "x_article": "https://x.com/intuitiveml/status/2043545596699750791?s=46",
    "x_regular": "https://x.com/shawmakesmagic/status/2046707773900313072?s=20",
    "github": "https://github.com/VectifyAI/OpenKB",
    "youtube_with_transcript": "https://www.youtube.com/watch?v=5MWT_doo68k",
    "pdf": "https://arxiv.org/pdf/2601.10583",
}

RESULTS = {}


def report(name: str, success: bool, detail: str = ""):
    """Record test result."""
    RESULTS[name] = {"success": success, "detail": detail}
    status = "PASS" if success else "FAIL"
    print(f"  [{status}] {name}: {detail[:120]}")


async def test_tinyfish_grok():
    """Test TinyFish extraction for Grok share links."""
    print("\n--- Phase 0: TinyFish Grok ---")
    from tools.tinyfish_fetcher import fetch_url_content

    content = await fetch_url_content(TEST_LINKS["grok"])
    if content and len(content) > 500:
        report("tinyfish_grok", True, f"{len(content)} chars extracted")
    else:
        report("tinyfish_grok", False, f"Content: {len(content) if content else 0} chars")


async def test_tinyfish_x_article():
    """Test TinyFish extraction for X Articles (login-walled). Retries once on flaky result."""
    print("\n--- Phase 0: TinyFish X Article ---")
    from tools.tinyfish_fetcher import fetch_url_content

    # TinyFish can return thin results intermittently — retry once
    for attempt in range(2):
        content = await fetch_url_content(TEST_LINKS["x_article"])
        if content and len(content) > 500:
            report("tinyfish_x_article", True, f"{len(content)} chars extracted")
            return
    report("tinyfish_x_article", False, f"Content: {len(content) if content else 0} chars (after retry)")


async def test_tinyfish_github():
    """Test TinyFish extraction for GitHub repos."""
    print("\n--- Phase 0: TinyFish GitHub ---")
    from tools.tinyfish_fetcher import fetch_url_content

    content = await fetch_url_content(TEST_LINKS["github"])
    if content and len(content) > 200:
        report("tinyfish_github", True, f"{len(content)} chars extracted")
    else:
        report("tinyfish_github", False, f"Content: {len(content) if content else 0} chars")


async def test_voice_transcription():
    """Test OGG Opus voice transcription via Gemini."""
    print("\n--- Phase 1: Voice Transcription (OGG Opus) ---")
    voice_path = os.path.join(os.path.dirname(__file__), "..", "tests", "fixtures", "test-voice.ogg")
    if not os.path.exists(voice_path):
        report("voice_ogg_opus", False, "test-voice.ogg not found")
        return

    try:
        from tools.voice_transcriber import transcribe_audio

        with open(voice_path, "rb") as f:
            audio_bytes = f.read()

        transcript = await transcribe_audio(audio_bytes, mime_type="audio/ogg")
        if transcript and len(transcript) > 10:
            report("voice_ogg_opus", True, f"Transcript: {transcript[:100]}")
        else:
            report("voice_ogg_opus", False, f"No transcript returned: {transcript}")
    except ImportError:
        report("voice_ogg_opus", False, "tools/voice_transcriber.py not yet implemented")
    except Exception as e:
        report("voice_ogg_opus", False, f"Error: {e}")


async def test_file_extraction_pdf():
    """Test PDF file extraction from bytes."""
    print("\n--- Phase 1: PDF File Extraction ---")
    try:
        from tools.file_extractor import extract_file_text
        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(TEST_LINKS["pdf"])
            pdf_bytes = resp.content

        text = extract_file_text(pdf_bytes, "paper.pdf", "application/pdf")
        if text and len(text) > 500:
            report("file_pdf", True, f"{len(text)} chars extracted from PDF")
        else:
            report("file_pdf", False, f"PDF text: {len(text) if text else 0} chars")
    except ImportError:
        report("file_pdf", False, "tools/file_extractor.py not yet implemented")
    except Exception as e:
        report("file_pdf", False, f"Error: {e}")


def test_youtube_transcript():
    """Test YouTube transcript extraction using the actual agent helpers."""
    print("\n--- Phase 2: YouTube Transcript ---")
    try:
        from agent import _extract_video_id, _get_youtube_transcript, _get_youtube_title

        video_id = _extract_video_id(TEST_LINKS["youtube_with_transcript"])
        if not video_id:
            report("youtube_transcript", False, "Could not extract video ID")
            return
        transcript = _get_youtube_transcript(video_id)
        title = _get_youtube_title(video_id)
        if transcript and len(transcript) > 100:
            report("youtube_transcript", True, f"{len(transcript)} chars, title: {title}")
        else:
            report("youtube_transcript", False, f"Transcript: {len(transcript) if transcript else 0} chars")
    except Exception as e:
        report("youtube_transcript", False, f"Error: {e}")


async def test_spotify_metadata():
    """Test Spotify metadata extraction."""
    print("\n--- Phase 3: Spotify Metadata ---")
    try:
        from tools.spotify_scraper import get_spotify_metadata

        # Test episode
        metadata = get_spotify_metadata("https://open.spotify.com/episode/4UBPQG2Z7s70DpRVD5kMbC")
        if metadata and metadata.get("title"):
            desc_len = len(metadata.get("description", ""))
            report("spotify_episode", True, f"Title: {metadata['title'][:60]}, desc: {desc_len} chars")
        else:
            report("spotify_episode", False, f"No metadata: {metadata}")

        # Test show
        metadata = get_spotify_metadata("https://open.spotify.com/show/79CkJF3UJTHFV8Dse3Oy0P")
        if metadata and metadata.get("title"):
            report("spotify_show", True, f"Title: {metadata['title'][:60]}")
        else:
            report("spotify_show", False, f"No metadata: {metadata}")
    except ImportError:
        report("spotify_episode", False, "tools/spotify_scraper.py not yet implemented")
        report("spotify_show", False, "tools/spotify_scraper.py not yet implemented")
    except Exception as e:
        report("spotify_episode", False, f"Error: {e}")


async def main():
    print("=" * 60)
    print("MURMUR BOT — Media Integration Tests")
    print("=" * 60)

    # Phase 0: TinyFish
    await test_tinyfish_grok()
    await test_tinyfish_x_article()
    await test_tinyfish_github()

    # Phase 1: Voice + Files
    await test_voice_transcription()
    await test_file_extraction_pdf()

    # Phase 2: YouTube
    test_youtube_transcript()

    # Phase 3: Spotify
    await test_spotify_metadata()

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    total = len(RESULTS)
    passed = sum(1 for r in RESULTS.values() if r["success"])
    failed = total - passed
    for name, result in RESULTS.items():
        status = "PASS" if result["success"] else "FAIL"
        print(f"  [{status}] {name}")
    print(f"\n{passed}/{total} passed, {failed} failed")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
