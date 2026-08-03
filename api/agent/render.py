"""Turn a tool result plus the model's envelope into an AnswerCard."""

from __future__ import annotations

import json
import logging
import re
from calendar import monthrange
from collections.abc import Sequence
from datetime import date
from typing import Any, cast

from ..models import (
    AnswerCard,
    CardStatus,
    ChartSpec,
    Claim,
    Column,
    Provenance,
    TimeWindow,
    ToolCallRecord,
)
from ..result_cache import CachedResult
from .validate import Attribution

logger = logging.getLogger(__name__)

# The model is told to end with exactly one ```json block.
_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)

_FALLBACK_TITLE = "Resultat"

# The card renders the narrative as text, not as markdown. The prompt says so; this is the
# belt-and-braces, because a stray ** reads as broken to the user and glues itself to the
# number the validator is trying to match.
_EMPHASIS = re.compile(r"(\*\*|__)(\S.*?\S|\S)\1", re.DOTALL)


# The model writes markdown lists despite an explicit prompt rule and an `insights[]` field
# built for exactly that; under `whitespace-pre-line` they render as literal hyphens.
_BULLET = re.compile(r"^[ \t]*[-*•]\s+", re.MULTILINE)

# And headings: "## Hörlurar - juli 2025 till juni 2026" arrived on a card that already
# carried that exact title and period in its header. The hashes render literally, and the
# line was noise even without them.
_HEADING = re.compile(r"^[ \t]*#{1,6}[ \t]+", re.MULTILINE)

# A dash used as a pause mid-sentence is the single clearest tell that nobody typed this. Both
# characters go, but only where they are punctuation: an en dash with a space either side is a
# pause, while "jul 2025-jun 2026" is a range and every period label on the card is written
# that way. A hyphen carries the same pause and reads as a person typing.
_PAUSE_DASH = re.compile(r"\s+[–—]\s+|—")


def strip_markdown(text: str) -> str:
    """Drop the markdown and the tells the model was told not to emit."""
    text = _EMPHASIS.sub(r"\2", text)
    text = _HEADING.sub("", text)
    text = _BULLET.sub("", text)
    return _PAUSE_DASH.sub(lambda m: " - " if m.group().strip() != m.group() else "-", text)


# What an unresolvable name is replaced by. The prompt already says not to repeat the name a
# refusal is about; this is the same rule in code, because a guarantee that lives only in a
# prompt is a guarantee the model gets to decide about.
_REDACTED_NAME = "det efterfrågade namnet"
_SENTENCE_START = re.compile(rf"(\A|[.!?]\s+){re.escape(_REDACTED_NAME)}")
_QUOTE = "[\"'«»‘’“”]?"
# The words the model looked up are rarely the whole name it then writes: it resolves "Lumia"
# and writes "Lumia Nordic". Redacting only the looked-up part left `det efterfrågade namnet
# Nordic"` in the prose - the competitor still named, and the sentence broken as well. So the
# capitalised run continuing the name goes with it. Not case-insensitive, deliberately: this
# part must match capitalisation or it swallows the rest of the sentence.
_NAME_TAIL = r"(?:[-\s]+[A-ZÅÄÖ][\w]*)*"
_REPEATS = re.compile(rf"{re.escape(_REDACTED_NAME)}(\s+{re.escape(_REDACTED_NAME)})+")


def scrub_names(text: str, names: Sequence[str]) -> str:
    """Take names the turn could not resolve back out of the prose.

    Confirming which name was and was not in the data is itself a statement about someone else,
    and it is the one the refusal path made on every run.
    """
    for name in sorted({n.strip() for n in names if len(n.strip()) >= 3}, key=len, reverse=True):
        # Surrounding quotes go too, or the redaction is left sitting inside "…".
        text = re.sub(rf"{_QUOTE}(?i:{re.escape(name)}){_NAME_TAIL}{_QUOTE}",
                      _REDACTED_NAME, text)
    text = _REPEATS.sub(_REDACTED_NAME, text)
    return _SENTENCE_START.sub(
        lambda m: f"{m.group(1)}{_REDACTED_NAME[0].upper()}{_REDACTED_NAME[1:]}", text)


def split_answer(text: str) -> tuple[str, dict[str, Any]]:
    """Separate the Swedish prose from the JSON envelope."""
    blocks = list(_JSON_BLOCK.finditer(text))
    if not blocks:
        return strip_markdown(text.strip()), {}

    last = blocks[-1]
    narrative = strip_markdown((text[: last.start()] + text[last.end():]).strip())
    try:
        envelope = json.loads(last.group(1))
    except json.JSONDecodeError:
        return narrative, {}
    return narrative, envelope if isinstance(envelope, dict) else {}


# Columns the tools carry for policy and joining, which are not part of the answer.
_INTERNAL_COLUMNS = frozenset({"suppressed", "truncated"})


