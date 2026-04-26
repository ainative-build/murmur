"""Generic async exponential-backoff retry helper.

Provider impls wrap this with their own model-fallback loop on top.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_ATTEMPTS = 3
DEFAULT_BASE_DELAY = 1.0  # seconds; doubles each attempt → 1s, 2s, 4s


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    is_retryable: Callable[[BaseException], bool],
    attempts: int = DEFAULT_ATTEMPTS,
    base_delay: float = DEFAULT_BASE_DELAY,
    label: str = "",
) -> T:
    """Run fn up to `attempts` times with exponential backoff on retryable errors.

    Args:
        fn: Async callable to execute.
        is_retryable: Returns True for transient errors worth retrying.
        attempts: Total number of tries (not retries).
        base_delay: Seconds before first retry; doubles each time → 1s, 2s, 4s.
        label: Logged in warnings to identify the call site.
    """
    last: BaseException | None = None
    for i in range(attempts):
        try:
            return await fn()
        except Exception as exc:  # noqa: BLE001
            last = exc
            if not is_retryable(exc) or i == attempts - 1:
                raise
            delay = base_delay * (2 ** i)
            logger.warning(
                "[%s] transient error (attempt %d/%d), retrying in %.1fs: %s",
                label or "retry",
                i + 1,
                attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
    raise last  # unreachable — loop always raises or returns
