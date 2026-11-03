"""Thread-safe in-memory rate limiter for authentication and API protection."""
from __future__ import annotations

import threading
import time
from collections import defaultdict
from fastapi import Request


class SlidingWindowRateLimiter:
    """Sliding-window in-memory rate limiter with thread safety and auto-eviction."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._attempts: dict[str, list[float]] = defaultdict(list)

    def check_rate_limit(
        self,
        key: str,
        max_requests: int,
        window_seconds: int = 60,
    ) -> tuple[bool, int]:
        """Check whether the key is within the rate limit.

        Returns (allowed: bool, retry_after_seconds: int).
        """
        now = time.time()
        cutoff = now - window_seconds
        with self._lock:
            # Evict timestamps outside the sliding window
            timestamps = [ts for ts in self._attempts[key] if ts > cutoff]
            self._attempts[key] = timestamps

            if len(timestamps) >= max_requests:
                oldest = timestamps[0]
                retry_after = max(1, int(window_seconds - (now - oldest)) + 1)
                return False, retry_after
            return True, 0

    def record_attempt(self, key: str) -> None:
        """Record an attempt timestamp for the specified key."""
        now = time.time()
        with self._lock:
            self._attempts[key].append(now)

    def clear_attempts(self, key: str) -> None:
        """Clear all recorded attempts for the specified key (e.g. on successful authentication)."""
        with self._lock:
            self._attempts.pop(key, None)

    def reset_all(self) -> None:
        """Reset all rate limiter state (useful in testing)."""
        with self._lock:
            self._attempts.clear()


auth_rate_limiter = SlidingWindowRateLimiter()


def get_client_ip(request: Request) -> str:
    """Extract client IP address safely from forwarded headers or connection."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        # Take the leftmost untrusted client IP
        ip = forwarded.split(",")[0].strip()
        if ip:
            return ip
    if request.client and request.client.host:
        return request.client.host
    return "127.0.0.1"

