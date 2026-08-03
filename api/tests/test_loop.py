"""Tests for the agent turn: the validation gate, the loop's bounds, and its bookkeeping."""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest

from api.agent import loop as agent_loop
from api.models import CardEvent, PreviewEvent, StatusEvent, ToolResultEvent, UsageEvent
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


class Usage:
    def __init__(self, **fields):
        self.__dict__.update(fields)


class Response:
    def __init__(self, text: str = "", uses: list | None = None, usage: Usage | None = None):
        self.content = list(uses or [])
        if text:
            self.content.append(Block(type="text", text=text))
        self.stop_reason = "tool_use" if uses else "end_turn"
        self.usage = usage


class FakeMessages:
    def __init__(self, script: list[Response], *, repeat_last: bool = False):
        self.script = list(script)
        self.calls = 0
        # `repeat_last` models the case the iteration cap exists for: a model that will keep
        # asking for tools no matter what it is told.
        self.repeat_last = repeat_last
        self.kwargs: list[dict] = []

    async def create(self, **kwargs):
        self.calls += 1
        self.kwargs.append(kwargs)
        if self.calls > 200:
            raise AssertionError("runaway loop — the iteration cap did not hold")
        if not self.script:
            raise AssertionError("the loop asked the model for more turns than were scripted")
        return self.script[0] if self.repeat_last and len(self.script) == 1 \
            else self.script.pop(0)


class FakeClient:
    def __init__(self, script, *, repeat_last: bool = False):
        self.messages = FakeMessages(script, repeat_last=repeat_last)


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


async def run(monkeypatch, script, *, repeat_last: bool = False) -> object:
    client = FakeClient(script, repeat_last=repeat_last)
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


async def usage_of(monkeypatch, script) -> UsageEvent | None:
    client = FakeClient(script)
    monkeypatch.setattr(agent_loop.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(agent_loop, "_client", lambda: client)
    events = [event async for event in
              agent_loop.run_turn(question="Hur gick mars?", history=[], supplier_id=1,
                                  mcp=FakeMcp(), cache=ResultCache())]
    return next((e for e in events if isinstance(e, UsageEvent)), None), events


def query_turn() -> Response:
    return Response(uses=[Block(type="tool_use", id="tu_1", name="query_sales",
                                input={"measures": ["net_sales_sek"],
                                       "dimensions": ["month"]})])


# ------------------------------------------------------------- the gate is on data, not status

@pytest.mark.parametrize("status", ["ok", "clarify", "cannot_answer", "partial"])
@pytest.mark.asyncio
async def test_a_fabricated_figure_is_caught_under_every_status(monkeypatch, status):
    """The B1 regression: `clarify` must not be a way around the numeric check."""
    lie = f"Försäljningen i mars var 9 900 000,00 kr.\n{envelope(status)}"
    card, client = await run(monkeypatch, [query_turn(), Response(lie), Response(lie)])

    assert card.status == "validation_failed"
    assert card.narrative == ""
    assert client.messages.calls == 3, "the model should have been asked to try again"
    # The chart survives — it is drawn from the cache and never passed through the model.
    assert card.chart is not None
    # The status carries the explanation; the card renders it from there, once.
    assert not any("kunde inte verifieras" in c for c in card.caveats)


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
async def test_the_retry_still_declares_the_tools(monkeypatch):
    """B7."""
    lie = f"Mars gav 9 900 000 kr.\n{envelope('ok')}"
    fixed = f"Mars gav 3 450 900,50 kr.\n{envelope('ok')}"
    card, client = await run(monkeypatch, [query_turn(), Response(lie), Response(fixed)])

    assert card.status == "ok"
    retry = client.messages.kwargs[-1]
    assert retry["tools"], "the regeneration request dropped the tool declarations"
    # And the history it carries is exactly why that matters.
    def block_type(block):
        return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)

    assert any(block_type(block) == "tool_use"
               for message in retry["messages"]
               if isinstance(message.get("content"), list)
               for block in message["content"])


@pytest.mark.asyncio
async def test_a_model_that_never_stops_asking_for_tools_is_cut_off(monkeypatch):
    """B6."""
    card, client = await run(monkeypatch, [query_turn()], repeat_last=True)

    assert client.messages.calls == agent_loop.MAX_ROUNDS
    # The turn still ends in a card rather than an error, and the rows it did fetch survive.
    assert card is not None
    assert card.chart is not None


