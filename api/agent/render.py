"""Turn a tool result plus the model's envelope into an AnswerCard.

Two jobs, and the order matters: the chart type is proposed **deterministically from the
shape of the result** first, and the model may only override it. That keeps every chart in
the product consistent even when the model is careless — which matters more for how the
product feels than model freedom does (§8).

The second job is validating the override. A ChartSpec that references a column which does
not exist in the result, or puts a text column on a numeric axis, is rejected and replaced by
the deterministic proposal rather than shipped to the frontend to fail there.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ..models import AnswerCard, ChartSpec, Column, Provenance, TimeWindow
from ..result_cache import CachedResult

# The model is told to end with exactly one ```json block. Match the LAST one: if it wrote an
# illustrative block earlier in its prose, the final one is the real answer.
_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)

_FALLBACK_TITLE = "Resultat"


def split_answer(text: str) -> tuple[str, dict[str, Any]]:
    """Separate the Swedish prose from the JSON envelope.

    A missing or malformed block is not fatal — the prose is still the answer and the server
    can pick the chart itself. Failing the whole turn because a code fence was mangled would
    trade a good answer for no answer.
    """
    blocks = list(_JSON_BLOCK.finditer(text))
    if not blocks:
        return text.strip(), {}

    last = blocks[-1]
    narrative = (text[: last.start()] + text[last.end():]).strip()
    try:
        envelope = json.loads(last.group(1))
    except json.JSONDecodeError:
        return narrative, {}
    return narrative, envelope if isinstance(envelope, dict) else {}


# Columns the tools carry for policy and joining, which are not part of the answer.
# `suppressed` is a boolean the k-anonymity guard sets — `_infer_columns` types it as text,
# which made it look like a third dimension and pushed every market-share result onto the
# `table` branch. An `_id` is an identifier, never a quantity.
_INTERNAL_COLUMNS = frozenset({"suppressed", "truncated"})


def _presentable(column: dict) -> bool:
    """Belongs in anything a user reads: the table view, the CSV, the card's columns.

    The distinction from `_plottable` is `_compare`: a comparison figure is real data and a
    reader may well want it in a spreadsheet, it just cannot share an axis with the current
    period. Everything excluded here is internal bookkeeping in English, and shipping it
    turned an export into something a supplier could not hand to a colleague.
    """
    key = column.get("key", "")
    return key not in _INTERNAL_COLUMNS and not key.endswith("_id")


def presentable_columns(result: CachedResult) -> list[dict]:
    """The result's columns, minus the ones that exist for the machine."""
    return [c for c in result.columns if _presentable(c)]


def presentable_row(row: dict) -> dict:
    """A row carrying only the keys `presentable_columns` describes.

    An endpoint should not ship what it does not describe: leaving `product_id` in the JSON
    while omitting it from `columns` would keep the identifier on the wire and merely hide
    it from the table.
    """
    return {key: value for key, value in row.items() if _presentable({"key": key})}


def _plottable(column: dict) -> bool:
    # `_compare` covers the comparison period's own date column as well as its measures.
    # It labels the prior period rather than splitting the current one, so treating it as
    # a dimension would turn a 12-month year-on-year line into twelve one-point series.
    return _presentable(column) and not column.get("key", "").endswith("_compare")


def _dimensions(result: CachedResult) -> list[dict]:
    # A column holding one distinct value is not something to split by — it is a filter the
    # caller already applied, echoed back on every row. query_market_share returns exactly
    # that shape: `subcategory` is constant ("TV" on every row) while `brand` varies, and
    # treating both as dimensions routed a plain share comparison to `stacked_bar` with a
    # single stack. Judging by the data rather than the schema also collapses a one-row
    # result to `kpi`, which is what a single number should look like.
    return [c for c in result.columns
            if c.get("type") in ("date", "text") and _plottable(c) and _varies(c, result)]


def _varies(column: dict, result: CachedResult) -> bool:
    # Needs at least two rows to mean anything: in a one-row result every column is constant,
    # and that says nothing about whether it is a dimension. A single-row grouped query is a
    # legitimate one-bar chart, so the schema decides there.
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


