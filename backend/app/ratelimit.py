"""Small in-process sliding-window rate limiter for the endpoints attackers like: login, sign-up, OTP.

It is per API process. Behind several workers each has its own counters (a shared store such as Redis would be the
next step); for a single container it does the job. Turn it off with RATE_LIMIT_ENABLED=false."""
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from .config import settings

_hits: dict[str, deque] = defaultdict(deque)
_lock = threading.Lock()
_PRUNE_AT = 5000


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def check(key: str, limit: int, window_seconds: int) -> None:
    """Record one use of `key`; raise 429 if it has been used `limit` times in the last `window_seconds`."""
    if not settings.rate_limit_enabled:
        return
    now = time.monotonic()
    with _lock:
        q = _hits[key]
        while q and q[0] <= now - window_seconds:
            q.popleft()
        if len(q) >= limit:
            retry = max(1, int(q[0] + window_seconds - now) + 1)
            raise HTTPException(
                429, f"Too many attempts. Please try again in {retry} second{'s' if retry != 1 else ''}.",
                headers={"Retry-After": str(retry)},
            )
        q.append(now)
        if len(_hits) > _PRUNE_AT:  # keep memory bounded
            for k in [k for k, v in _hits.items() if not v or v[-1] <= now - 3600]:
                del _hits[k]


def reset() -> None:
    with _lock:
        _hits.clear()
