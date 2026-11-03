"""Cryptographically secure, single-use ticket management for SSE subscriptions.

Prevents long-lived bearer tokens from appearing in URL query parameters, access logs,
browser history, and proxy logs.
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Any


class SSETicketStore:
    """Thread-safe store for single-use, short-lived SSE connection tickets."""

    DEFAULT_TTL_SECONDS = 60

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._tickets: dict[str, dict[str, Any]] = {}

    def create_ticket(self, user_id: int, project_id: int) -> str:
        """Create a single-use random ticket bound to user_id and project_id."""
        ticket = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            # Lazy cleanup of expired tickets
            cutoff = now - self._ttl
            expired = [t for t, data in self._tickets.items() if data["created_at"] < cutoff]
            for t in expired:
                del self._tickets[t]

            self._tickets[ticket] = {
                "user_id": user_id,
                "project_id": project_id,
                "created_at": now,
                "expires_at": now + self._ttl,
            }
        return ticket

    def validate_and_consume(self, ticket: str, expected_project_id: int) -> dict[str, Any] | None:
        """Validate the ticket against project and expiration, consuming it immediately.
        
        Returns the ticket payload on success, or None if invalid, expired, or replayed.
        """
        now = time.time()
        with self._lock:
            data = self._tickets.pop(ticket, None)
            if not data:
                # Ticket does not exist or has already been consumed (replay prevented)
                return None
            if now > data["expires_at"]:
                # Ticket has expired
                return None
            if data["project_id"] != expected_project_id:
                # Cross-project ticket usage rejected
                return None
            return data

    def reset_all(self) -> None:
        """Reset ticket store state (useful for tests)."""
        with self._lock:
            self._tickets.clear()


sse_ticket_store = SSETicketStore()