def propose_chart(result: CachedResult, title: str | None = None,
                  subtitle: str | None = None) -> ChartSpec:
    """Pick a chart from the result's shape alone."""
    dimensions = _dimensions(result)
    # Comparison columns are derived, not independent series — charting net_sales_sek and
    # net_sales_sek_delta_pct on one axis would put a percentage next to kronor.
    measures = [m for m in _measures(result)
                if not m["key"].endswith(("_compare", "_delta_pct"))]

    title = title or _FALLBACK_TITLE
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
        # A time series with a second dimension becomes one line per series value.
        return ChartSpec(type="line", x=first["key"], y=[measures[0]["key"]],
                         series=rest[0]["key"] if rest else None,
                         title=title, subtitle=subtitle)

    if rest and len(result.rows) > 1:
        # Categorical split by categorical is part-of-whole. Stacked bar rather than pie:
        # a pie with more than a handful of slices is unreadable, and these routinely have
        # twenty-one (one per län). A single row cannot be stacked against anything, so it
        # falls through to the plain bar below — query_market_share for one brand lands here.
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

    # A result with no dimension column is a single number. `kpi` shows it and `table` prints
    # it; every other type needs a category or a time axis to lay values out along, and asking
    # for one anyway yields a chart with a single bar floating on an empty axis. Models pick
    # `bar` here fairly often — it is the default shape of "show me a chart" — so the server
    # declines rather than rendering something that looks broken.
    if not _dimensions(result) and spec.type not in ("kpi", "table"):
        problems.append(f"chart.type '{spec.type}' kräver en dimension att fördela värdena "
                        f"över; resultatet är ett enda tal")

    if problems:
        fallback = propose_chart(result, title=spec.title, subtitle=spec.subtitle)
        return fallback, problems
    return spec, []


def to_columns(result: CachedResult) -> list[Column]:
    """What the card's table view renders — the answer's columns, not the tool's."""
    return [Column(key=c["key"], type=c.get("type", "text"),
                   label=c.get("label", c["key"]), unit=c.get("unit"))
            for c in presentable_columns(result)]


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


def build_card(*, result: CachedResult | None, narrative: str, envelope: dict[str, Any],
               status: str = "ok") -> AnswerCard:
    """Assemble the card. `caveats` accumulates anything we had to correct."""
    caveats = [str(c) for c in (envelope.get("caveats") or [])]

    if result is None:
        # clarify / cannot_answer paths: no data was returned, so there is nothing to chart
        # and nothing to prove — only the explanation and what to try instead.
        #
        # `ok` means "besvarad från verktygsdata" (prompts.py). With no result there is no
        # tool data, so `ok` here is a contradiction rather than a judgement call, and it is
        # one models reach for whenever they decline politely — a refusal phrased helpfully
        # still reads to them as a job done. Left alone it reaches the client as an ordinary
        # answer, because status is what the UI styles the card on. Correcting it in code
        # rather than in the prompt is the same choice made for rule 1 and rule 6: the prompt
        # states the contract, the server keeps it.
        if status == "ok":
            status = "cannot_answer"
        return AnswerCard(
            status=status, narrative=narrative,
            insights=[str(i) for i in (envelope.get("insights") or [])],
            caveats=caveats,
            suggestions=[str(s) for s in (envelope.get("suggestions") or [])],
        )

    proposed = propose_chart(result, title=_title(envelope), subtitle=_subtitle(envelope))
    chart = proposed
    if isinstance(envelope.get("chart"), dict):
        try:
            override = ChartSpec.model_validate(envelope["chart"])
        except Exception:  # noqa: BLE001 — a bad spec must not lose a good answer
            caveats.append("Diagramförslaget från modellen var ogiltigt; "
                           "servern valde diagramtyp utifrån resultatets form.")
        else:
            chart, problems = validate_chart(override, result)
            if problems:
                caveats.append("Diagramförslaget avvisades (" + "; ".join(problems)
                               + "); servern valde utifrån resultatets form istället.")

    if status == "validation_failed":
        caveats.insert(0, "Svarstexten kunde inte verifieras mot datan och har därför "
                          "utelämnats. Diagrammet nedan kommer direkt från databasen.")

    return AnswerCard(
        status=status,
        narrative="" if status == "validation_failed" else narrative,
        insights=([] if status == "validation_failed"
                  else [str(i) for i in (envelope.get("insights") or [])]),
        caveats=caveats,
        chart=chart,
        query_id=result.query_id,
        columns=to_columns(result),
        provenance=build_provenance(result),
        suggestions=[str(s) for s in (envelope.get("suggestions") or [])],
    )


def _title(envelope: dict[str, Any]) -> str | None:
    chart = envelope.get("chart")
    if isinstance(chart, dict) and chart.get("title"):
        return str(chart["title"])
    return None


def _subtitle(envelope: dict[str, Any]) -> str | None:
    chart = envelope.get("chart")
    if isinstance(chart, dict) and chart.get("subtitle"):
        return str(chart["subtitle"])
    return None
