"""Rate limits and the per-tenant cost cap — the three places this API can be made expensive."""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

from . import db
from .config import settings

log = logging.getLogger(__name__)

# Above this many distinct keys, sweep the empty ones.
_SWEEP_ABOVE_KEYS = 4096


class SlidingWindow:
    """`limit` events per `window_seconds`, keyed by caller."""

    def __init__(self, limit: int, window_seconds: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> float | None:
        """Record one event. `None` if it is allowed, else seconds until a slot frees."""
        # 0 (or negative) disables the limiter.
        if self.limit <= 0:
            return None

        now = self._clock()
        cutoff = now - self.window_seconds
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.limit:
            # Deliberately *not* recorded.
            return max(0.0, hits[0] - cutoff)

        hits.append(now)
        if len(self._hits) > _SWEEP_ABOVE_KEYS:
            self._sweep(cutoff)
        return None

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def _sweep(self, cutoff: float) -> None:
        for key, hits in list(self._hits.items()):
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if not hits:
                del self._hits[key]


def _too_many(wait_seconds: float, message: str) -> HTTPException:
    # Retry-After in whole seconds, rounded up, so a client that honours it does not come back a
    # fraction of a second early and burn another refusal.
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message,
                         headers={"Retry-After": str(max(1, int(wait_seconds) + 1))})


# --------------------------------------------------------------------------------- login
# Argon2id at 19 MiB, t=2 (api/auth.py) is not merely CPU-expensive: every verification
# allocates 19 MiB, so an unthrottled login endpoint converts a cheap POST into hundreds of
# megabytes of allocation churn — a *memory* amplifier, not just a brute-force surface.
login_by_identifier = SlidingWindow(settings.login_attempts_per_identifier,
                                    settings.login_window_seconds)
login_by_ip = SlidingWindow(settings.login_attempts_per_ip, settings.login_window_seconds)

# One message for throttled, unknown-account and wrong-password alike — see the note in
# auth.login.
LOGIN_THROTTLED = "För många inloggningsförsök. Vänta en stund och försök igen."


def enforce_login(*, identifier: str, client_ip: str) -> None:
    """Raise 429 if this identifier or this address has spent its attempts."""
    waits = [wait for wait in (login_by_identifier.hit(identifier.strip().lower()),
                               login_by_ip.hit(client_ip))
             if wait is not None]
    if waits:
        raise _too_many(max(waits), LOGIN_THROTTLED)


def clear_login(*, identifier: str, client_ip: str) -> None:
    """Forget the strikes after a successful login."""
    login_by_identifier.reset(identifier.strip().lower())
    login_by_ip.reset(client_ip)


def client_ip(request: Request) -> str:
    """The address to key the IP throttle on."""
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------------- chat

# A turn is several LLM calls and takes 10–30 s, so a human asking as fast as they can read
# manages perhaps ten in five minutes.
chat_turns = SlidingWindow(settings.chat_turns_per_user, settings.chat_window_seconds)


def enforce_chat_turn(user_id: int) -> None:
    if (wait := chat_turns.hit(f"user:{user_id}")) is not None:
        raise _too_many(
            wait,
            f"Du har ställt många frågor på kort tid. Vänta {int(wait) + 1} sekunder och "
            f"försök igen.")


# ------------------------------------------------------------------------- tenant budget

async def enforce_tenant_budget(supplier_id: int) -> None:
    """Refuse a turn once the tenant has burned its token budget for the trailing window."""
    budget = settings.tenant_token_budget
    if not budget or budget <= 0:  # None or 0 = unlimited, so the demo cannot lock itself out
        return

    window_hours = settings.tenant_budget_window_hours
    try:
        used = await db.tokens_used_since(supplier_id, window_hours)
    except Exception:  # noqa: BLE001 — see docstring
        log.warning("could not read the token budget for supplier %s", supplier_id,
                    exc_info=True)
        return

    if used >= budget:
        # A clean 429 with a Swedish message, not a 500 — the frontend surfaces `detail`
        # verbatim, so this is what the user reads.
        raise _too_many(
            60,
            f"Kontots AI-budget för de senaste {window_hours} timmarna är förbrukad "
            f"({_spaced(used)} av {_spaced(budget)} tokens). Nya frågor går att ställa igen "
            f"när fönstret rullar vidare.")


def _spaced(number: int) -> str:
    """Swedish thousands separator."""
    return f"{number:,}".replace(",", " ")
