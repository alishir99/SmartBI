"""Every type in docs/API_CONTRACT.md, as Pydantic.

The contract is frozen and the frontend is coded against it, so these models are a literal
transcription — no extra fields, no renames, no convenience additions. Where a field is
nullable in the contract it is nullable here, including the ones that look like they could
be omitted; a missing key and a `null` are different things to a TypeScript consumer.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["supplier_viewer", "supplier_admin", "retail_analyst", "system_admin"]
Unit = Literal["SEK", "st", "%"]
ChartType = Literal["line", "bar", "stacked_bar", "area", "pie", "kpi", "table"]
CardStatus = Literal["ok", "cannot_answer", "clarify", "validation_failed"]


# ------------------------------------------------------------------------------ auth

class LoginRequest(BaseModel):
    email: str
    password: str


class User(BaseModel):
    user_id: int
    email: str
    display_name: str
    role: Role
    supplier_id: int | None
    supplier_name: str | None


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: User


# ---------------------------------------------------------------------- shared types

class Column(BaseModel):
    key: str
    type: Literal["date", "text", "number"]
    label: str
    unit: Unit | None = None


class ChartSpec(BaseModel):
    """What the model is allowed to emit about presentation. Note what is absent: values.

    `extra="forbid"` so an invented field is a validation error rather than something the
    frontend silently ignores.
    """

    model_config = ConfigDict(extra="forbid")

    type: ChartType
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    series: str | None = None
    sort: Literal["asc", "desc"] | None = None
    limit: int | None = None
    title: str
    subtitle: str | None = None


class TimeWindow(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = ConfigDict(populate_by_name=True)


class Provenance(BaseModel):
    """The source chip (§9.3). Everything a grader needs to trace a number on screen.

    `scope` is the hashed supplier label the MCP server produces, not the raw id — the chip
    is visible in the UI and a raw tenant id there is an unnecessary disclosure.
    """

    model_config = ConfigDict(populate_by_name=True)

    tool: str
    source: str
    scope: str
    currency: Literal["SEK"] = "SEK"
    vat: str = "exkl. moms"
    time_range: TimeWindow
    compare_range: TimeWindow | None = None
    coverage: TimeWindow
    filters_applied: dict[str, Any] = Field(default_factory=dict)
    row_count: int
    truncated: bool
    executed_at: str
    tool_args: dict[str, Any] = Field(default_factory=dict)


class Claim(BaseModel):
    """One numeric literal in the narrative and the query that licensed it.

    What turns "the numbers are checked" into "this number came from that query". The
    validator already knew which result accounted for each figure and threw the mapping away
    at the last step.
    """

    literal: str
    query_id: str


class ToolCallRecord(BaseModel):
    """One tool result produced during the turn, with its own provenance.

    A card used to carry a single `query_id` while `validate_narrative` checked the prose
    against *every* result the turn produced. So prose grounded in result A could ship beside
    a chart of result B and a source chip describing B's filters and time range — the one
    artefact whose entire purpose is traceability, pointing at the wrong query. Recording
    every result makes the card's provenance true rather than approximately true.
    """

    query_id: str
    tool: str
    provenance: Provenance
    row_count: int


class AnswerCard(BaseModel):
    """The single unit both the dashboard and the chat produce.

    One card type, two producers, is what lets a chat answer be pinned next to a standard
    dashboard tile — and what guarantees the two can never disagree about a number, since
    both got it from the same MCP tool.
    """

    card_id: str | None = None
    status: CardStatus = "ok"
    narrative: str = ""
    insights: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    chart: ChartSpec | None = None
    #: The chart's source. Still singular, because a chart is drawn from exactly one result.
    query_id: str | None = None
    columns: list[Column] = Field(default_factory=list)
    #: The chart's provenance, kept for compatibility — it is `sources[i]` for the chart's id.
    provenance: Provenance | None = None
    #: Every result the turn produced, chart's first.
    sources: list[ToolCallRecord] = Field(default_factory=list)
    #: Which query licensed each accepted figure in the narrative.
    claims: list[Claim] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)


# ------------------------------------------------------------------------- dashboard

class Kpi(BaseModel):
    key: Literal["net_sales_sek", "category_share_pct", "units", "avg_price_sek"]
    label: str
    value: float
    unit: Unit
    delta_pct: float | None = None
    delta_label: str | None = None
    rank_label: str | None = None


class DashboardResponse(BaseModel):
    kpis: list[Kpi]
    cards: list[AnswerCard]


# ------------------------------------------------------------------------------ chat

class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


# The history caps. `question` was capped at 2000 chars while `history` was unbounded, which
# made that cap decorative: history goes into the same prompt, so a single request could carry
# megabytes of "prior conversation" and bill the tenant for all of it on every LLM call in the
# turn. The frontend sends at most the last 8 entries (web/src/lib/chat.ts), and a card
# narrative runs a few hundred characters, so a real client lands around 8 turns / 10 k chars.
# Both ceilings are roughly double that: invisible to the product, immediately fatal to the
# amplifier.
MAX_HISTORY_TURNS = 20
MAX_HISTORY_CHARS = 24_000


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)

    @field_validator("history")
    @classmethod
    def _history_fits_in_a_prompt(cls, turns: list[ChatTurn]) -> list[ChatTurn]:
        """Turn count alone is not a bound — one turn can hold a megabyte of text.

        Rejected rather than truncated: silently dropping half of what a client sent would
        make the model answer a conversation the user cannot see, and no legitimate client
        can reach this ceiling anyway.
        """
        if (total := sum(len(turn.content) for turn in turns)) > MAX_HISTORY_CHARS:
            raise ValueError(
                f"historiken är {total} tecken, högst {MAX_HISTORY_CHARS} tillåts")
        return turns


# The SSE event union. Modelled so the shapes are checked in one place before they are
# serialised into `data: <json>`; the wire format is built by agent/loop.py.
class StatusEvent(BaseModel):
    type: Literal["status"] = "status"
    message: str


class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool: str
    args: dict[str, Any]


class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool: str
    row_count: int


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str


class CardEvent(BaseModel):
    type: Literal["card"] = "card"
    card: AnswerCard


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


class UsageEvent(BaseModel):
    """Token accounting for one turn. Internal: the chat route consumes it to fill
    `audit_turn.input_tokens`/`output_tokens` and does NOT forward it over SSE.

    It travels as an event rather than a return value because `run_turn` is a generator and
    the counts are only complete once it has finished — and because a turn that dies partway
    still has real cost to record. Keeping it off the wire is deliberate: the browser has no
    use for token counts, and the per-tenant cost cap this feeds is a server-side concern.
    """
    type: Literal["usage"] = "usage"
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    llm_calls: int = 0


# ----------------------------------------------------------------------------- result

class ResultPage(BaseModel):
    query_id: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool


# ------------------------------------------------------------- saved views and sharing

# The tools a saved card may re-run. A free string here meant an authenticated user could
# name any tool the MCP server exposes — or one it does not — and have `GET /api/cards` call
# it on every dashboard load, forever. Scope was never at risk (the supplier id is a header
# the client cannot set), so this is resource exhaustion rather than a leak, but the fix is
# the same either way: an allowlist. Only the two row-returning tools are listed;
# `get_capabilities` and `resolve_entities` return no rows and cannot become a chart, so a
# card naming them is meaningless rather than merely unsupported.
CardTool = Literal["query_sales", "query_market_share"]
#: The same allowlist as a set, for the read path — derived from the type rather than written
#: twice, so the two can never drift apart.
ALLOWED_CARD_TOOLS = frozenset(get_args(CardTool))


class SaveCardRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    chart: ChartSpec
    tool_name: CardTool
    # Persisting the arguments rather than the rows is what lets a saved card re-run live
    # against fresh data (§10). A screenshot would freeze both the numbers and the bug.
    tool_args: dict[str, Any] = Field(default_factory=dict)


class ShareRequest(BaseModel):
    card_id: str
    # Snapshot by default: a live link re-executes under *someone's* tenant scope, and
    # getting that wrong is a data leak. "live" is an explicit opt-in (§10).
    mode: Literal["snapshot", "live"] = "snapshot"


class ShareResponse(BaseModel):
    url: str
    expires_at: str
