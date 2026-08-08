"""Every type in docs/API_CONTRACT.md, as Pydantic."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field, field_validator

Role = Literal["supplier_viewer", "supplier_admin", "retail_analyst", "system_admin"]
# str, not Literal: a unit is "st"/"%"/"p.e." or an ISO-4217 currency code set by deployment.
# "p.e." is its own unit, not a flavour of "%", so share-point deltas can't misread as percent.
Unit = str
NON_CURRENCY_UNITS = ("st", "%", "p.e.")
ChartType = Literal["line", "bar", "stacked_bar", "area", "pie", "kpi", "table"]
# "explain" answers questions about the card itself (no query needed) - separate from
# cannot_answer so a valid explanation isn't shown under a false "no data" message.
CardStatus = Literal["ok", "cannot_answer", "clarify", "validation_failed", "explain"]



class LoginRequest(BaseModel):
    email: str
    password: str


# Ceiling, not just floor: Argon2id hashes whatever length it's given, so an unbounded
# password field is unbounded work per request.
_MAX_PASSWORD = 200


class NewPassword(BaseModel):
    """The one place a new password is validated, so every route that sets one agrees.

    Length only, deliberately: composition rules ("one digit, one symbol") measurably push
    people towards weaker and more predictable passwords, which is why NIST SP 800-63B dropped
    them. The minimum is a setting so a deployment can raise it without a code change.
    """

    new_password: str = Field(max_length=_MAX_PASSWORD)

    @field_validator("new_password")
    @classmethod
    def _long_enough(cls, value: str) -> str:
        from .config import settings

        if len(value) < settings.password_min_length:
            raise ValueError(f"lösenordet måste vara minst {settings.password_min_length} "
                             f"tecken")
        return value


class ChangePasswordRequest(NewPassword):
    """Changing a password requires proving you know the current one.

    Without this, a borrowed session - a shared laptop, an unlocked screen - becomes permanent
    account takeover, because the attacker can lock the owner out.
    """

    current_password: str = Field(max_length=_MAX_PASSWORD)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(max_length=320)   # RFC 5321 maximum


class ResetPasswordRequest(NewPassword):
    token: str = Field(min_length=1, max_length=4000)


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
    # Server-owned: validate_chart strips whatever the model puts here - a model-invented
    # annotation is exactly the kind of unchecked claim this pipeline exists to prevent.
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
    # ISO-4217, from the tool's own meta, so a card can't claim a currency the query didn't run in.
    # `vat` is a code, not a phrase - the reader's language decides the wording.
    currency: str = "SEK"
    vat: Literal["excl", "incl"] = "excl"
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
    # : The chart's provenance, kept for compatibility - it is `sources[i]` for the chart's id.
    provenance: Provenance | None = None
    # : Every result the turn produced, chart's first.
    sources: list[ToolCallRecord] = Field(default_factory=list)
    # : Which query licensed each accepted figure in the narrative.
    claims: list[Claim] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)



class Kpi(BaseModel):
    key: Literal["net_sales_sek", "category_share_pct", "units", "avg_price_sek"]
    label: str
    value: float
    unit: Unit
    delta_pct: float | None = None
    delta_label: str | None = None
    rank_label: str | None = None
    # Oldest-first shape, not a reading: no axis or labels, just enough to show steady growth
    # vs. one good month vs. a trend that just turned.
    spark: list[float] = Field(default_factory=list)


class DashboardResponse(BaseModel):
    kpis: list[Kpi]
    cards: list[AnswerCard]


class MoversResponse(BaseModel):
    """Biggest risers and biggest fallers, in that order."""
    cards: list[AnswerCard]



class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


# The history caps.
MAX_HISTORY_TURNS = 20
MAX_HISTORY_CHARS = 24_000


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=MAX_HISTORY_TURNS)
    # In the body, not middleware context: the answer streams from a generator running outside
    # the middleware's task, and a language that reverts mid-stream is worse than none.
    lang: str | None = None

    @field_validator("history")
    @classmethod
    def _history_fits_in_a_prompt(cls, turns: list[ChatTurn]) -> list[ChatTurn]:
        """Turn count alone is not a bound - one turn can hold a megabyte of text."""
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
    # : None for tools with no row concept (get_capabilities, resolve_entities) - so the chip
    # says nothing rather than "0 rader" next to a green tick.
    row_count: int | None = None


class TokenEvent(BaseModel):
    type: Literal["token"] = "token"
    text: str


class PreviewEvent(BaseModel):
    """The chart, as soon as its rows land and seconds before the prose is written.

    The chart was never the untrusted half - it is drawn from the cached rows, not from the
    model - so showing it early costs nothing in trust. The prose is still withheld until it
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



class ResultPage(BaseModel):
    query_id: str
    columns: list[Column]
    rows: list[dict[str, Any]]
    row_count: int
    truncated: bool



# The tools a saved card may re-run.
CardTool = Literal["query_sales", "query_market_share"]
# : Same allowlist as a set, for the read path - derived from the type instead of written
# twice, so the two can never drift apart.
ALLOWED_CARD_TOOLS = frozenset(get_args(CardTool))


class SaveCardRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    chart: ChartSpec
    tool_name: CardTool
    tool_args: dict[str, Any]

    @field_validator("tool_args")
    @classmethod
    def _args_required(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("tool_args saknas - kortet skulle aldrig gå att uppdatera")
        return value


class ShareRequest(BaseModel):
    card_id: str
    # ponytail: only `live` is served - a real snapshot needs a table and retention policy, not
    # just a flag. Mode rides in the token so the read side can honour it later without reissuing.
    mode: Literal["snapshot", "live"] = "live"


class ShareResponse(BaseModel):
    url: str
    expires_at: str


class SharedView(BaseModel):
    """What a share link resolves to, for a reader with no session at all."""

    card: AnswerCard
    # Inline: the reader can't call /api/result, since that endpoint is tenant-scoped and this
    # page deliberately has no login.
    result: ResultPage
    shared_by: str
    expires_at: str
    mode: Literal["snapshot", "live"]
