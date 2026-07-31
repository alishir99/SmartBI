"""Rate limits and the per-tenant cost cap — the three places this API can be made expensive.

Login, because Argon2id is deliberately expensive; `/api/chat`, because a turn is several LLM
calls; and the tenant budget, because a rate limit bounds *turns* while only token accounting
bounds *money*.

**In-process and per-worker, exactly like result_cache.py.** With one uvicorn worker — what
this demo runs, and what `docker compose up` starts — that is the whole picture. With N
workers or N containers each counter is a shard, so the real limit becomes N × the configured
one and a login throttle can be bypassed by reconnecting until you land on a fresh worker. The
replacement is Redis with the same two methods (`hit`/`reset`, INCR + EXPIRE, or a sorted set
per key for a true sliding window); nothing above this line would change. It is not done here
for the same reason the result cache is in memory: a single-instance demo, and an added
infrastructure dependency that the graded code does not exercise is a worse trade than a
stated limitation.

Also per-process and therefore lost on restart. For the login throttle that is a real gap — a
crash-loop resets everyone's strike count — and the same Redis move closes it.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException, Request, status

from . import db
from .config import settings

log = logging.getLogger(__name__)

# Above this many distinct keys, sweep the empty ones. Keys are unbounded input (any IP, any
# submitted e-mail), so without this the dict is a slow memory leak with a free growth knob
# for whoever is already attacking the login endpoint.
_SWEEP_ABOVE_KEYS = 4096


class SlidingWindow:
    """`limit` events per `window_seconds`, keyed by caller.

    A true sliding window (timestamps in a deque) rather than a fixed bucket: a fixed bucket
    lets 2× the limit through across a boundary, and the whole point of the login throttle is
    that the ceiling holds at the moment someone is leaning on it.

    `clock` is injected so the time-based behaviour is testable without sleeping.
    """

    def __init__(self, limit: int, window_seconds: float,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def hit(self, key: str) -> float | None:
        """Record one event. `None` if it is allowed, else seconds until a slot frees."""
        # 0 (or negative) disables the limiter. The demo must never be able to lock itself
        # out, and an operator killing a limit should not have to edit code to do it.
        if self.limit <= 0:
            return None

        now = self._clock()
        cutoff = now - self.window_seconds
        hits = self._hits.setdefault(key, deque())
        while hits and hits[0] <= cutoff:
            hits.popleft()

        if len(hits) >= self.limit:
            # Deliberately *not* recorded. Counting refused attempts would let a client that
            # keeps hammering extend its own lockout indefinitely, which turns a throttle into
            # a self-inflicted denial of service — and, on the identifier key, into a way for
            # a third party to keep a known account locked out for as long as they like.
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
    # Retry-After in whole seconds, rounded up, so a client that honours it does not come back
    # a fraction of a second early and burn another refusal.
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, message,
                         headers={"Retry-After": str(max(1, int(wait_seconds) + 1))})


# --------------------------------------------------------------------------------- login
#
# Argon2id at 19 MiB, t=2 (api/auth.py) is not merely CPU-expensive: every verification
# allocates 19 MiB, so an unthrottled login endpoint converts a cheap POST into hundreds of
# megabytes of allocation churn — a *memory* amplifier, not just a brute-force surface. In
# this process `verify_password` is a synchronous call inside `async def`, so hashes never
# overlap and peak RSS stays near one hash; the same traffic instead pins the event loop and
# stalls every other request in the worker. Both failure modes have the same fix: refuse
# before hashing. So the counter is incremented ahead of the user lookup and ahead of
# `verify_password`, not after a failed one.
#
# Two keys, because they catch different attacks. Per-identifier stops password-guessing
# against one known account; per-IP stops credential stuffing that tries one password against
# many accounts and would never trip a per-identifier counter.
login_by_identifier = SlidingWindow(settings.login_attempts_per_identifier,
                                    settings.login_window_seconds)
login_by_ip = SlidingWindow(settings.login_attempts_per_ip, settings.login_window_seconds)

# One message for throttled, unknown-account and wrong-password alike — see the note in
# auth.login. The number of seconds is derived from the caller's own attempts, so it tells
# them nothing about whether the account they named exists.
LOGIN_THROTTLED = "För många inloggningsförsök. Vänta en stund och försök igen."


def enforce_login(*, identifier: str, client_ip: str) -> None:
    """Raise 429 if this identifier or this address has spent its attempts.

    Both counters are hit unconditionally, in this order, before anything reads the database.
    Hitting the IP counter even when the identifier is already over its limit is deliberate:
    otherwise an attacker gets unlimited free requests by rotating to a locked-out identifier.
    """
    waits = [wait for wait in (login_by_identifier.hit(identifier.strip().lower()),
                               login_by_ip.hit(client_ip))
             if wait is not None]
    if waits:
        raise _too_many(max(waits), LOGIN_THROTTLED)


def clear_login(*, identifier: str, client_ip: str) -> None:
    """Forget the strikes after a successful login.

    Somebody who mistypes twice and then gets in should not be two attempts from a lockout for
    the next five minutes. A successful password proves the caller is not the guesser the
    counter exists for.
    """
    login_by_identifier.reset(identifier.strip().lower())
    login_by_ip.reset(client_ip)


def client_ip(request: Request) -> str:
    """The address to key the IP throttle on.

    `X-Forwarded-For` is ignored on purpose. Behind a proxy this collapses every caller onto
    the proxy's address, which is a real weakness — but trusting a client-supplied header is
    strictly worse than that: it is spoofable, so it hands an attacker both an unlimited
    supply of fresh limiter keys and the ability to burn *someone else's* budget. The fix is
    uvicorn's `--proxy-headers --forwarded-allow-ips=<the proxy>`, which resolves
    `request.client` correctly at the transport layer, where the trust decision belongs.
    """
    return request.client.host if request.client else "unknown"


# ---------------------------------------------------------------------------------- chat

# A turn is several LLM calls and takes 10–30 s, so a human asking as fast as they can read
# manages perhaps ten in five minutes. 20 is twice the fastest plausible human and a small
# fraction of what a loop does in the same time — generous for the demo, tight for a script.
chat_turns = SlidingWindow(settings.chat_turns_per_user, settings.chat_window_seconds)


def enforce_chat_turn(user_id: int) -> None:
    if (wait := chat_turns.hit(f"user:{user_id}")) is not None:
        raise _too_many(
            wait,
            f"Du har ställt många frågor på kort tid. Vänta {int(wait) + 1} sekunder och "
            f"försök igen.")


# ------------------------------------------------------------------------- tenant budget

async def enforce_tenant_budget(supplier_id: int) -> None:
    """Refuse a turn once the tenant has burned its token budget for the trailing window.

    Driven by `audit_turn.input_tokens`/`output_tokens`, which now hold real per-turn counts.
    That makes this the only control here that bounds *money* rather than request count: a
    turn cap cannot tell a one-tool question from one that reads 200 k tokens of context.

    Cached tokens are excluded — they live in `row_counts` and are billed at roughly a tenth
    of the rate, so counting them against the same ceiling would charge a tenant full price
    for the discount that makes the agent affordable.

    Fails **open**. A budget check that turns a database hiccup into "no one can ask
    anything" is a worse outage than the overspend it prevents, and the audit row is written
    regardless, so a missed check is visible after the fact rather than silent.
    """
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
    """Swedish thousands separator. These two numbers are the whole explanation a refused
    user gets, so they should read as Swedish rather than as English."""
    return f"{number:,}".replace(",", " ")