def _presentable(column: dict) -> bool:
    """Belongs in anything a user reads: the table view, the CSV, the card's columns."""
    key = column.get("key", "")
    return key not in _INTERNAL_COLUMNS and not key.endswith("_id")


def presentable_columns(result: CachedResult) -> list[dict]:
    """The result's columns, minus the ones that exist for the machine."""
    return [c for c in result.columns if _presentable(c)]


def presentable_row(row: dict) -> dict:
    """A row carrying only the keys `presentable_columns` describes."""
    return {key: value for key, value in row.items() if _presentable({"key": key})}


def _plottable(column: dict) -> bool:
    # The comparison *date* column is not a dimension: reading it as one splits a 12-month line
    # into twelve one-point series. The comparison *measure* is real data in the same unit as
    # the current period, and putting it on the same axis is the point of `compare_to`.
    key = column.get("key", "")
    return _presentable(column) and not (
        key.endswith("_compare") and column.get("type") != "number")


def _dimensions(result: CachedResult) -> list[dict]:
    # A column holding one distinct value is not something to split by - it is a filter the
    # caller already applied, echoed back on every row.
    return [c for c in result.columns
            if c.get("type") in ("date", "text") and _plottable(c) and _varies(c, result)]


def _varies(column: dict, result: CachedResult) -> bool:
    # Needs at least two rows to mean anything: in a one-row result every column is constant,
    # and that says nothing about whether it is a dimension.
    if len(result.rows) < 2:
        return True
    key = column["key"]
    seen = set()
    for row in result.rows:
        seen.add(row.get(key))
        if len(seen) > 1:
            return True
    return False


def _measures(result: CachedResult) -> list[dict]:
    return [c for c in result.columns if c.get("type") == "number" and _plottable(c)]


_TOOL_TITLE = {"query_market_share": "Marknadsandel", "query_sales": "Försäljning"}


def derive_title(result: CachedResult, dimensions: Sequence[dict]) -> str:
    """A title from the result's own shape, for every card the model gave none.

    The chart-first preview card is built with an empty envelope, so without this every chat
    answer read "Resultat" for the several seconds between the chart landing and the prose
    arriving - and market-share answers, where the prompt tells the model to omit `chart`
    entirely, kept it for good.
    """
    head = _TOOL_TITLE.get((result.meta or {}).get("tool", result.tool), _FALLBACK_TITLE)
    labels = [str(d.get("label", d["key"])).lower() for d in dimensions
              if not str(d["key"]).endswith("_compare")]
    if labels:
        head = f"{head} per {' och '.join(labels[:2])}"
    period = _period_label(_window((result.meta or {}).get("time_range")))
    return f"{head} · {period}" if period else head


def propose_chart(result: CachedResult, title: str | None = None,
                  subtitle: str | None = None) -> ChartSpec:
    """Pick a chart from the result's shape alone."""
    dimensions = _dimensions(result)
    plottable = _measures(result)
    # The current period leads. `_delta_pct` never joins it - a percentage on a kronor axis is
    # the bug the filter was written for - and `_compare` only joins it on a time axis, below.
    measures = [m for m in plottable
                if not m["key"].endswith(("_compare", "_delta", "_delta_pct", "_delta_pe"))]

    title = title or derive_title(result, dimensions)
    if not measures:
        return ChartSpec(type="table", x=None, y=[], title=title, subtitle=subtitle)

    if not dimensions:
        return ChartSpec(type="kpi", x=None, y=[measures[0]["key"]],
                         title=title, subtitle=subtitle)

    first, *rest = dimensions
    if len(dimensions) > 2:
        return ChartSpec(type="table", x=first["key"],
                         y=[m["key"] for m in measures], title=title, subtitle=subtitle)

    if first["type"] == "date":
        # A time series with a second dimension becomes one line per series value. Overlaying
        # the comparison there would double an already-crowded chart, so it stays single.
        if rest:
            return ChartSpec(type="line", x=first["key"], y=[measures[0]["key"]],
                             series=rest[0]["key"], title=title, subtitle=subtitle)
        compare = f"{measures[0]['key']}_compare"
        y = [measures[0]["key"]]
        if any(m["key"] == compare for m in plottable):
            y.append(compare)
        return ChartSpec(type="line", x=first["key"], y=y, title=title, subtitle=subtitle)

    if rest and len(result.rows) > 1:
        # Categorical split by categorical is part-of-whole.
        return ChartSpec(type="stacked_bar", x=first["key"], y=[measures[0]["key"]],
                         series=rest[0]["key"], sort="desc", title=title, subtitle=subtitle)

    return ChartSpec(type="bar", x=first["key"], y=[measures[0]["key"]], sort="desc",
                     limit=result.row_count if result.row_count <= 25 else 25,
                     title=title, subtitle=subtitle)


