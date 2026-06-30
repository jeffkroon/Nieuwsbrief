"""Eenvoudige in-memory rate limiter (sliding window) per sleutel/IP.

Geschikt voor 1 instance (zoals de DO basic-deploy). Bij meerdere instances
hoort hier een gedeelde store (Redis) achter; dat is nu niet nodig.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque

from starlette.requests import Request


class SlidingWindowRateLimiter:
    def __init__(self, max_hits: int, window_seconds: float) -> None:
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        """Registreer een poging; True als die binnen de limiet valt."""
        now = time.time()
        dq = self._hits[key]
        cutoff = now - self.window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if len(dq) >= self.max_hits:
            return False
        dq.append(now)
        return True

    def reset(self) -> None:
        self._hits.clear()


def client_ip(request: Request) -> str:
    """Echte client-IP, ook achter de DO-proxy (X-Forwarded-For)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"
