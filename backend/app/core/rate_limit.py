import logging
import time
from collections import defaultdict

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

# In-memory, per-process -- consistent with the OAuth state store and price-history
# cache elsewhere in this app. Fine for a single-worker deployment; a multi-worker
# or multi-instance deployment would need a shared store (e.g. Redis) instead, since
# each process would otherwise enforce its own independent limit. Old keys aren't
# proactively swept, only pruned when touched again -- an accepted, minor tradeoff
# at this app's scale, same as the other in-memory stores.
_attempts: dict[str, list[float]] = defaultdict(list)


def enforce_rate_limit(key: str, max_attempts: int, window_seconds: int) -> None:
    """
    Raises 429 if `key` has been hit more than `max_attempts` times within the
    trailing `window_seconds`; otherwise records this attempt. Every call counts
    toward the limit regardless of whether the request goes on to succeed --
    simpler to reason about than a failures-only counter, and the limits are
    generous enough that a legitimate user's occasional typo won't exhaust them.

    Callers should build `key` from the endpoint name plus whatever identifies the
    caller, e.g. "login:ip:1.2.3.4" and "login:email:a@b.com" as two independent
    checks -- one blocks one source hammering many targets, the other blocks many
    sources hammering one target.
    """
    now = time.time()
    timestamps = _attempts[key]

    cutoff = now - window_seconds
    while timestamps and timestamps[0] < cutoff:
        timestamps.pop(0)

    if len(timestamps) >= max_attempts:
        retry_after = int(timestamps[0] + window_seconds - now) + 1
        logger.warning("Rate limit exceeded for key=%s (%d attempts in %ds)", key, len(timestamps), window_seconds)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    timestamps.append(now)


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"