def validate_chart(spec: ChartSpec, result: CachedResult) -> tuple[ChartSpec, list[str]]:
    """Accept the model's spec only if every column it names is real and typed compatibly."""
    by_key = {c["key"]: c for c in result.columns}
    problems: list[str] = []

    if spec.x is not None and spec.x not in by_key:
        problems.append(f"chart.x '{spec.x}' finns inte i resultatet")

    for key in spec.y:
        column = by_key.get(key)
        if column is None:
            problems.append(f"chart.y '{key}' finns inte i resultatet")
        elif column.get("type") != "number":
            problems.append(f"chart.y '{key}' är inte numerisk och kan inte ligga på värdeaxeln")
        elif not _plottable(column):
            problems.append(f"chart.y '{key}' är ett id eller en flagga, inte ett mätvärde")

    if spec.series is not None and spec.series not in by_key:
        problems.append(f"chart.series '{spec.series}' finns inte i resultatet")

    if spec.type != "kpi" and spec.x is None and _dimensions(result):
        problems.append("chart.x saknas trots att resultatet har en dimension")

    # A result with no dimension column is a single number.
    if not _dimensions(result) and spec.type not in ("kpi", "table"):
        problems.append(f"chart.type '{spec.type}' kräver en dimension att fördela värdena "
                        f"över; resultatet är ett enda tal")

    if problems:
        fallback = propose_chart(result, title=spec.title, subtitle=spec.subtitle)
        return fallback, problems
    # Annotations are the server's to make. A marker the model invented would be an unsourced
    # claim drawn on top of verified rows, which is the one thing this pipeline exists to stop.
    return spec.model_copy(update={"markers": [], "marker_label": None}), []


_MONTH_SHORT = ("jan", "feb", "mar", "apr", "maj", "jun",
                "jul", "aug", "sep", "okt", "nov", "dec")


def _period_label(window: TimeWindow | None) -> str | None:
    """`jul 2024–jun 2025`. What the comparison series is, rather than what the column is called."""
    if window is None:
        return None
    try:
        start, end = date.fromisoformat(window.from_), date.fromisoformat(window.to)
    except ValueError:
        return None
    tail = f"{_MONTH_SHORT[end.month - 1]} {end.year}"
    if (start.year, start.month) == (end.year, end.month):
        # A whole calendar month is named; a few days inside one are not. Collapsing a 7-day
        # comparison to "jun 2026" gave both series of a day-grain chart the same legend label,
        # and a 7-day window always sits inside one month.
        if start.day == 1 and end.day == monthrange(end.year, end.month)[1]:
            return tail
        return f"{start.day}–{end.day} {tail}"
    return f"{_MONTH_SHORT[start.month - 1]} {start.year}–{tail}"


def to_columns(result: CachedResult) -> list[Column]:
    """What the card's table view renders - the answer's columns, not the tool's."""
    # "(jämförelse)" says a comparison exists; the legend has to say which one. Only the
    # measure gets renamed - the comparison's date column already reads as a date.
    period = _period_label(_window((result.meta or {}).get("compare_range")))
    return [Column(key=c["key"], type=c.get("type", "text"),
                   label=_label(c, period), unit=c.get("unit"))
            for c in presentable_columns(result)]


def _label(column: dict, period: str | None) -> str:
    label = column.get("label", column["key"])
    if period and column.get("type") == "number" and column["key"].endswith("_compare"):
        return label.replace("(jämförelse)", f"({period})")
    return label


def _window(raw: Any) -> TimeWindow | None:
    if not isinstance(raw, dict):
        return None
    start, end = raw.get("from"), raw.get("to")
    if not start or not end:
        return None
    return TimeWindow(**{"from": str(start), "to": str(end)})


def build_provenance(result: CachedResult) -> Provenance | None:
    """The source chip. Built from the tool's own meta so it cannot drift from what ran."""
    meta = result.meta or {}
    time_range = _window(meta.get("time_range"))
    coverage = _window(meta.get("coverage")) or time_range
    if time_range is None or coverage is None:
        return None

    return Provenance(
        tool=meta.get("tool", result.tool),
        source=meta.get("source", "okänd"),
        scope=meta.get("scope", "okänt"),
        time_range=time_range,
        compare_range=_window(meta.get("compare_range")),
        coverage=coverage,
        filters_applied=meta.get("filters_applied") or {},
        row_count=result.row_count,
        truncated=bool(result.truncated),
        executed_at=meta.get("executed_at", ""),
        tool_args=result.tool_args or {},
    )


def build_sources(results: Sequence[CachedResult],
                  primary: CachedResult | None) -> list[ToolCallRecord]:
    """Provenance for every result the turn produced, the chart's first."""
    ordered: list[CachedResult] = []
    for result in ([primary] if primary is not None else []) + list(results):
        if result is not None and all(seen.query_id != result.query_id for seen in ordered):
            ordered.append(result)
    records = []
    for result in ordered:
        provenance = build_provenance(result)
        if provenance is not None:
            records.append(ToolCallRecord(
                query_id=result.query_id, tool=result.tool,
                provenance=provenance, row_count=result.row_count))
    return records


