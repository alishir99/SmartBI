"""The limits, and the two properties that are easy to get subtly wrong."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from api import auth, ratelimit
from api.models import ChatRequest, ChatTurn, SaveCardRequest
from api.ratelimit import SlidingWindow
from api.routes import chat as chat_route


class FakeClock:
    """A monotonic clock the test advances by hand."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def request_from(ip: str = "198.51.100.7"):
    return SimpleNamespace(client=SimpleNamespace(host=ip))


# ------------------------------------------------------------------- the window itself

def test_the_limit_holds_and_then_releases():
    clock = FakeClock()
    window = SlidingWindow(3, 60, clock=clock)

    assert [window.hit("a") for _ in range(3)] == [None, None, None]
    assert window.hit("a") is not None

    # Sliding, not a fixed bucket: at 59 s the first hit is still inside the window.
    clock.advance(59)
    assert window.hit("a") is not None
    clock.advance(2)
    assert window.hit("a") is None


def test_the_wait_is_how_long_until_a_slot_actually_frees():
    clock = FakeClock()
    window = SlidingWindow(1, 60, clock=clock)

    window.hit("a")
    clock.advance(20)
    assert window.hit("a") == pytest.approx(40, abs=0.5)


def test_hammering_never_extends_a_lockout():
    """A refused attempt must not be counted, or a client that keeps retrying locks itself out
    forever — and, on the identifier key, so could a third party."""
    clock = FakeClock()
    window = SlidingWindow(2, 60, clock=clock)

    window.hit("a")
    window.hit("a")
    for _ in range(50):
        clock.advance(1)
        assert window.hit("a") is not None

    clock.advance(10)  # 61 s after the first of the two real attempts
    assert window.hit("a") is None


def test_keys_are_independent():
    window = SlidingWindow(1, 60, clock=FakeClock())
    assert window.hit("a") is None
    assert window.hit("b") is None


def test_zero_disables_the_limiter():
    """0 is the escape hatch. The demo must never be able to lock itself out."""
    window = SlidingWindow(0, 60, clock=FakeClock())
    assert all(window.hit("a") is None for _ in range(1000))


def test_reset_forgets_the_strikes():
    window = SlidingWindow(1, 60, clock=FakeClock())
    window.hit("a")
    window.reset("a")
    assert window.hit("a") is None


def test_exhausted_keys_are_swept_rather_than_accumulated():
    """Keys are unbounded input — any IP, any submitted e-mail — so the dict has to shrink."""
    clock = FakeClock()
    window = SlidingWindow(5, 60, clock=clock)

    for n in range(ratelimit._SWEEP_ABOVE_KEYS + 1):
        window.hit(f"key-{n}")
    clock.advance(61)
    window.hit("trigger")

    assert len(window._hits) == 1


# -------------------------------------------------------------------- the login throttle

@pytest.fixture
def login_probe(monkeypatch):
    """A login route wired to counters instead of a database and a password hash."""
    clock = FakeClock()
    monkeypatch.setattr(ratelimit, "login_by_identifier", SlidingWindow(2, 300, clock=clock))
    monkeypatch.setattr(ratelimit, "login_by_ip", SlidingWindow(4, 300, clock=clock))

    calls = {"lookup": 0, "hash": 0}

    async def fake_lookup(email: str):
        calls["lookup"] += 1
        return ({"user_id": 1, "email": email, "password_hash": "x", "role": "supplier_viewer",
                 "display_name": "Test", "supplier_id": 1, "supplier_name": "Testbolaget"}
                if email == "known@example.se" else None)

    def fake_verify(password: str, encoded: str) -> bool:
        calls["hash"] += 1
        return password == "rätt"

    monkeypatch.setattr(auth.db, "user_by_email", fake_lookup)
    monkeypatch.setattr(auth, "verify_password", fake_verify)
    return SimpleNamespace(clock=clock, calls=calls)


async def attempt(email: str, password: str = "fel", ip: str = "198.51.100.7"):
    return await auth.login(auth.LoginRequest(email=email, password=password),
                            request_from(ip))


async def status_of(email: str, **kwargs) -> tuple[int, str]:
    with pytest.raises(HTTPException) as caught:
        await attempt(email, **kwargs)
    return caught.value.status_code, str(caught.value.detail)


async def test_the_throttle_refuses_before_the_lookup_and_before_argon2(login_probe):
    """The whole point."""
    for _ in range(2):
        assert (await status_of("known@example.se"))[0] == 401

    assert (await status_of("known@example.se"))[0] == 429
    assert login_probe.calls["lookup"] == 2, "en strypt begäran slog ändå mot databasen"
    assert login_probe.calls["hash"] == 2, "en strypt begäran hashade ändå lösenordet"


async def test_a_throttled_refusal_never_reveals_whether_the_account_exists(login_probe):
    await status_of("known@example.se")
    await status_of("known@example.se")
    known = await status_of("known@example.se")

    login_probe.clock.advance(301)  # a fresh identifier window for the unknown account
    await status_of("ghost@example.se", ip="203.0.113.9")
    await status_of("ghost@example.se", ip="203.0.113.9")
    unknown = await status_of("ghost@example.se", ip="203.0.113.9")

    assert known == unknown == (429, ratelimit.LOGIN_THROTTLED)


async def test_the_identifier_key_ignores_case_and_padding(login_probe):
    """Otherwise the counter is bypassed by typing the same address differently."""
    await status_of("known@example.se")
    await status_of("  KNOWN@Example.SE  ")
    assert (await status_of("Known@example.se"))[0] == 429