@pytest.mark.asyncio
async def test_the_tool_budget_is_never_exceeded(monkeypatch):
    """The other half: the round cap must not become a way to buy more tool calls."""
    _, client = await run(monkeypatch, [query_turn()], repeat_last=True)
    assert client.messages.calls == agent_loop.MAX_ROUNDS
    assert agent_loop.MAX_TOOL_CALLS < agent_loop.MAX_ROUNDS, (
        "a round cap at or below the tool budget would cut turns off before they spend it")


# --------------------------------------------------------- which result the card is about

class FakeResult:
    """`_result_for` only ever reads `.query_id`."""

    def __init__(self, query_id: str):
        self.query_id = query_id


def test_a_query_id_we_minted_is_honoured():
    a, b = FakeResult("q_a"), FakeResult("q_b")
    assert agent_loop._result_for({"query_id": "q_a"}, [a, b]) is a


def test_a_query_id_we_never_minted_falls_back_to_our_own():
    """The security reason this function has a docstring: `query_id` arrives inside the model's
    JSON envelope, which is generated text."""
    ours = FakeResult("q_ours")
    assert agent_loop._result_for({"query_id": "q_someone_elses"}, [ours]) is ours


@pytest.mark.parametrize("envelope_value", [
    {},                                  # the model said nothing
    {"query_id": None},
    {"query_id": ""},                    # falsy, so the lookup is skipped entirely
    {"query_id": 12345},                 # not even a string
    {"query_id": ["q_a"]},               # unhashable-ish shapes must not raise
])
def test_a_missing_or_malformed_query_id_never_raises(envelope_value):
    last = FakeResult("q_last")
    assert agent_loop._result_for(envelope_value, [FakeResult("q_first"), last]) is last


def test_no_results_means_no_card_source():
    assert agent_loop._result_for({"query_id": "q_a"}, []) is None


# ------------------------------------------------------- the chart arrives before the prose

@pytest.mark.asyncio
async def test_the_chart_is_emitted_as_soon_as_its_rows_land(monkeypatch):
    """Mean latency is 26 s; the chart is ready long before the prose has been validated."""
    truth = f"Mars gav 3 450 900,50 kr.\n{envelope('ok')}"
    _, events = await usage_of(monkeypatch, [query_turn(), Response(truth)])

    kinds = [type(e).__name__ for e in events]
    preview = next(e for e in events if isinstance(e, PreviewEvent))

    # Before the model was asked to compose, and before the final card.
    assert kinds.index("PreviewEvent") < kinds.index("CardEvent")
    assert preview.card.chart is not None
    assert preview.card.query_id is not None


@pytest.mark.asyncio
async def test_the_preview_carries_the_chart_but_never_the_prose(monkeypatch):
    """The prose is the part that can be wrong, and it stays withheld until validated."""
    truth = f"Mars gav 3 450 900,50 kr.\n{envelope('ok')}"
    _, events = await usage_of(monkeypatch, [query_turn(), Response(truth)])

    preview = next(e for e in events if isinstance(e, PreviewEvent))

    assert preview.card.narrative == ""
    assert preview.card.insights == []


@pytest.mark.asyncio
async def test_a_turn_with_no_rows_emits_no_preview(monkeypatch):
    """cannot_answer has nothing to chart, so there is nothing to show early."""
    _, events = await usage_of(monkeypatch, [
        Response(f"Marginal finns inte i datan.\n{envelope('cannot_answer')}")])

    assert not any(isinstance(e, PreviewEvent) for e in events)


# ------------------------------------------------------------------- cost accounting

@pytest.mark.asyncio
async def test_usage_is_summed_across_every_call_in_the_turn(monkeypatch):
    """`audit_turn` has had input_tokens/output_tokens since the first schema and wrote NULL into
    both, because nothing collected what the SDK returns on every call."""
    truth = f"Mars gav 3 450 900,50 kr.\n{envelope('ok')}"
    usage, _ = await usage_of(monkeypatch, [
        Response(uses=[Block(type="tool_use", id="tu_1", name="query_sales", input={})],
                 usage=Usage(input_tokens=2000, output_tokens=100,
                             cache_creation_input_tokens=1900, cache_read_input_tokens=0)),
        Response(truth, usage=Usage(input_tokens=300, output_tokens=250,
                                    cache_creation_input_tokens=0,
                                    cache_read_input_tokens=1900)),
    ])

    assert usage is not None
    assert usage.llm_calls == 2
    assert usage.input_tokens == 2300
    assert usage.output_tokens == 350
    # The whole point of the cached prefix: written once, read back on the second call.
    assert usage.cache_write_tokens == 1900
    assert usage.cache_read_tokens == 1900


