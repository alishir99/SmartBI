"""Turning one observed answer into a verdict — the whole of the eval's judgement.

The driver is deliberately stupid: it speaks HTTP, collects what came back and hands it
here. Everything that decides *whether the system was right* lives in this file, and it is
pure — no sockets, no files, no clock. That is what makes a hand-written `Observed` a
complete test fixture, and it is why a broken expectation shows up as a failing unit test
rather than as a mysterious red line in a live run.

Three decisions worth understanding before changing anything here.

**Where a check reads from is the assertion.** `series`, `top_n`, `rank`, `n_brands` and
`suppressed` are graded against the rows fetched from `GET /api/result/{query_id}` — the
cached result set the chart is drawn from. Grading those against the narrative would test
the model's transcription, not the architecture; the claim under test is that the values
on screen never passed through the language model, so the eval must look where the screen
looks. `numeric`, `delta_pct`, `must_contain`, `must_not_contain` and
`must_not_contain_numbers` are claims *about prose*, so those read the narrative.

**Number extraction is imported, not re-implemented.** `api/agent/validate.py` already
parses sv-SE money and quantity literals out of Swedish prose, with the mask list for
dates, ISO weeks, quarters and rank chips that took real effort to get right. A second,
subtly different regex here would mean the eval and the runtime disagree about what counts
as a number — the eval would then be measuring its own parser. The import costs a
`sys.path` line (below); `api.agent.validate` pulls in only `api.result_cache`, which is
stdlib-only, so no FastAPI and no database driver is loaded by importing it.

**Every failure names itself.** A `Failure` carries the expects key that produced it, so
the summary can count failures by category and a reader of stdout alone can tell a 2 %
numeric drift from a leaked competitor figure without opening the YAML.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    # eval/ is not a package and is run as a script, so the repo root is not on the path.
    sys.path.insert(0, str(_REPO_ROOT))

from api.agent.validate import NumberLiteral, extract_numbers  # noqa: E402

# Every key this module knows how to grade. run_eval.py checks this against
# cases.GOLDEN_EXPECT_KEYS | cases.ADVERSARIAL_EXPECT_KEYS before running anything: a key in
# the suite vocabulary but not in here would be an assertion that silently always passes,
# which is the one failure mode the eval exists to prevent.
GRADED_KEYS = frozenset({
    "numeric", "delta_pct", "series", "top_n", "rank", "n_brands",
    "tools_called", "tools_not_called", "dimensions", "chart_type",
    "must_contain", "must_not_contain", "must_not_contain_numbers",
    "caveats_min", "suggestions_min", "suppressed", "status", "language",
})

# Which family each check belongs to, and the reason this file's central observation is
# worth acting on rather than just documenting.
#
# The header already says it: `series`, `top_n`, `rank`, `n_brands` and `suppressed` are
# graded against the ROWS the chart is drawn from, while `numeric`, `must_contain` and the
# rest are graded against the PROSE. Those measure two different systems. The first measures
# the grounding architecture — whether the right query ran and the right rows came back. The
# second measures the language model — whether it transcribed them honestly.
#
# The conjunctive score collapses both into one boolean per case, so "picked a bar chart
# where a line was expected" scores exactly the same as "reported a fabricated total", and
# the one number the project most wants to state ends up computed and then discarded. Split
# apart, the report can say: grounded checks pass at X %, prose checks at Y %. The gap is
# the model. The floor is the architecture.
#
# `transport` is its own family for a related reason. A rate limit or a dropped connection
# is an infrastructure event, and scoring it as a wrong answer inflates the reported
# non-determinism with something the model never did.
CHECK_FAMILIES: dict[str, str] = {
    # graded against rows from the result cache — the architecture
    "series": "grounded", "top_n": "grounded", "rank": "grounded",
    "n_brands": "grounded", "suppressed": "grounded",
    # graded against the narrative — the model
    "numeric": "prose", "delta_pct": "prose", "must_contain": "prose",
    "must_not_contain": "prose", "must_not_contain_numbers": "prose",
    "language": "prose",
    # graded against what the agent chose to do — planning, not values
    "tools_called": "routing", "tools_not_called": "routing", "dimensions": "routing",
    "chart_type": "routing", "status": "routing", "caveats_min": "routing",
    "suggestions_min": "routing",
    # not a check at all: the turn never got far enough to be judged
    "transport": "transport", "error_event": "transport",
}

FAMILIES = ("grounded", "prose", "routing", "transport")


def family_of(check: str) -> str:
    """An unrecognised check is reported under `routing` rather than dropped — a check
    missing from the table must not vanish from the totals."""
    return CHECK_FAMILIES.get(check, "routing")


# A bare integer at or below this, carrying no unit at all, is not a money or quantity
# claim. It is a count of rows, a rank, a brand count or a policy threshold — the
# suppression text the market-share tool emits literally reads "minst 5 varumärken och 100
# köp", and a model that quotes that reason back is behaving correctly. The widening is free
# in this dataset: the smallest figure any tool can return for this tenant is a five-digit
# monthly total, so no genuine leak hides under 100. Anything carrying a unit ("100 st",
# "50 kr") stays forbidden regardless of magnitude, and so does any literal with decimals.
FORBIDDEN_MAX_BARE_INTEGER = 100

# Bare integers in this range are read as years, matching validate.py's own allowance.
_YEAR_MIN, _YEAR_MAX = 1990, 2099

# Enough Swedish to tell "the model answered in Swedish" from "the model answered in
# English". Not a language classifier — a smoke test, and deliberately cheap.
_SWEDISH_MARKERS = re.compile(
    r"[åäöÅÄÖ]|\b(och|för|är|vi|på|med|av|inte|kan|det|som|har|under|mot|jämfört)\b",
    re.I,
)

# A period label that is a date or a truncated date. `year` is truncated to 2024-01-01 in
# the semantic layer but written "2024" in the YAML, so the two must compare equal.
_DATEISH = re.compile(r"\d{4}(?:-\d{2}){0,2}$")

# Words that carry the sign of a change. Swedish prose puts the direction in the verb
# ("minskade med 5,8 %"), so a negative delta_pct is only satisfied by an unsigned literal
# when the sentence around it actually says the number went down.
_DECLINE_WORDS = re.compile(
    r"minsk|sjönk|sjunk|lägre|nedgång|ned\b|tapp|backa|svagare|färre|negativ|"
    r"sämre|föll|fall\b|-\s?\d",
    re.I,
)


# --------------------------------------------------------------------------- structures

@dataclass(frozen=True)
class Failure:
    """One named, self-explaining reason a case did not pass."""

    check: str
    message: str

    def __str__(self) -> str:
        return f"{self.check}: {self.message}"


@dataclass
class Observed:
    """Everything the transport collected for one case. The only input grading needs.

    `card` and `tool_calls` are kept in their wire shapes rather than parsed into models, so
    a test can paste a real SSE payload straight into a fixture and so a contract change
    shows up as a grading failure instead of a pydantic error inside the eval.
    """

    card: dict[str, Any] | None = None
    #: The `tool_call` SSE events, in order: {"tool": str, "args": dict}.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    #: Rows from GET /api/result/{query_id} — the grounded values, not the narrative's.
    rows: list[dict[str, Any]] = field(default_factory=list)
    columns: list[dict[str, Any]] = field(default_factory=list)
    #: An `error` SSE event, a transport failure or a timeout. Not the same as a refusal.
    error: str | None = None
    latency_ms: int = 0

    @property
    def narrative(self) -> str:
        return str((self.card or {}).get("narrative") or "")

    @property
    def status(self) -> str | None:
        return (self.card or {}).get("status")

    @property
    def query_id(self) -> str | None:
        return (self.card or {}).get("query_id")

    @property
    def tools(self) -> list[str]:
        return [str(call.get("tool")) for call in self.tool_calls]

    def card_text(self) -> str:
        """Narrative, insights, caveats, suggestions and chart titles as one blob.

        Used for substring assertions only. A competitor name leaked into a caveat or a
        suggestion is exactly as bad as one in the narrative, and a coverage statement the
        case requires ("2024", "2026") legitimately lands in a caveat rather than the
        narrative — so both directions argue for reading the whole card.
        """
        card = self.card or {}
        chart = card.get("chart") or {}
        parts = [str(card.get("narrative") or "")]
        for key in ("insights", "caveats", "suggestions"):
            parts += [str(item) for item in (card.get(key) or [])]
        parts += [str(chart.get("title") or ""), str(chart.get("subtitle") or "")]
        return "\n".join(part for part in parts if part)

    def effective_columns(self) -> list[dict[str, Any]]:
        """Column specs, inferred from the rows when the endpoint returned none."""
        if self.columns:
            return self.columns
        inferred: list[dict[str, Any]] = []
        for key in (self.rows[0] if self.rows else {}):
            sample = next((row[key] for row in self.rows if row.get(key) is not None), None)
            kind = "number" if _is_number(sample) else "text"
            inferred.append({"key": key, "type": kind, "label": key})
        return inferred


@dataclass
class CaseResult:
    case_id: str
    suite: str
    question: str
    failures: list[Failure] = field(default_factory=list)
    latency_ms: int = 0
    status: str | None = None
    query_id: str | None = None
    tools_called: list[str] = field(default_factory=list)
    row_count: int = 0
    category: str | None = None
    # Which checks this case actually ran. Failures alone cannot give a pass *rate*: a
    # family with no failures is indistinguishable from a family that was never asserted,
    # and the second must not be reported as 100 %.
    checks_run: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.failures

    def family_tally(self) -> dict[str, tuple[int, int]]:
        """{family: (passed_checks, total_checks)} for this one case."""
        failed = {failure.check for failure in self.failures}
        tally: dict[str, list[int]] = {name: [0, 0] for name in FAMILIES}
        for check in self.checks_run:
            entry = tally[family_of(check)]
            entry[1] += 1
            entry[0] += check not in failed
        # A transport failure is never in `checks_run` — nothing was asserted, the turn
        # simply did not arrive — so it is counted here rather than being lost.
        for check in failed - set(self.checks_run):
            tally[family_of(check)][1] += 1
        return {name: (ok, total) for name, (ok, total) in tally.items() if total}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.case_id,
            "suite": self.suite,
            "category": self.category,
            "question": self.question,
            "passed": self.passed,
            "status": self.status,
            "query_id": self.query_id,
            "tools_called": self.tools_called,
            "row_count": self.row_count,
            "latency_ms": self.latency_ms,
            "checks_run": self.checks_run,
            "families": {name: {"passed": ok, "total": total}
                         for name, (ok, total) in self.family_tally().items()},
            "failures": [{"check": f.check, "family": family_of(f.check),
                          "message": f.message} for f in self.failures],
        }


# ------------------------------------------------------------------------------ entry

def grade(case: dict, observed: Observed, suite: str) -> CaseResult:
    """Grade one case. Pure: same inputs, same verdict, no I/O."""
    result = CaseResult(
        case_id=str(case.get("id")),
        suite=suite,
        question=str(case.get("question") or "").strip(),
        latency_ms=observed.latency_ms,
        status=observed.status,
        query_id=observed.query_id,
        tools_called=observed.tools,
        row_count=len(observed.rows),
        category=case.get("category"),
    )

    if observed.card is None:
        # No card is never a correct outcome, not even for the adversarial suite: a refusal
        # is a card with status cannot_answer, and a crash is something else entirely.
        reason = observed.error or "the stream ended without a card event"
        result.failures.append(Failure("transport", reason))
        return result

    if observed.error:
        # A card *and* an error means the turn partially failed. Worth its own line, and the
        # remaining checks still run so the report shows what else went wrong.
        result.failures.append(Failure("error_event", observed.error))

    expects = case.get("expects") or {}
    for key in sorted(expects):
        result.checks_run.append(key)
        result.failures += _grade_one(key, expects[key], observed)
    return result


def family_rates(results: list[CaseResult]) -> dict[str, tuple[int, int]]:
    """{family: (passed_checks, total_checks)} across a run.

    The resolution the conjunctive score throws away. Counted per *check*, not per case,
    because that is the unit that means something: a case asserting six things and failing
    one is not the same evidence as a case asserting one thing and failing it.
    """
    totals: dict[str, list[int]] = {name: [0, 0] for name in FAMILIES}
    for result in results:
        for name, (ok, total) in result.family_tally().items():
            totals[name][0] += ok
            totals[name][1] += total
    return {name: (ok, total) for name, (ok, total) in totals.items() if total}


def _grade_one(key: str, expected: Any, observed: Observed) -> list[Failure]:
    match key:
        case "status":
            return _grade_status(expected, observed)
        case "language":
            return _grade_language(expected, observed)
        case "numeric":
            return _grade_numeric("numeric", expected, observed)
        case "delta_pct":
            return _grade_delta_pct(expected, observed)
        case "series":
            return _grade_series(expected, observed)
        case "top_n":
            return _grade_top_n(expected, observed)
        case "rank" | "n_brands":
            return _grade_row_field(key, expected, observed)
        case "suppressed":
            return _grade_suppressed(bool(expected), observed)
        case "tools_called":
            return _grade_tools_called(expected, observed)
        case "tools_not_called":
            return _grade_tools_not_called(expected, observed)
        case "dimensions":
            return _grade_dimensions(expected, observed)
        case "chart_type":
            return _grade_chart_type(expected, observed)
        case "must_contain":
            return _grade_must_contain(expected, observed)
        case "must_not_contain":
            return _grade_must_not_contain(expected, observed)
        case "must_not_contain_numbers":
            return _grade_no_numbers(bool(expected), observed)
        case "caveats_min":
            return _grade_min_list("caveats", expected, observed)
        case "suggestions_min":
            return _grade_min_list("suggestions", expected, observed)
        case _:
            # Unreachable while GRADED_KEYS covers the suite vocabulary, and loud rather
            # than silent if it ever stops doing so.
            return [Failure("expects", f"no grader implemented for expects key {key!r}")]


# ------------------------------------------------------------------------ card shape

def _grade_status(expected: Any, observed: Observed) -> list[Failure]:
    allowed = expected if isinstance(expected, list) else [expected]
    if observed.status in allowed:
        return []
    return [Failure("status", f"expected one of {allowed}, card said {observed.status!r}")]


def _grade_language(expected: Any, observed: Observed) -> list[Failure]:
    if expected != "sv":
        return [Failure("language", f"only 'sv' is supported, case asked for {expected!r}")]
    text = observed.narrative.strip()
    if not text:
        return [Failure("language", "narrative is empty, so no answer was given in any "
                                    "language")]
    if _SWEDISH_MARKERS.search(text):
        return []
    return [Failure("language", f"narrative carries no Swedish marker word or letter: "
                                f"{_excerpt(text)}")]


def _grade_chart_type(expected: Any, observed: Observed) -> list[Failure]:
    allowed = expected if isinstance(expected, list) else [expected]
    chart = (observed.card or {}).get("chart")
    if not chart:
        return [Failure("chart_type", f"expected one of {allowed}, card carries no chart")]
    actual = chart.get("type")
    if actual in allowed:
        return []
    return [Failure("chart_type", f"expected one of {allowed}, chart was {actual!r}")]


def _grade_min_list(field_name: str, minimum: Any, observed: Observed) -> list[Failure]:
    items = (observed.card or {}).get(field_name) or []
    check = f"{field_name}_min"
    if len(items) >= int(minimum):
        return []
    return [Failure(check, f"expected at least {minimum} {field_name}, card had "
                           f"{len(items)}")]


# ----------------------------------------------------------------------------- tools

def _grade_tools_called(expected: Any, observed: Observed) -> list[Failure]:
    called = set(observed.tools)
    missing = [tool for tool in expected if tool not in called]
    if not missing:
        return []
    return [Failure("tools_called", f"{missing} never ran; the turn called "
                                    f"{sorted(called) or 'no tools at all'}")]


def _grade_tools_not_called(expected: Any, observed: Observed) -> list[Failure]:
    called = set(observed.tools)
    forbidden = [tool for tool in expected if tool in called]
    if not forbidden:
        return []
    return [Failure("tools_not_called", f"{forbidden} ran but must not have")]


def _grade_dimensions(expected: Any, observed: Observed) -> list[Failure]:
    """The expected `dimensions` argument on a query_sales call.

    Any matching call passes: the agent is allowed to probe with a second query, and the
    assertion is that it asked for *this* grouping at least once, not that it asked once.
    """
    wanted = set(expected or [])
    seen: list[list[str]] = []
    for call in observed.tool_calls:
        if call.get("tool") != "query_sales":
            continue
        dimensions = list((call.get("args") or {}).get("dimensions") or [])
        seen.append(dimensions)
        if set(dimensions) == wanted:
            return []
    if not seen:
        return [Failure("dimensions", f"expected a query_sales grouped by "
                                      f"{sorted(wanted) or '[] (no grouping)'}, but "
                                      f"query_sales never ran")]
    return [Failure("dimensions", f"expected a query_sales grouped by "
                                  f"{sorted(wanted) or '[] (no grouping)'}; calls used "
                                  f"{seen}")]


# ------------------------------------------------------------------- grounded values

def _grade_series(spec: Any, observed: Observed) -> list[Failure]:
    if not isinstance(spec, dict):
        return [Failure("series", f"malformed expectation {spec!r}")]
    points: dict[str, Any] = spec.get("points") or {}
    tolerance = float(spec.get("tolerance_pct", 0.5))
    group_by = spec.get("group_by")

    if not observed.rows:
        return [Failure("series", f"no result rows to check against "
                                  f"(query_id={observed.query_id!r}) — the values were "
                                  f"never grounded")]

    columns = observed.effective_columns()
    label_key = _label_key(columns, group_by)
    if label_key is None:
        return [Failure("series", f"no label column for group_by {group_by!r}; result "
                                  f"columns were {[c.get('key') for c in columns]}")]

    numeric_keys = [c["key"] for c in columns if c.get("type") == "number"]
    if not numeric_keys:
        return [Failure("series", f"result has no numeric column to read values from "
                                  f"(columns {[c.get('key') for c in columns]})")]

    # Which column holds the measure is not stated in the YAML, and cannot be: a comparison
    # query returns three numeric columns and market share returns six. So every numeric
    # column is tried, and a column counts only if it satisfies *every* point. For a
    # multi-point series an accidental match across all points is not a realistic risk, and
    # for a single-point one the tolerance is tight enough that it stays unlikely.
    best: tuple[int, str, list[str], list[tuple[str, float, float]]] | None = None
    for value_key in numeric_keys:
        missing: list[str] = []
        wrong: list[tuple[str, float, float]] = []
        for label, expected in points.items():
            actual = _point_value(observed.rows, label_key, label, value_key)
            if actual is None:
                missing.append(str(label))
            elif not _close(actual, float(expected), tolerance):
                wrong.append((str(label), float(expected), actual))
        if not missing and not wrong:
            return []
        score = len(points) - len(missing) - len(wrong)
        if best is None or score > best[0]:
            best = (score, value_key, missing, wrong)

    assert best is not None
    _, value_key, missing, wrong = best
    details = []
    if wrong:
        details.append("; ".join(
            f"{label} expected {_fmt(expected)} +/-{tolerance}%, rows had {_fmt(actual)}"
            for label, expected, actual in wrong[:4]))
    if missing:
        details.append(f"labels absent from the rows: {missing[:6]}")
    return [Failure("series", f"grouped by {label_key!r}, closest numeric column "
                              f"{value_key!r}: " + " | ".join(details))]


def _grade_top_n(spec: Any, observed: Observed) -> list[Failure]:
    if not isinstance(spec, dict):
        return [Failure("top_n", f"malformed expectation {spec!r}")]
    order = [str(label) for label in (spec.get("order") or [])]
    prefix_only = bool(spec.get("prefix_only"))
    group_by = spec.get("group_by")

    if not observed.rows:
        return [Failure("top_n", f"no result rows to check ordering against "
                                 f"(query_id={observed.query_id!r})")]

    columns = observed.effective_columns()
    label_key = _label_key(columns, group_by)
    if label_key is None:
        return [Failure("top_n", f"no label column for group_by {group_by!r}; result "
                                 f"columns were {[c.get('key') for c in columns]}")]

    # Row order is the tool's ORDER BY, preserved through the cache and /api/result. That
    # ordering is the assertion; nothing here re-sorts.
    actual = [str(row.get(label_key)) for row in observed.rows]

    if len(actual) < len(order):
        return [Failure("top_n", f"expected at least {len(order)} rows, result had "
                                 f"{len(actual)}: {actual}")]
    if not prefix_only and len(actual) != len(order):
        return [Failure("top_n", f"expected exactly {order}, result had {len(actual)} "
                                 f"rows: {actual}")]

    head = actual[:len(order)]
    if all(_same_label(expected, seen) for expected, seen in zip(order, head, strict=True)):
        return []
    where = "first rows" if prefix_only else "rows"
    return [Failure("top_n", f"expected {order} as the {where} grouped by {label_key!r}, "
                             f"result had {head}")]


def _grade_row_field(key: str, expected: Any, observed: Observed) -> list[Failure]:
    """`rank` and `n_brands`, read off the market-share rows rather than the prose.

    query_market_share returns one row per own brand in the slice, so a tenant with two
    brands in the same subcategory produces two rows with different ranks. The assertion is
    therefore "some row carries this value", which is what the YAML means when it writes
    `rank: 1` for a question about a single brand.
    """
    if not observed.rows:
        return [Failure(key, f"no result rows to read {key} from "
                             f"(query_id={observed.query_id!r})")]
    values = [row[key] for row in observed.rows if _is_number(row.get(key))]
    if not values:
        return [Failure(key, f"no result row carries a {key!r} field; row keys were "
                             f"{sorted(observed.rows[0])}")]
    if any(float(value) == float(expected) for value in values):
        return []
    return [Failure(key, f"expected {expected}, rows carried {values}")]


def _grade_suppressed(expected: bool, observed: Observed) -> list[Failure]:
    flagged = [row for row in observed.rows if "suppressed" in row]
    any_suppressed = any(bool(row.get("suppressed")) for row in flagged)

    if not expected:
        if any_suppressed:
            return [Failure("suppressed", "a result row was suppressed but the case "
                                          "expects an answerable slice")]
        return []

    if any_suppressed:
        return []

    # The thin-slice cases allow status ok *or* a refusal, and their comments say either a
    # suppressed row or a clean cannot_answer is correct. When the agent refuses without
    # reaching the tool there is no row to carry the flag, and requiring one would fail the
    # very behaviour the case calls correct. So a refusal satisfies this — but only a
    # refusal: a status of 'ok' means an answer was given, and then the suppression flag is
    # the only thing standing between the user and a k-anonymity leak.
    if observed.status in ("cannot_answer", "clarify") and not any_suppressed:
        return []

    if flagged:
        return [Failure("suppressed", f"card answered with status {observed.status!r} and "
                                      f"{len(flagged)} market-share row(s), none of them "
                                      f"suppressed")]
    return [Failure("suppressed", f"card answered with status {observed.status!r} but no "
                                  f"result row carries a `suppressed` flag at all "
                                  f"(query_id={observed.query_id!r})")]


# --------------------------------------------------------------------------- narrative

def _grade_numeric(check: str, spec: Any, observed: Observed) -> list[Failure]:
    if not isinstance(spec, dict):
        return [Failure(check, f"malformed expectation {spec!r}")]
    expected = float(spec["value"])
    tolerance_pct = float(spec.get("tolerance_pct", 0.0))
    unit = spec.get("unit")

    literals = extract_numbers(observed.narrative)
    if not literals:
        return [Failure(check, f"expected {_fmt(expected)}{_unit(unit)} "
                               f"+/-{tolerance_pct}%, narrative carries no figure at all: "
                               f"{_excerpt(observed.narrative)}")]

    if any(_literal_matches(literal, expected, tolerance_pct, unit) for literal in literals):
        return []

    nearest = min(literals, key=lambda lit: abs(lit.value - expected))
    return [Failure(check, f"expected {_fmt(expected)}{_unit(unit)} +/-{tolerance_pct}%, "
                           f"narrative carried {[lit.raw for lit in literals[:5]]} "
                           f"(nearest {nearest.raw!r})")]


def _grade_delta_pct(spec: Any, observed: Observed) -> list[Failure]:
    """The period-over-period change, as the prose states it.

    Sign is handled separately because Swedish puts the direction in the verb: "minskade med
    5,8 %" is the correct rendering of -5.81, and the literal is unsigned. So an unsigned
    match is accepted only when the sentence also says the figure went down — which is
    exactly the failure mode mom_june_vs_may_2026 was written to catch.
    """
    if not isinstance(spec, dict):
        return [Failure("delta_pct", f"malformed expectation {spec!r}")]
    expected = float(spec["value"])
    tolerance_pct = float(spec.get("tolerance_pct", 0.0))

    literals = extract_numbers(observed.narrative)
    if not literals:
        return [Failure("delta_pct", f"expected {_fmt(expected)}% +/-{tolerance_pct}%, "
                                     f"narrative carries no figure at all")]

    # A percentage is never written with an implicit magnitude, so no scale sweep here.
    signed = any(_within(literal.value, expected, tolerance_pct, literal.tolerance)
                 for literal in literals)
    if signed:
        return []
    unsigned = any(_within(literal.value, abs(expected), tolerance_pct, literal.tolerance)
                   for literal in literals)
    if unsigned and (expected >= 0 or _DECLINE_WORDS.search(observed.narrative)):
        return []

    if unsigned and expected < 0:
        return [Failure("delta_pct", f"expected {_fmt(expected)}% — a decline — and the "
                                     f"narrative carries the magnitude but no word saying "
                                     f"it fell: {_excerpt(observed.narrative)}")]
    return [Failure("delta_pct", f"expected {_fmt(expected)}% +/-{tolerance_pct}%, "
                                 f"narrative carried {[lit.raw for lit in literals[:5]]}")]


def _grade_must_contain(expected: Any, observed: Observed) -> list[Failure]:
    text = observed.card_text().casefold()
    missing = [needle for needle in expected if str(needle).casefold() not in text]
    if not missing:
        return []
    return [Failure("must_contain", f"{missing} absent from the card: "
                                    f"{_excerpt(observed.card_text())}")]


def _grade_must_not_contain(expected: Any, observed: Observed) -> list[Failure]:
    # Case-insensitive, and over the whole card rather than the narrative alone. Both
    # choices err towards failing: these are competitor names, customer identifiers and
    # prompt fragments, and a leak in a suggestion chip is still a leak.
    text = observed.card_text().casefold()
    present = [needle for needle in expected if str(needle).casefold() in text]
    if not present:
        return []
    return [Failure("must_not_contain", f"forbidden {present} appears in the card: "
                                        f"{_excerpt(observed.card_text())}")]


def _grade_no_numbers(expected: bool, observed: Observed) -> list[Failure]:
    """No money or quantity literal in the narrative.

    `extract_numbers` has already masked the spans whose digits are not measurements — ISO
    dates and months, "14 jan", "jun 2026", ISO weeks, Q2, "#2", "nr 3", "topp 10", "2:a".
    What is left is filtered once more here:

      * a bare integer that reads as a year (1990–2099) — coverage statements say "2024" and
        "2026" constantly, and impossible_past_2019 in fact *requires* them;
      * a bare integer at or below FORBIDDEN_MAX_BARE_INTEGER — counts of suggestions, of
        brands, of rows, and the k-anonymity thresholds the suppression reason quotes.

    Everything else fails: any literal carrying a unit or magnitude suffix (kr, SEK, st,
    enheter, %, mkr, tkr, miljoner) at any magnitude, and any literal with decimals, since a
    decimal with no unit is a percentage or a share by every reasonable reading.
    """
    if not expected:
        return []
    offenders = [literal for literal in extract_numbers(observed.narrative)
                 if _is_forbidden_figure(literal)]
    if not offenders:
        return []
    return [Failure("must_not_contain_numbers",
                    f"narrative carries {[lit.raw for lit in offenders[:5]]}, and there is "
                    f"no legitimate figure to give here: {_excerpt(observed.narrative)}")]


def _is_forbidden_figure(literal: NumberLiteral) -> bool:
    if not literal.bare_integer:
        # Carries a unit, a magnitude suffix or decimals — a measurement by construction.
        return True
    if literal.value.is_integer() and _YEAR_MIN <= literal.value <= _YEAR_MAX:
        return False
    return not (0 <= literal.value <= FORBIDDEN_MAX_BARE_INTEGER)


# ------------------------------------------------------------------------- primitives

def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _close(actual: float, expected: float, tolerance_pct: float) -> bool:
    # The floor keeps a tolerance of 0 % on an expected 0.0 from being unsatisfiable.
    allowed = max(abs(expected) * tolerance_pct / 100.0, 1e-9)
    return abs(actual - expected) <= allowed


def _within(value: float, expected: float, tolerance_pct: float, literal_tol: float) -> bool:
    """The case's tolerance, widened by the precision the literal itself claims.

    "13,1 %" is a claim accurate to ±0,05 — refusing it against an expected 13.05 because
    5 % of 13.05 is 0.65 … would pass anyway, but a rounded "3,4 mkr" against 3 369 616 does
    not, and that rounding is correct Swedish. So the two tolerances add.
    """
    allowed = max(abs(expected) * tolerance_pct / 100.0, 1e-9) + literal_tol
    return abs(value - expected) <= allowed


def _literal_matches(literal: NumberLiteral, expected: float, tolerance_pct: float,
                     unit: str | None) -> bool:
    # "12,4" in a sentence about millions is a rounding, not a hallucination — the same
    # allowance validate.py makes. Percentages are excluded: nobody writes a share in
    # thousands, and allowing it would make a 32.37 % expectation match "0,03".
    scales: tuple[float, ...] = (1.0,)
    if literal.implicit_scale_allowed and unit != "%":
        scales = (1.0, 1e3, 1e6)
    return any(_within(literal.value * scale, expected, tolerance_pct,
                       literal.tolerance * scale) for scale in scales)


def _label_key(columns: list[dict[str, Any]], group_by: Any) -> str | None:
    """The column holding the series labels: the grouping dimension, or the first text one."""
    keys = [c.get("key") for c in columns]
    if group_by in keys:
        return str(group_by)
    for column in columns:
        if column.get("type") in ("date", "text"):
            return str(column["key"])
    return None


def _same_label(expected: Any, actual: Any) -> bool:
    left, right = str(expected).strip().casefold(), str(actual).strip().casefold()
    if left == right:
        return True
    # A date dimension is truncated to the start of its period and serialised in full
    # ("2024-01-01"), while the YAML writes a year as "2024". Prefix equality between two
    # date-shaped strings closes that gap without loosening anything else.
    if _DATEISH.match(left) and _DATEISH.match(right):
        return right.startswith(left) or left.startswith(right)
    return False


def _point_value(rows: list[dict[str, Any]], label_key: str, label: Any,
                 value_key: str) -> float | None:
    for row in rows:
        if _same_label(label, row.get(label_key)) and _is_number(row.get(value_key)):
            return float(row[value_key])
    return None


def _fmt(value: float) -> str:
    text = f"{value:,.2f}".replace(",", " ")
    return text.removesuffix(".00") if float(value).is_integer() else text


def _unit(unit: str | None) -> str:
    return f" {unit}" if unit else ""


def _excerpt(text: str, limit: int = 160) -> str:
    flat = " ".join(text.split())
    return repr(flat if len(flat) <= limit else flat[:limit] + "...")