async def test_the_ip_key_catches_stuffing_across_many_accounts(login_probe):
    """One password against many accounts never trips a per-identifier counter."""
    for name in ("a", "b", "c", "d"):
        assert (await status_of(f"{name}@example.se"))[0] == 401

    assert (await status_of("e@example.se"))[0] == 429


async def test_a_successful_login_forgets_the_strikes(login_probe):
    await status_of("known@example.se")
    response = await attempt("known@example.se", password="rätt")
    assert response.user.email == "known@example.se"

    # Back to a full budget: two more wrong attempts, and only the third is refused.
    assert (await status_of("known@example.se"))[0] == 401
    assert (await status_of("known@example.se"))[0] == 401
    assert (await status_of("known@example.se"))[0] == 429


async def test_the_refusal_carries_retry_after(login_probe):
    await status_of("known@example.se")
    await status_of("known@example.se")

    with pytest.raises(HTTPException) as caught:
        await attempt("known@example.se")
    assert int(caught.value.headers["Retry-After"]) > 0


# ----------------------------------------------------------------------- the chat limits

class FakeTenant:
    user_id = 7
    supplier_id = 1


async def ask():
    return await chat_route.chat(ChatRequest(question="Hur gick mars?"), FakeTenant(),
                                 mcp=None, cache=None)


@pytest.fixture
def unlimited_budget(monkeypatch):
    monkeypatch.setattr(ratelimit.settings, "tenant_token_budget", 0)


async def test_the_turn_cap_is_a_sliding_window_per_user(monkeypatch, unlimited_budget):
    clock = FakeClock()
    monkeypatch.setattr(ratelimit, "chat_turns", SlidingWindow(2, 300, clock=clock))

    await ask()
    await ask()
    with pytest.raises(HTTPException) as caught:
        await ask()
    assert caught.value.status_code == 429
    assert "Vänta" in str(caught.value.detail)

    clock.advance(301)
    await ask()


async def test_another_user_is_unaffected(monkeypatch, unlimited_budget):
    monkeypatch.setattr(ratelimit, "chat_turns", SlidingWindow(1, 300, clock=FakeClock()))

    class Other(FakeTenant):
        user_id = 8

    await ask()
    await chat_route.chat(ChatRequest(question="q"), Other(), mcp=None, cache=None)


# -------------------------------------------------------------------- the tenant budget

@pytest.fixture
def budget(monkeypatch):
    """A tenant budget of 1000 tokens over 24 h, and a recorded spend the test sets."""
    monkeypatch.setattr(ratelimit, "chat_turns", SlidingWindow(0, 300))
    monkeypatch.setattr(ratelimit.settings, "tenant_token_budget", 1000)
    monkeypatch.setattr(ratelimit.settings, "tenant_budget_window_hours", 24)

    state = SimpleNamespace(used=0, asked=[])

    async def fake_usage(supplier_id: int, window_hours: int) -> int:
        state.asked.append((supplier_id, window_hours))
        if isinstance(state.used, Exception):
            raise state.used
        return state.used

    monkeypatch.setattr(ratelimit.db, "tokens_used_since", fake_usage)
    return state


async def test_a_tenant_under_budget_is_let_through(budget):
    budget.used = 999
    await ask()
    assert budget.asked == [(1, 24)]


async def test_a_spent_budget_refuses_cleanly_in_swedish(budget):
    budget.used = 1000

    with pytest.raises(HTTPException) as caught:
        await ask()

    assert caught.value.status_code == 429
    detail = str(caught.value.detail)
    assert "AI-budget" in detail and "24 timmarna" in detail
    # The numbers are readable and Swedish-formatted, not "1,000".
    assert "1 000" in detail and "," not in detail


async def test_a_budget_of_zero_is_unlimited_and_never_even_asks(budget, monkeypatch):
    """The demo has to be able to switch this off without a database round-trip per turn."""
    monkeypatch.setattr(ratelimit.settings, "tenant_token_budget", 0)
    budget.used = 10 ** 9

    await ask()
    assert budget.asked == []


async def test_an_unset_budget_is_unlimited(budget, monkeypatch):
    monkeypatch.setattr(ratelimit.settings, "tenant_token_budget", None)
    budget.used = 10 ** 9

    await ask()
    assert budget.asked == []


async def test_the_budget_check_fails_open(budget):
    """A database hiccup must not turn into "nobody can ask anything". The audit row is written
    either way, so an unenforced turn is visible afterwards."""
    budget.used = RuntimeError("connection pool not initialised")
    await ask()


# ------------------------------------------------------------------------ request bounds

def turns(count: int, content: str = "hej") -> list[ChatTurn]:
    return [ChatTurn(role="user" if n % 2 == 0 else "assistant", content=content)
            for n in range(count)]


def test_history_is_capped_by_turn_count():
    ChatRequest(question="q", history=turns(20))
    with pytest.raises(ValueError):
        ChatRequest(question="q", history=turns(21))


def test_history_is_capped_by_total_characters():
    """Turn count alone is not a bound: one turn can carry a megabyte."""
    with pytest.raises(ValueError, match="tecken"):
        ChatRequest(question="q", history=turns(2, "x" * 20_000))


def test_a_realistic_conversation_is_well_under_both_caps():
    """The frontend sends the last 8 entries with narrative-length content."""
    ChatRequest(question="q", history=turns(8, "x" * 1200))


def test_a_saved_card_may_only_name_a_real_tool():
    chart = {"type": "bar", "title": "Topp 10"}
    for tool in ("query_sales", "query_market_share"):
        SaveCardRequest(title="t", chart=chart, tool_name=tool)

    for tool in ("get_capabilities", "drop_everything", "", "query_sales; DROP TABLE"):
        with pytest.raises(ValueError):
            SaveCardRequest(title="t", chart=chart, tool_name=tool)
