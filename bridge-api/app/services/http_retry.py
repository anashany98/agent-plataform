from __future__ import annotations

import asyncio
import datetime
import random
from collections.abc import Awaitable, Callable
from email.utils import parsedate_to_datetime

import httpx

from app.config import settings

RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = str(response.headers.get("Retry-After") or "").strip()
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        try:
            retry_at = parsedate_to_datetime(raw)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=datetime.UTC)
        return max(0.0, (retry_at - datetime.datetime.now(datetime.UTC)).total_seconds())


async def request_with_retry(
    operation: Callable[[], Awaitable[httpx.Response]],
) -> httpx.Response:
    """Retry bounded transient HTTP failures and return only a final response.

    Callers remain responsible for provider-level idempotency on operations
    whose remote side effect may have happened before a response was lost.
    """

    attempts = max(1, min(int(settings.INTEGRATION_RETRY_ATTEMPTS), 8))
    base_delay = max(0.0, float(settings.INTEGRATION_RETRY_BASE_DELAY_SEC))
    max_delay = max(base_delay, float(settings.INTEGRATION_RETRY_MAX_DELAY_SEC))
    last_error: httpx.RequestError | None = None
    for attempt in range(attempts):
        try:
            response = await operation()
        except httpx.RequestError as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
            delay = min(max_delay, base_delay * (2**attempt))
        else:
            if response.status_code not in RETRYABLE_STATUS_CODES or attempt + 1 >= attempts:
                return response
            delay = _retry_after_seconds(response)
            if delay is None:
                delay = min(max_delay, base_delay * (2**attempt))
        bounded_delay = min(max_delay, max(0.0, delay))
        if bounded_delay:
            jittered_delay = bounded_delay + random.uniform(0, bounded_delay * 0.1)
            await asyncio.sleep(min(max_delay, jittered_delay))
    if last_error is not None:
        raise last_error
    raise RuntimeError("La política de retry terminó sin respuesta")
