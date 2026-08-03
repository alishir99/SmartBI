"""Every type in docs/API_CONTRACT.md, as Pydantic."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["supplier_viewer", "supplier_admin", "retail_analyst", "system_admin"]
# "p.e." is percentage points, and it is a unit of its own rather than a flavour of "%": a share
# moving 29,5 → 30,7 has risen 1,2 p.e., and letting the two share one unit is what let the model
# call that "+1,2 procent" and pass validation (G2).
Unit = Literal["SEK", "st", "%", "p.e."]
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
    """What the model is allowed to emit about presentation."""

    model_config = ConfigDict(extra="forbid")

    type: ChartType
    x: str | None = None
    y: list[str] = Field(default_factory=list)
    series: str | None = None
    sort: Literal["asc", "desc"] | None = None
    limit: int | None = None
    title: str
    subtitle: str | None = None
    # Server-owned: x values worth a line on the axis, and one sentence saying what they mean.
    # `validate_chart` drops whatever a model puts here — an annotation the model invented is
    # exactly the kind of claim the rest of this pipeline exists to prevent.
    markers: list[str] = Field(default_factory=list)
    marker_label: str | None = None


class TimeWindow(BaseModel):
    from_: str = Field(alias="from")
    to: str

    model_config = ConfigDict(populate_by_name=True)


class Provenance(BaseModel):
    """The source chip (§9.3)."""

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
    """One numeric literal in the narrative and the query that licensed it."""

    literal: str
    query_id: str


class ToolCallRecord(BaseModel):
    """One tool result produced during the turn, with its own provenance."""

    query_id: str
    tool: str
    provenance: Provenance
    row_count: int


class AnswerCard(BaseModel):
    """The single unit both the dashboard and the chat produce."""

    card_id: str | None = None
    status: CardStatus = "ok"
    narrative: str = ""
    insights: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    chart: ChartSpec | None = None
    # : The chart's source.
    query_id: str | None = None
    columns: list[Column] = Field(default_factory=list)
    # : The chart's provenance, kept for compatibility — it is `sources[i]` for the chart's id.
    provenance: Provenance | None = None
    # : Every result the turn produced, chart's first.
    sources: list[ToolCallRecord] = Field(default_factory=list)
    # : Which query licensed each accepted figure in the narrative.
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
    # The measure over the window's own grain, oldest first. An arrow gives direction; this
    # gives shape — steady growth, one good month, or a trend that has just turned. It carries
    # no axis and no labels, so it is a shape and never a reading.
    spark: list[float] = Field(default_factory=list)


class DashboardResponse(BaseModel):
    kpis: list[Kpi]
    cards: list[AnswerCard]


class MoversResponse(BaseModel):
    """Biggest risers and biggest fallers, in that order."""
    cards: list[AnswerCard]


# ------------------------------------------------------------------------------ chat

class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


# The history caps.
MAX_HISTORY_TURNS = 20
MAX_HISTORY_CHARS = 24_000


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)

    @field_validator("history")
    @classmethod
    def _history_fits_in_a_prompt(cls, turns: list[ChatTurn]) -> list[ChatTurn]:
        """Turn count alone is not a bound — one turn can hold a megabyte of text."""
        if (total := sum(len(turn.content) for turn in turns)) > MAX_HISTORY_CHARS:
            raise ValueError(
                f"historiken är {total} tecken, högst {MAX_HISTORY_CHARS} tillåts")
        return turns


# The SSE event union.
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
    # : None for tools with no row concept (get_capabilities, resolve_entities) — the chip then
    # says nothing rather than "0 rader" next to a green tick.
    row_count: int | None = None


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str


class PreviewEvent(BaseModel):
    """The chart, as soon as its rows land and seconds before the prose is written.

    The chart was never the untrusted half — it is drawn from the cached rows, not from the
    model — so showing it early costs nothing in trust. The prose is still withheld until it
    has been validated, which is the part that can be wrong. Not terminal: a `card` follows.
    """
    type: Literal["preview"] = "preview"
    card: AnswerCard


class CardEvent(BaseModel):
    type: Literal["card"] = "card"
    card: AnswerCard


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str


class UsageEvent(BaseModel):
    """Token accounting for one turn."""
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

# The tools a saved card may re-run.
CardTool = Literal["query_sales", "query_market_share"]
# : The same allowlist as a set, for the read path — derived from the type rather than written :
# twice, so the two can never drift apart.
ALLOWED_CARD_TOOLS = frozenset(get_args(CardTool))


class SaveCardRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    chart: ChartSpec
    tool_name: CardTool
    # Persisting the arguments rather than the rows is what lets a saved card re-run live
    # against fresh data (§10).
    tool_args: dict[str, Any] = Field(default_factory=dict)


class ShareRequest(BaseModel):
    card_id: str
    # ponytail: only `live` is served. A frozen snapshot means storing the rows as they were,
    # which is a table and a retention policy, not a flag — the mode is carried in the token so
    # the read side can start honouring it without reissuing links.
    mode: Literal["snapshot", "live"] = "live"


class ShareResponse(BaseModel):
    url: str
    expires_at: str


class SharedView(BaseModel):
    """What a share link resolves to, for a reader with no session at all."""

    card: AnswerCard
    # Inline, because the reader cannot call /api/result — that endpoint is scoped to a
    # logged-in tenant, and this page deliberately has no login.
    result: ResultPage
    shared_by: str
    expires_at: str
    mode: Literal["snapshot", "live"]
