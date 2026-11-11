"""HTTP fetching with retries, exponential backoff, and rate-limit handling."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

import httpx

from src.core.logging import get_logger

log = get_logger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    """Raised when a resource cannot be fetched after all retries."""


def backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
    """Exponential backoff: base, 2*base, 4*base, ... capped."""
    return float(min(cap, base * (2**attempt)))


def retry_after_seconds(response: httpx.Response) -> float | None:
    """Read a numeric `Retry-After` header. HTTP-date values are ignored."""
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


async def fetch_bytes(
    url: str,
    *,
    client: httpx.AsyncClient,
    max_retries: int = 4,
    backoff_base: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> bytes:
    """GET a URL, retrying transient failures. Non-retryable errors fail immediately.

    The request honours the server's rate limiting (`Retry-After`) and never attempts to
    work around an access restriction: 401, 403, and 404 are final.
    """
    last_error = "no attempt made"
    for attempt in range(max_retries + 1):
        try:
            response = await client.get(url)
        except httpx.TransportError as exc:
            last_error = f"transport error: {exc!r}"
            delay = backoff_delay(attempt, backoff_base)
        else:
            if response.status_code < 400:
                return response.content
            last_error = f"HTTP {response.status_code}"
            if response.status_code not in RETRYABLE_STATUS:
                raise FetchError(f"{url}: {last_error} (not retryable)")
            delay = retry_after_seconds(response) or backoff_delay(attempt, backoff_base)
        if attempt < max_retries:
            log.warning(
                "fetch failed, retrying",
                extra={"url": url, "attempt": attempt + 1, "error": last_error, "delay": delay},
            )
            await sleep(delay)
    raise FetchError(f"{url}: {last_error} after {max_retries + 1} attempts")
