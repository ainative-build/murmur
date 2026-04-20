"""URL normalization for dedup — lowercase host, strip tracking params, trailing slash."""

from urllib.parse import urlparse, urlunparse, parse_qs, urlencode

# Common tracking parameters to strip
_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "source", "mc_cid", "mc_eid",
})


def normalize_url(url: str) -> str:
    """Normalize a URL for dedup comparison.

    - Lowercase scheme + host
    - Strip trailing slash from path
    - Remove common tracking query params
    - Sort remaining query params for stable comparison
    """
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return url.strip().lower()

    # Lowercase scheme and host
    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower() if parsed.hostname else ""
    port = f":{parsed.port}" if parsed.port and parsed.port not in (80, 443) else ""
    netloc = f"{host}{port}"

    # Strip trailing slash from path (but keep "/" for root)
    path = parsed.path.rstrip("/") or "/"

    # Filter out tracking params, sort remainder
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {
        k: v for k, v in query_params.items()
        if k.lower() not in _TRACKING_PARAMS
    }
    sorted_query = urlencode(filtered, doseq=True) if filtered else ""

    return urlunparse((scheme, netloc, path, "", sorted_query, ""))