@pytest.mark.asyncio
async def test_usage_is_reported_even_when_the_turn_fails(monkeypatch):
    """A turn that dies partway still spent real money."""
    usage, events = await usage_of(monkeypatch, [])   # empty script → the fake raises

    assert any(type(e).__name__ == "ErrorEvent" for e in events)
    assert usage is not None and usage.llm_calls == 0


@pytest.mark.asyncio
async def test_usage_survives_a_provider_that_reports_none(monkeypatch):
    """Not every Anthropic-compatible endpoint returns a usage block, and a missing one must not
    take the turn down with it."""
    truth = f"Mars gav 3 450 900,50 kr.\n{envelope('ok')}"
    usage, _ = await usage_of(monkeypatch, [query_turn(), Response(truth)])

    assert usage is not None
    assert (usage.input_tokens, usage.output_tokens, usage.llm_calls) == (0, 0, 0)


def test_the_cached_prefix_is_only_sent_to_anthropic(monkeypatch):
    """`cache_control` attaches to content blocks, so `system=SYSTEM` as a bare string was
    structurally ready for caching and never requested it."""
    monkeypatch.setattr(agent_loop.settings, "llm_base_url", "https://api.deepseek.com/anthropic")
    assert isinstance(agent_loop._system(), str)

    monkeypatch.setattr(agent_loop.settings, "llm_base_url", "https://api.anthropic.com")
    blocks = agent_loop._system()
    assert isinstance(blocks, list)
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}
    assert blocks[0]["text"] == agent_loop.SYSTEM


@pytest.mark.asyncio
async def test_no_tool_data_means_nothing_to_validate_against(monkeypatch):
    """With no rows the validator has no reference set, so the turn must not be blocked."""
    card, client = await run(monkeypatch, [
        Response(f"Jag kan inte svara på det utan att veta vilket år du menar.\n"
                 f"{envelope('clarify')}")])

    assert card.status == "clarify"
    assert client.messages.calls == 1
    assert card.narrative


# -------------------------------------------------------- which lookups counted as a miss

@pytest.mark.parametrize("asked, labels, resembles", [
    # The refusal path. Retrieval fuses lexical and semantic search, so a competitor's name
    # comes back with the nearest brand the supplier does own — a hit by count, a miss in fact.
    ("Lumia Nordic", ["Nordström", "Vidar"], False),
    ("Lumia Nordic", [], False),
    # A typo must still resolve, or the answer stops naming a brand the user owns.
    ("nordstrom", ["Nordström"], True),
    ("Hörlurar", ["Hörlurar"], True),
    ("vidar hörlurar", ["Vidar Hörlurar V191 Studio"], True),
])
def test_a_lookup_counts_as_a_miss_unless_something_like_it_came_back(asked, labels, resembles):
    assert agent_loop.resembles_any(asked, labels) is resembles


# ------------------------------------------------------------------ the visible status

@pytest.mark.asyncio
async def test_the_status_stops_claiming_to_fetch_once_the_tools_are_done(monkeypatch):
    """'Hämtar försäljningssiffror…' sat on screen for ~25 s after the rows had landed."""
    client = FakeClient([query_turn(), Response(f"Mars: {MARS:,.2f} kr.\n{envelope('ok')}")])
    monkeypatch.setattr(agent_loop.settings, "llm_api_key", "test-key")
    monkeypatch.setattr(agent_loop, "_client", lambda: client)

    events = [e async for e in
              agent_loop.run_turn(question="Hur gick mars?", history=[], supplier_id=1,
                                  mcp=FakeMcp(), cache=ResultCache())]

    last_result = max(i for i, e in enumerate(events) if isinstance(e, ToolResultEvent))
    after = [e.message for e in events[last_result:] if isinstance(e, StatusEvent)]
    assert after, "the turn goes quiet after the last tool result"
    assert not any("Hämtar" in message for message in after)
