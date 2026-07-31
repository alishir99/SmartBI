"""What the chat stream does with the usage event."""

from __future__ import annotations

import pytest

from api.models import (
    AnswerCard,
    CardEvent,
    ChatRequest,
    StatusEvent,
    ToolCallEvent,
    UsageEvent,
)
from api.routes import chat as chat_route


class FakeTenant:
    user_id = 7
    supplier_id = 1


def card() -> AnswerCard:
    return AnswerCard(title="Mars", status="ok", narrative="Allt väl.", query_id="q_1")


async def fake_turn(**_kwargs):
    yield StatusEvent(message="Tänker…")
    yield ToolCallEvent(tool="query_sales", args={})
    yield CardEvent(card=card())
    yield UsageEvent(input_tokens=2300, output_tokens=350, cache_read_tokens=1900,
                     cache_write_tokens=1900, llm_calls=2)


@pytest.mark.asyncio
async def test_usage_is_recorded_but_never_streamed(monkeypatch):
    recorded: dict = {}

    async def fake_record(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(chat_route, "run_turn", fake_turn)
    monkeypatch.setattr(chat_route.db, "record_turn", fake_record)

    frames = [frame async for frame in chat_route._stream(
        ChatRequest(question="Hur gick mars?"), FakeTenant(), mcp=None, cache=None)]

    wire = "".join(frames)
    assert '"type":"usage"' not in wire.replace(" ", "")
    assert '"type":"card"' in wire.replace(" ", "")

    assert recorded["input_tokens"] == 2300
    assert recorded["output_tokens"] == 350
    assert recorded["row_counts"]["cache_read_tokens"] == 1900
    assert recorded["row_counts"]["llm_calls"] == 2
    assert recorded["status"] == "ok"


@pytest.mark.asyncio
async def test_tokens_stay_null_when_the_loop_reports_nothing(monkeypatch):
    """Null rather than zero: a zero reads as "this turn was free" in any cost rollup, which is a
    worse lie than an honest gap."""
    recorded: dict = {}

    async def no_usage(**_kwargs):
        yield CardEvent(card=card())

    async def fake_record(**kwargs):
        recorded.update(kwargs)

    monkeypatch.setattr(chat_route, "run_turn", no_usage)
    monkeypatch.setattr(chat_route.db, "record_turn", fake_record)

    async for _ in chat_route._stream(ChatRequest(question="q"), FakeTenant(),
                                      mcp=None, cache=None):
        pass

    assert recorded["input_tokens"] is None
    assert recorded["output_tokens"] is None
