"""Tests for exponential backoff retry helper."""

import pytest
from unittest.mock import AsyncMock

from src.providers.retry import with_retry


class TestWithRetry:
    """Test exponential backoff retry logic."""

    async def test_succeeds_on_first_attempt(self, monkeypatch):
        """When fn succeeds immediately, no sleep is called."""
        sleeps = []

        async def fake_sleep(d):
            sleeps.append(d)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        async def fn():
            return "ok"

        result = await with_retry(fn, is_retryable=lambda e: True)
        assert result == "ok"
        assert sleeps == []

    async def test_retry_once_and_succeed(self, monkeypatch):
        """Retry once: first call fails, second succeeds."""
        sleeps = []

        async def fake_sleep(d):
            sleeps.append(d)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("transient")
            return "ok"

        result = await with_retry(fn, is_retryable=lambda e: True)
        assert result == "ok"
        assert sleeps == [1.0]

    async def test_exponential_backoff_timing(self, monkeypatch):
        """Backoff doubles each attempt: 1.0s, 2.0s, 4.0s."""
        sleeps = []

        async def fake_sleep(d):
            sleeps.append(d)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise RuntimeError("transient")
            return "ok"

        result = await with_retry(
            fn, is_retryable=lambda e: True, attempts=4, base_delay=1.0
        )
        assert result == "ok"
        assert sleeps == [1.0, 2.0]

    async def test_custom_base_delay(self, monkeypatch):
        """Custom base_delay is respected."""
        sleeps = []

        async def fake_sleep(d):
            sleeps.append(d)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("transient")
            return "ok"

        result = await with_retry(
            fn, is_retryable=lambda e: True, base_delay=0.5
        )
        assert result == "ok"
        assert sleeps == [0.5]

    async def test_non_retryable_error_raises_immediately(self, monkeypatch):
        """Non-retryable error is raised immediately without retry."""
        sleeps = []

        async def fake_sleep(d):
            sleeps.append(d)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        async def fn():
            raise ValueError("not retryable")

        with pytest.raises(ValueError, match="not retryable"):
            await with_retry(fn, is_retryable=lambda e: False)
        assert sleeps == []

    async def test_all_attempts_fail_raises_last_exception(self, monkeypatch):
        """When all attempts fail, the last exception is raised."""
        sleeps = []

        async def fake_sleep(d):
            sleeps.append(d)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        async def fn():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError, match="always fails"):
            await with_retry(fn, is_retryable=lambda e: True, attempts=2)
        # 2 attempts = 1 sleep before the final failure
        assert sleeps == [1.0]

    async def test_retryable_predicate_called_with_exception(self, monkeypatch):
        """is_retryable predicate is called with the raised exception."""
        sleeps = []

        async def fake_sleep(d):
            sleeps.append(d)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        exceptions_seen = []

        def is_retryable(exc):
            exceptions_seen.append(exc)
            return isinstance(exc, RuntimeError)

        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("retryable")
            elif call_count == 2:
                raise ValueError("not retryable")
            return "ok"

        with pytest.raises(ValueError, match="not retryable"):
            await with_retry(fn, is_retryable=is_retryable, attempts=3)

        assert len(exceptions_seen) == 2
        assert isinstance(exceptions_seen[0], RuntimeError)
        assert isinstance(exceptions_seen[1], ValueError)

    async def test_custom_attempts_limit(self, monkeypatch):
        """Custom attempts parameter is respected."""
        sleeps = []

        async def fake_sleep(d):
            sleeps.append(d)

        monkeypatch.setattr("asyncio.sleep", fake_sleep)

        call_count = 0

        async def fn():
            nonlocal call_count
            call_count += 1
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError):
            await with_retry(fn, is_retryable=lambda e: True, attempts=2)
        # 2 attempts = 1 sleep before exhaustion
        assert len(sleeps) == 1
