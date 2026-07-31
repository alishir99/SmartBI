"""Every type in docs/API_CONTRACT.md, as Pydantic.

The contract is frozen and the frontend is coded against it, so these models are a literal
transcription — no extra fields, no renames, no convenience additions. Where a field is
nullable in the contract it is nullable here, including the ones that look like they could
be omitted; a missing key and a `null` are different things to a TypeScript consumer.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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
    query_id: str | None = None
    columns: list[Column] = Field(default_factory=list)
    provenance: Provenance | None = None
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


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list)


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

class SaveCardRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    chart: ChartSpec
    tool_name: str
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
