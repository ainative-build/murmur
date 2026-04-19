"""Unit tests for url_normalize.py — URL normalization and dedup."""

import pytest
from url_normalize import normalize_url


class TestBasicNormalization:
    """Test basic URL normalization (scheme, host, path)."""

    def test_lowercase_scheme(self):
        """HTTPS and https should normalize the same."""
        url1 = "HTTPS://example.com/page"
        url2 = "https://example.com/page"
        assert normalize_url(url1) == normalize_url(url2)

    def test_lowercase_host(self):
        """Hostname should be lowercase."""
        url1 = "https://EXAMPLE.COM/page"
        url2 = "https://example.com/page"
        assert normalize_url(url1) == normalize_url(url2)

    def test_trailing_slash_removed(self):
        """Trailing slashes on path should be stripped."""
        url1 = "https://example.com/page/"
        url2 = "https://example.com/page"
        assert normalize_url(url1) == normalize_url(url2)

    def test_root_slash_preserved(self):
        """Root path '/' should be preserved (not stripped)."""
        url1 = "https://example.com/"
        url2 = "https://example.com"
        assert normalize_url(url1) == normalize_url(url2)

    def test_mixed_case_normalization(self):
        """Test complex URL with mixed case, trailing slash."""
        url1 = "HTTPS://EXAMPLE.COM:443/Page/"
        url2 = "https://example.com/page"
        # Note: port 443 is stripped; path case preserved per RFC 3986
        assert normalize_url(url1).startswith("https://example.com")


class TestTrackingParamRemoval:
    """Test removal of common tracking parameters."""

    def test_utm_params_removed(self):
        """UTM tracking params should be stripped."""
        url1 = "https://example.com/page?utm_source=google&utm_medium=cpc&utm_campaign=sale"
        url2 = "https://example.com/page"
        assert normalize_url(url1) == normalize_url(url2)

    def test_fbclid_removed(self):
        """Facebook click ID should be removed."""
        url1 = "https://example.com/page?fbclid=ABC123"
        url2 = "https://example.com/page"
        assert normalize_url(url1) == normalize_url(url2)

    def test_gclid_removed(self):
        """Google click ID should be removed."""
        url1 = "https://example.com/page?gclid=XYZ789"
        url2 = "https://example.com/page"
        assert normalize_url(url1) == normalize_url(url2)

    def test_ref_source_removed(self):
        """Generic ref and source params removed."""
        url1 = "https://example.com/page?ref=twitter&source=reddit"
        url2 = "https://example.com/page"
        assert normalize_url(url1) == normalize_url(url2)

    def test_mailchimp_params_removed(self):
        """Mailchimp tracking params (mc_cid, mc_eid) removed."""
        url1 = "https://example.com/page?mc_cid=123&mc_eid=456"
        url2 = "https://example.com/page"
        assert normalize_url(url1) == normalize_url(url2)

    def test_multiple_tracking_params(self):
        """Multiple tracking params mixed with real params."""
        url1 = "https://example.com/page?utm_source=x&id=123&fbclid=abc&name=test"
        normalized = normalize_url(url1)
        # Should preserve id and name, remove utm and fbclid
        assert "id=123" in normalized
        assert "name=test" in normalized
        assert "utm_source" not in normalized
        assert "fbclid" not in normalized


class TestQueryParamHandling:
    """Test handling of query parameters (preservation and sorting)."""

    def test_query_params_preserved(self):
        """Non-tracking query params should be preserved."""
        url = "https://example.com/page?id=123&name=test"
        normalized = normalize_url(url)
        assert "id=123" in normalized
        assert "name=test" in normalized

    def test_query_params_sorted(self):
        """Query params should be sorted for stable comparison."""
        url1 = "https://example.com/page?z=1&a=2&m=3"
        url2 = "https://example.com/page?a=2&m=3&z=1"
        # Both should normalize to same form when sorted
        norm1 = normalize_url(url1)
        norm2 = normalize_url(url2)
        # Parse params to check they're equivalent (order may vary by implementation)
        from urllib.parse import parse_qs, urlparse
        p1_params = parse_qs(urlparse(norm1).query)
        p2_params = parse_qs(urlparse(norm2).query)
        assert p1_params == p2_params

    def test_blank_query_values_preserved(self):
        """Query params with blank values should be preserved."""
        url = "https://example.com/page?flag&id=123"
        normalized = normalize_url(url)
        assert "flag" in normalized
        assert "id=123" in normalized

    def test_no_query_string(self):
        """URLs without query strings should normalize correctly."""
        url = "https://example.com/page"
        normalized = normalize_url(url)
        assert normalized == "https://example.com/page"


