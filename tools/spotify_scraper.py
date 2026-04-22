"""Spotify metadata extraction via Web API (client credentials) with oEmbed fallback.

Focused on podcast episodes — returns episode description, show name, duration.
For tracks/albums, falls back to oEmbed (title only).

Requires: SPOTIFY_CLIENT_ID + SPOTIFY_CLIENT_SECRET env vars for rich metadata.
Without credentials: oEmbed fallback gives title only.

Attribution: Spotify policy requires linking back to source. Never cache/download audio.
"""

import base64
import logging
import re
import time

import requests

import config

logger = logging.getLogger(__name__)

SPOTIFY_URL_PATTERN = r'open\.spotify\.com/(track|album|episode|show|playlist)/([a-zA-Z0-9]+)'

# Token cache — client credentials tokens last 1 hour
_token_cache: dict = {"token": None, "expires_at": 0}


def _get_access_token() -> str | None:
    """Get Spotify access token via client credentials flow. Cached ~1 hour."""
    if not config.SPOTIFY_CLIENT_ID or not config.SPOTIFY_CLIENT_SECRET:
        return None
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]
    try:
        creds = base64.b64encode(
            f"{config.SPOTIFY_CLIENT_ID}:{config.SPOTIFY_CLIENT_SECRET}".encode()
        ).decode()
        resp = requests.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {creds}"},
            data={"grant_type": "client_credentials"},
            timeout=5,
        )
        if resp.status_code != 200:
            logger.error(f"Spotify auth failed: {resp.status_code} {resp.text[:200]}")
            return None
        data = resp.json()
        _token_cache["token"] = data["access_token"]
        _token_cache["expires_at"] = now + data.get("expires_in", 3600)
        return _token_cache["token"]
    except Exception as e:
        logger.error(f"Spotify auth failed: {e}")
        return None


def _parse_spotify_url(url: str) -> tuple[str | None, str | None]:
    """Parse Spotify URL. Returns (content_type, spotify_id) or (None, None)."""
    match = re.search(SPOTIFY_URL_PATTERN, url)
    if match:
        return match.group(1), match.group(2)
    return None, None


def _fetch_episode(spotify_id: str, token: str) -> dict | None:
    """Fetch podcast episode metadata from Spotify Web API."""
    try:
        resp = requests.get(
            f"https://api.spotify.com/v1/episodes/{spotify_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if resp.status_code != 200:
            logger.warning(f"Spotify episode API {resp.status_code}: {resp.text[:100]}")
            return None
        data = resp.json()
        return {
            "title": data.get("name", ""),
            "type": "episode",
            "description": (data.get("description", "") or "")[:2000],
            "show_name": data.get("show", {}).get("name", ""),
            "duration_ms": data.get("duration_ms"),
        }
    except Exception as e:
        logger.error(f"Spotify episode fetch failed: {e}")
        return None


def _fetch_show(spotify_id: str, token: str) -> dict | None:
    """Fetch podcast show metadata from Spotify Web API."""
    try:
        resp = requests.get(
            f"https://api.spotify.com/v1/shows/{spotify_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=5,
        )
        if resp.status_code != 200:
            logger.warning(f"Spotify show API {resp.status_code}: {resp.text[:100]}")
            return None
        data = resp.json()
        return {
            "title": data.get("name", ""),
            "type": "show",
            "description": (data.get("description", "") or "")[:2000],
            "total_episodes": data.get("total_episodes"),
        }
    except Exception as e:
        logger.error(f"Spotify show fetch failed: {e}")
        return None


def _get_oembed_fallback(url: str, content_type: str | None) -> dict | None:
    """Fallback to oEmbed for title-only metadata (no auth required)."""
    try:
        resp = requests.get(
            f"https://open.spotify.com/oembed?url={url}",
            timeout=5,
        )
        if resp.status_code == 200:
            data = resp.json()
            return {
                "title": data.get("title", ""),
                "type": content_type or "unknown",
                "description": "",
            }
    except Exception:
        pass
    return None


def get_spotify_metadata(url: str) -> dict | None:
    """Fetch Spotify metadata. Web API for episodes/shows, oEmbed fallback for rest.

    Returns dict with keys: title, type, description, show_name (optional), duration_ms (optional).
    Returns None if all extraction methods fail.
    """
    content_type, spotify_id = _parse_spotify_url(url)
    if not content_type or not spotify_id:
        return None

    # Try Web API first (requires credentials)
    token = _get_access_token()
    if token:
        if content_type == "episode":
            result = _fetch_episode(spotify_id, token)
            if result:
                return result
        elif content_type == "show":
            result = _fetch_show(spotify_id, token)
            if result:
                return result

    # Fallback to oEmbed for everything else or when API fails
    return _get_oembed_fallback(url, content_type)
