"""Tests for the agent turn's validation gate (§9.2).

The validator is the second line of the grounding defence, and what these tests pin is *when*
it runs. It used to be gated on `status == "ok"`, a field the model writes itself in its own
JSON envelope — which made the whole numeric guarantee opt-out from inside the generated text.
`clarify` is precisely the status a model reaches for when it is unsure what was asked, i.e.
when its prose is most likely to be improvised, so that gate leaked exactly the wrong answers.

Driving the loop needs a stand-in for the LLM and for MCP. Both are small: the loop only ever
calls `messages.create`, and the MCP surface it touches is three methods.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from api.agent import loop as agent_loop
from api.models import CardEvent
from api.result_cache import ResultCache

MARS = 3_450_900.50

PAYLOAD = {
    "rows": [{"month": "2026-01-01", "net_sales_sek": 3_120_450.25},
             {"month": "2026-02-01", "net_sales_sek": 2_890_100.00},
             {"month": "2026-03-01", "net_sales_sek": MARS}],
    "row_count": 3,
    "columns": [{"key": "month", "type": "date", "label": "Månad"},
                {"key": "net_sales_sek", "type": "number", "label": "Netto", "unit": "SEK"}],
    "meta": {"tool": "query_sales", "source": "mv_sales_daily (rollup)",
             "scope": "supplier:demo", "currency": "SEK", "vat": "exkl. moms",
             "time_range": {"from": "2026-01-01", "to": "2026-03-31"},
             "executed_at": "2026-07-29T10:00:00Z"},
}


# ------------------------------------------------------------------------------ fakes

class Block:
    """Stands in for an Anthropic content block; the loop only reads `.type` and friends."""

    def __init__(self, **fields):
        self.__dict__.update(fields)


class Response:
    def __init__(self, text: str = "", uses: list | None = None):
        self.content = list(uses or [])
        if text:
            self.content.append(Block(type="text", text=text))
        self.stop_reason = "tool_use" if uses else "end_turn"


class FakeMessages:
    def __init__(self, script: list[Response]):
        self.script = list(script)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        if not self.script:
            raise AssertionError("the loop asked the model for more turns than were scripted")
        return self.script.pop(0)


class FakeClient:
    def __init__(self, script):
        self.messages = FakeMessages(script)


class FakeMcp:
    """Answers every query_sales call with PAYLOAD; records what was asked."""

    def __init__(self):
        self.calls: list[tuple[str, dict]] = []

    @asynccontextmanager
    async def session(self, supplier_id: int):
        yield object()

    async def anthropic_tools(self, supplier_id: int):
        return [{"name": "query_sales", "description": "", "input_schema": {"type": "object"}}]

    async def call_on(self, session, tool: str, args: dict):
        self.calls.append((tool, args))
        return PAYLOAD


def envelope(status: str, query_id: str | None = None) -> str:
    ident = f', "query_id": "{query_id}"' if query_id else ""
    return f'```json\n{{"status": "{status}"{ident}}}\n```'


async def run(monkeypatch, script) -> object:
    client = FakeClient(script)
    monkeypatch.setattr(agent_loop.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(agent_loop, "_client", lambda: client)
    mcp = FakeMcp()
    card = None
    async for event in agent_loop.run_turn(question="Hur gick mars?", history=[],
                                           supplier_id=1, mcp=mcp, cache=ResultCache()):
        if isinstance(event, CardEvent):
            card = event.card
    assert card is not None
    return card, client


def query_turn() -> Response:
    return Response(uses=[Block(type="tool_use", id="tu_1", name="query_sales",
                                input={"measures": ["net_sales_sek"],
                                       "dimensions": ["month"]})])


# ------------------------------------------------------------- the gate is on data, not status

@pytest.mark.parametrize("status", ["ok", "clarify", "cannot_answer", "partial"])
@pytest.mark.asyncio
async def test_a_fabricated_figure_is_caught_under_every_status(monkeypatch, status):
    """The B1 regression: `clarify` must not be a way around the numeric check.

    Both scripted answers quote 9 900 000 kr, which appears nowhere in PAYLOAD. The loop
    retries once, the retry is just as wrong, and the prose must be dropped.
    """
    lie = f"Försäljningen i mars var 9 900 000,00 kr.\n{envelope(status)}"
    card, client = await run(monkeypatch, [query_turn(), Response(lie), Response(lie)])

    assert card.status == "validation_failed"
    assert card.narrative == ""
    assert client.messages.calls == 3, "the model should have been asked to try again"
    # The chart survives — it is drawn from the cache and never passed through the model.
    assert card.chart is not None
    assert any("kunde inte verifieras" in c for c in card.caveats)


@pytest.mark.parametrize("status", ["ok", "clarify"])
@pytest.mark.asyncio
async def test_a_true_figure_passes_under_every_status(monkeypatch, status):
    truth = f"Mars landade på 3 450 900,50 kr exkl. moms.\n{envelope(status)}"
    card, client = await run(monkeypatch, [query_turn(), Response(truth)])

    assert card.status == status
    assert "3 450 900,50" in card.narrative
    assert client.messages.calls == 2, "a valid answer must not trigger a regeneration"


@pytest.mark.asyncio
async def test_the_retry_is_accepted_when_it_corrects_itself(monkeypatch):
    lie = f"Mars gav 9 900 000 kr.\n{envelope('clarify')}"
    fixed = f"Mars gav 3 450 900,50 kr.\n{envelope('clarify')}"
    card, _ = await run(monkeypatch, [query_turn(), Response(lie), Response(fixed)])

    assert card.status == "clarify"
    assert "3 450 900,50" in card.narrative


@pytest.mark.asyncio
async def test_no_tool_data_means_nothing_to_validate_against(monkeypatch):
    """With no rows the validator has no reference set, so the turn must not be blocked.

    build_card downgrades a resultless `ok` to `cannot_answer` on its own; that is the
    behaviour being pinned here, not a validation outcome.
    """
    card, client = await run(monkeypatch, [
        Response(f"Jag kan inte svara på det utan att veta vilket år du menar.\n"
                 f"{envelope('clarify')}")])

    assert card.status == "clarify"
    assert client.messages.calls == 1
    assert card.narrative