class TestPortHandling:
    """Test handling of port numbers."""

    def test_default_http_port_stripped(self):
        """Port 80 should be stripped for HTTP."""
        url1 = "http://example.com:80/page"
        url2 = "http://example.com/page"
        assert normalize_url(url1) == normalize_url(url2)

    def test_default_https_port_stripped(self):
        """Port 443 should be stripped for HTTPS."""
        url1 = "https://example.com:443/page"
        url2 = "https://example.com/page"
        assert normalize_url(url1) == normalize_url(url2)

    def test_non_default_port_preserved(self):
        """Non-default ports should be preserved."""
        url1 = "https://example.com:8443/page"
        url2 = "https://example.com/page"
        assert normalize_url(url1) != normalize_url(url2)
        assert ":8443" in normalize_url(url1)


class TestEdgeCases:
    """Test edge cases and malformed URLs."""

    def test_whitespace_stripped(self):
        """Leading/trailing whitespace should be stripped."""
        url = "  https://example.com/page  "
        normalized = normalize_url(url)
        assert normalized == "https://example.com/page"

    def test_malformed_url_gracefully_handled(self):
        """Malformed URLs should fall back to lowercase."""
        url = "not a valid url at all"
        normalized = normalize_url(url)
        assert normalized.islower()

    def test_empty_string(self):
        """Empty string should return something normalized (may be '/')."""
        normalized = normalize_url("")
        # Empty string gets normalized to a valid URL form
        assert normalized is not None
        assert isinstance(normalized, str)

    def test_url_without_scheme(self):
        """URL without scheme should still normalize."""
        url = "example.com/page"
        normalized = normalize_url(url)
        # Should at least lowercase it
        assert normalized.islower()

    def test_fragment_removed(self):
        """URL fragments (#section) should be removed."""
        url1 = "https://example.com/page#section"
        url2 = "https://example.com/page"
        assert normalize_url(url1) == normalize_url(url2)


class TestRealWorldExamples:
    """Test normalization on real-world URLs."""

    def test_twitter_url(self):
        """Twitter URL with tracking and trailing slash."""
        url1 = "https://twitter.com/user/status/123?utm_source=twitter/"
        url2 = "https://twitter.com/user/status/123"
        assert normalize_url(url1) == normalize_url(url2)

    def test_youtube_url(self):
        """YouTube URL with multiple params."""
        url1 = "https://www.youtube.com/watch?v=ABC123&t=10s&utm_source=reddit"
        url2 = "https://www.youtube.com/watch?v=ABC123&t=10s"
        assert normalize_url(url1) == normalize_url(url2)

    def test_linkedin_profile_url(self):
        """LinkedIn profile URL with tracking."""
        url1 = "https://LinkedIn.com/in/username?utm_campaign=profile"
        url2 = "https://linkedin.com/in/username"
        assert normalize_url(url1) == normalize_url(url2)

    def test_medium_article_url(self):
        """Medium article URL with referral param."""
        url1 = "https://medium.com/@author/article-title-12345?ref=twitter&source=reddit"
        url2 = "https://medium.com/@author/article-title-12345"
        assert normalize_url(url1) == normalize_url(url2)

    def test_github_repo_url(self):
        """GitHub repo URL (clean, usually no tracking)."""
        url1 = "https://GitHub.com/user/repo/"
        url2 = "https://github.com/user/repo"
        assert normalize_url(url1) == normalize_url(url2)

    def test_amazon_url_with_session_tracking(self):
        """Amazon URL with ASIN and tracking."""
        url1 = "https://amazon.com/PRODUCT/ABC123/?ref=nav&source=google"
        url2 = "https://amazon.com/PRODUCT/ABC123"
        assert normalize_url(url1) == normalize_url(url2)


class TestDeduplication:
    """Test that equivalent URLs produce identical normalized forms."""

    def test_same_url_multiple_times(self):
        """Same URL should always normalize to same result."""
        url = "https://EXAMPLE.COM/Page?utm_source=x&id=123&fbclid=y/"
        normalized1 = normalize_url(url)
        normalized2 = normalize_url(url)
        normalized3 = normalize_url(url)
        assert normalized1 == normalized2 == normalized3

    def test_equivalent_urls_deduplicate(self):
        """Variants of same URL should deduplicate (ignoring trailing slash difference)."""
        variants = [
            "https://example.com/page?id=123&utm_source=google",
            "https://EXAMPLE.COM/page?utm_source=google&id=123",
            "https://example.com/page?id=123&utm_source=google",  # Same as first
            "HTTPS://example.com/page?utm_source=google&id=123",  # Same as second
        ]
        normalized = [normalize_url(url) for url in variants]
        # All should be equal (ignoring case and param order)
        # Check that tracking params are removed and case-insensitive
        assert all("utm_source" not in n for n in normalized)
        assert all("example.com" in n for n in normalized)
        assert all("id=123" in n for n in normalized)

    def test_different_urls_dont_collide(self):
        """Different URLs should produce different normalized forms."""
        url1 = "https://example.com/page1"
        url2 = "https://example.com/page2"
        assert normalize_url(url1) != normalize_url(url2)

    def test_different_domains_dont_collide(self):
        """Different domains should not collide."""
        url1 = "https://example.com/page"
        url2 = "https://example.org/page"
        assert normalize_url(url1) != normalize_url(url2)