def build_card(*, result: CachedResult | None, narrative: str, envelope: dict[str, Any],
               status: str = "ok", produced: Sequence[CachedResult] = (),
               attributions: Sequence[Attribution] = (),
               unresolved: Sequence[str] = ()) -> AnswerCard:
    """Assemble the card."""
    caveats = [scrub_names(strip_markdown(str(c)), unresolved)
               for c in (envelope.get("caveats") or [])]
    narrative = scrub_names(narrative, unresolved)
    claims = [Claim(literal=a.literal, query_id=a.query_id) for a in attributions]

    if result is None:
        # clarify / cannot_answer paths: no data was returned, so there is nothing to chart and
        # nothing to prove - only the explanation and what to try instead. An "ok" here would be
        # an answer given from memory, so it is downgraded. "explain" is exempt: it answers a
        # question about the card, needs no query by definition, and any figure it states is
        # caught by the numeric check running against an empty result set.
        if status == "ok":
            status = "cannot_answer"
        # A suppressed narrative is suppressed here too. Without this the chartless path was a
        # way for unverified prose to reach the card with an amber banner over it and nothing
        # else changed.
        failed = status == "validation_failed"
        return AnswerCard(
            status=cast(CardStatus, status), narrative="" if failed else narrative,
            insights=([] if failed
                      else [scrub_names(strip_markdown(str(i)), unresolved)
                            for i in (envelope.get("insights") or [])]),
            caveats=caveats,
            sources=build_sources(produced, None),
            claims=claims,
            suggestions=[strip_markdown(str(s)) for s in (envelope.get("suggestions") or [])],
        )

    proposed = propose_chart(result, title=_title(envelope), subtitle=_subtitle(envelope))
    chart = proposed
    if isinstance(envelope.get("chart"), dict):
        try:
            override = ChartSpec.model_validate(envelope["chart"])
        except Exception as exc:  # noqa: BLE001 - a bad spec must not lose a good answer
            logger.info("", extra={"event": "chart.override", "reason": "schema",
                                   "problems": [str(exc)[:300]], "chart_type": chart.type})
            caveats.append(_override_caveat(chart))
        else:
            chart, problems = validate_chart(override, result)
            if problems:
                # `problems` is validator vocabulary - column keys, axis rules. It belongs in
                # the log, where someone can act on it, not on a retailer's card.
                logger.info("", extra={"event": "chart.override", "reason": "invalid",
                                       "problems": problems, "proposed_type": override.type,
                                       "chart_type": chart.type})
                caveats.append(_override_caveat(chart))

    # No caveat for `validation_failed`: the card renders that sentence from the status itself,
    # in the amber notice at the top. Adding it here printed it twice, verbatim.

    return AnswerCard(
        status=cast(CardStatus, status),
        narrative="" if status == "validation_failed" else narrative,
        insights=([] if status == "validation_failed"
                  else [scrub_names(strip_markdown(str(i)), unresolved)
                        for i in (envelope.get("insights") or [])]),
        caveats=caveats,
        chart=chart,
        query_id=result.query_id,
        columns=to_columns(result),
        provenance=build_provenance(result),
        sources=build_sources(produced, result),
        # A suppressed narrative has no claims left to attribute.
        claims=[] if status == "validation_failed" else claims,
        suggestions=[strip_markdown(str(s)) for s in (envelope.get("suggestions") or [])],
    )


_CHART_WORD = {"line": "linjediagram", "bar": "stapeldiagram",
               "stacked_bar": "staplat stapeldiagram", "area": "ytdiagram",
               "pie": "cirkeldiagram", "table": "tabell"}


def _override_caveat(chart: ChartSpec) -> str:
    """What the user is told when the server picked the chart instead of the model."""
    if chart.type == "kpi":
        return "Resultatet är ett enda tal - den föreslagna vyn passade inte datan."
    word = _CHART_WORD.get(chart.type, "diagram")
    return f"Visar som {word} - den föreslagna vyn passade inte datan."


def _title(envelope: dict[str, Any]) -> str | None:
    chart = envelope.get("chart")
    if isinstance(chart, dict) and chart.get("title"):
        # Through `strip_markdown` like every other piece of model text: a title is the most
        # visible line on the card, and an em dash in it is the one nobody misses.
        return strip_markdown(str(chart["title"]))
    return None


def _subtitle(envelope: dict[str, Any]) -> str | None:
    chart = envelope.get("chart")
    if isinstance(chart, dict) and chart.get("subtitle"):
        return strip_markdown(str(chart["subtitle"]))
    return None
