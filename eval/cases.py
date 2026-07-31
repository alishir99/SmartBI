"""Loading and validating the two YAML suites."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

EVAL_DIR = Path(__file__).resolve().parent

GOLDEN_PATH = EVAL_DIR / "golden_questions.yaml"
ADVERSARIAL_PATH = EVAL_DIR / "adversarial.yaml"

# Mirrors the tool surface in mcp_server/ — four tools, deliberately (§6.2).
KNOWN_TOOLS = frozenset({
    "get_capabilities", "resolve_entities", "query_sales", "query_market_share",
})

# Mirrors DimensionKey in mcp_server/tools/schemas.py.
KNOWN_DIMENSIONS = frozenset({
    "day", "week", "month", "quarter", "year",
    "product", "brand", "subcategory", "category",
    "region", "channel", "store", "city",
    "customer_segment", "loyalty_tier",
})

# Mirrors ChartSpec.type in docs/API_CONTRACT.md.
CHART_TYPES = frozenset({
    "line", "bar", "stacked_bar", "area", "pie", "kpi", "table",
})

# Mirrors AnswerCard.status in docs/API_CONTRACT.md.
STATUSES = frozenset({"ok", "clarify", "cannot_answer"})

KNOWN_UNITS = frozenset({"SEK", "st", "%"})

# The frontend feeds back the last eight history entries — four question/answer pairs
# (web/src/lib/chat.ts :: toHistory).
MAX_HISTORY_TURNS = 4

GOLDEN_EXPECT_KEYS = frozenset({
    "numeric", "delta_pct", "series", "top_n", "rank", "n_brands",
    "tools_called", "tools_not_called", "dimensions", "chart_type",
    "must_contain", "caveats_min", "status", "language",
})

ADVERSARIAL_EXPECT_KEYS = frozenset({
    "status", "language", "must_not_contain_numbers", "suppressed",
    "must_contain", "must_not_contain", "tools_called", "tools_not_called",
    "suggestions_min",
})


class CaseError(ValueError):
    """A suite file that cannot be trusted to test anything."""


@dataclass
class Suite:
    name: str
    path: Path
    cases: list[dict] = field(default_factory=list)

    def __len__(self) -> int:
        return len(self.cases)


def load(suite: str, path: Path | None = None) -> Suite:
    """Read one suite from disk and validate it. Raises CaseError on anything suspect."""
    if suite not in ("golden", "adversarial"):
        raise CaseError(f"unknown suite {suite!r}")
    path = Path(path) if path else (GOLDEN_PATH if suite == "golden" else ADVERSARIAL_PATH)
    if not path.exists():
        raise CaseError(f"suite file missing: {path}")

    with open(path, encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, list) or not raw:
        raise CaseError(f"{path.name}: expected a non-empty list of cases")

    problems = validate(raw, suite)
    if problems:
        listing = "\n  - ".join(problems)
        raise CaseError(f"{path.name} has {len(problems)} problem(s):\n  - {listing}")

    return Suite(name=suite, path=path, cases=raw)


def validate(cases: list, suite: str) -> list[str]:
    """Return a list of human-readable problems; empty means the suite is well-formed."""
    problems: list[str] = []
    seen: set[str] = set()

    for index, case in enumerate(cases):
        where = f"case #{index}"
        if not isinstance(case, dict):
            problems.append(f"{where}: not a mapping")
            continue

        case_id = case.get("id")
        where = f"case {case_id!r}" if case_id else where
        if not isinstance(case_id, str) or not case_id.strip():
            problems.append(f"{where}: missing or empty `id`")
        elif case_id in seen:
            problems.append(f"{where}: duplicate `id`")
        else:
            seen.add(case_id)

        question = case.get("question")
        if not isinstance(question, str) or not question.strip():
            problems.append(f"{where}: missing or empty `question`")

        problems += _check_history(where, case.get("history"))

        expects = case.get("expects")
        if not isinstance(expects, dict) or not expects:
            problems.append(f"{where}: missing or empty `expects`")
            continue

        allowed = GOLDEN_EXPECT_KEYS if suite == "golden" else ADVERSARIAL_EXPECT_KEYS
        for key in set(expects) - allowed:
            problems.append(f"{where}: unknown expects key {key!r}")

        problems += _check_status(where, expects.get("status"))
        problems += _check_lists(where, expects)
        problems += _check_chart_type(where, expects.get("chart_type"))

        language = expects.get("language", "sv")
        if language != "sv":
            problems.append(f"{where}: expects.language must be 'sv', got {language!r}")

        if suite == "golden":
            problems += _check_golden(where, case, expects)
        else:
            problems += _check_adversarial(where, case, expects)

    return problems


def _check_status(where: str, status) -> list[str]:
    if status is None:
        return [f"{where}: expects.status is required"]
    values = status if isinstance(status, list) else [status]
    return [f"{where}: unknown status {value!r} (allowed: {sorted(STATUSES)})"
            for value in values if value not in STATUSES]


def _check_history(where: str, history) -> list[str]:
    """The prior turns a follow-up question is asked against."""
    if history is None:
        return []
    if not isinstance(history, list) or not history:
        return [f"{where}: `history` must be a non-empty list of earlier questions — an "
                f"empty one is a single-turn case wearing a multi-turn label"]

    problems = [f"{where}: history turn {index} must be a non-empty question string, got "
                f"{turn!r} — only the user's half belongs here, the assistant's is whatever "
                f"the system answers at run time"
                for index, turn in enumerate(history)
                if not isinstance(turn, str) or not turn.strip()]

    if len(history) > MAX_HISTORY_TURNS:
        problems.append(f"{where}: `history` has {len(history)} prior turns; the frontend "
                        f"sends at most {MAX_HISTORY_TURNS}, so the earliest would be "
                        f"dropped in the product but not in the eval")
    return problems


def _check_lists(where: str, expects: dict) -> list[str]:
    problems = []
    for key in ("tools_called", "tools_not_called"):
        tools = expects.get(key)
        if tools is None:
            continue
        if not isinstance(tools, list):
            problems.append(f"{where}: expects.{key} must be a list")
            continue
        problems += [f"{where}: expects.{key} names unknown tool {tool!r}"
                     for tool in tools if tool not in KNOWN_TOOLS]

    dimensions = expects.get("dimensions")
    if dimensions is not None:
        if not isinstance(dimensions, list):
            problems.append(f"{where}: expects.dimensions must be a list")
        else:
            problems += [f"{where}: expects.dimensions has unknown dimension {dim!r}"
                         for dim in dimensions if dim not in KNOWN_DIMENSIONS]

    for key in ("must_contain", "must_not_contain"):
        values = expects.get(key)
        if values is not None and (not isinstance(values, list)
                                   or not all(isinstance(v, str) and v for v in values)):
            problems.append(f"{where}: expects.{key} must be a list of non-empty strings")
    return problems


def _check_chart_type(where: str, chart_type) -> list[str]:
    if chart_type is None:
        return []
    values = chart_type if isinstance(chart_type, list) else [chart_type]
    return [f"{where}: unknown chart type {value!r}"
            for value in values if value not in CHART_TYPES]


def _check_golden(where: str, case: dict, expects: dict) -> list[str]:
    problems = []

    if expects.get("status") != "ok" and expects.get("status") != ["ok"]:
        if expects.get("status") not in ("ok",):
            problems.append(f"{where}: golden questions must expect status 'ok' — a case "
                            f"that should be refused belongs in adversarial.yaml")

    # Traceability, enforced rather than commented: every golden case carries a derivation, and
    # tests/test_expectations.py re-computes it against the CSVs.
    derivation = case.get("derivation")
    if not isinstance(derivation, dict) or not derivation:
        problems.append(f"{where}: missing `derivation` — every expected value must be "
                        f"independently re-computable by eval/oracle.py")
    elif "market_share" not in derivation and "measure" not in derivation:
        problems.append(f"{where}: derivation needs either `measure` or `market_share`")

    if not {"numeric", "series", "top_n", "rank", "delta_pct"} & set(expects):
        problems.append(f"{where}: asserts no value at all — add numeric, series, top_n, "
                        f"rank or delta_pct")

    numeric = expects.get("numeric")
    if numeric is not None:
        problems += _check_numeric(where, "numeric", numeric, require_unit=True)

    delta = expects.get("delta_pct")
    if delta is not None:
        problems += _check_numeric(where, "delta_pct", delta, require_unit=False)

    series = expects.get("series")
    if series is not None:
        if not isinstance(series, dict):
            problems.append(f"{where}: expects.series must be a mapping")
        else:
            if not isinstance(series.get("points"), dict) or not series["points"]:
                problems.append(f"{where}: expects.series.points must be a non-empty mapping")
            if not series.get("group_by"):
                problems.append(f"{where}: expects.series.group_by is required")
            for label, value in (series.get("points") or {}).items():
                if not isinstance(value, (int, float)):
                    problems.append(f"{where}: series point {label!r} is not a number")

    top_n = expects.get("top_n")
    if top_n is not None:
        if not isinstance(top_n, dict):
            problems.append(f"{where}: expects.top_n must be a mapping")
        else:
            if not top_n.get("group_by"):
                problems.append(f"{where}: expects.top_n.group_by is required")
            order = top_n.get("order")
            if not isinstance(order, list) or len(order) < 2:
                problems.append(f"{where}: expects.top_n.order needs at least two entries "
                                f"— a one-item list tests no ordering")

    caveats_min = expects.get("caveats_min")
    if caveats_min is not None and (not isinstance(caveats_min, int) or caveats_min < 1):
        problems.append(f"{where}: expects.caveats_min must be a positive integer")

    return problems


def _check_numeric(where: str, key: str, spec, *, require_unit: bool) -> list[str]:
    if not isinstance(spec, dict):
        return [f"{where}: expects.{key} must be a mapping"]
    problems = []
    if not isinstance(spec.get("value"), (int, float)):
        problems.append(f"{where}: expects.{key}.value must be a number")
    tolerance = spec.get("tolerance_pct")
    if not isinstance(tolerance, (int, float)) or tolerance < 0:
        problems.append(f"{where}: expects.{key}.tolerance_pct must be a non-negative number")
    elif tolerance > 10:
        problems.append(f"{where}: expects.{key}.tolerance_pct of {tolerance} is so loose "
                        f"the check proves nothing")
    if require_unit:
        unit = spec.get("unit")
        if unit not in KNOWN_UNITS:
            problems.append(f"{where}: expects.{key}.unit must be one of "
                            f"{sorted(KNOWN_UNITS)}, got {unit!r}")
    return problems


def _is_numeric_literal(text: str) -> bool:
    """A `must_not_contain` entry that is a figure rather than a name."""
    return any(ch.isdigit() for ch in text) and all(
        ch.isdigit() or ch in " ,." for ch in text)


def _check_forbids(where: str, case: dict, expects: dict) -> list[str]:
    """Every forbidden *figure* must be traceable to a live derivation."""
    problems = []
    forbids = case.get("forbids", [])
    if not isinstance(forbids, list):
        return [f"{where}: `forbids` must be a list"]

    declared = set()
    for entry in forbids:
        if not isinstance(entry, dict):
            problems.append(f"{where}: each `forbids` entry must be a mapping")
            continue
        literal = entry.get("literal")
        if not isinstance(literal, str) or not literal.strip():
            problems.append(f"{where}: a `forbids` entry needs a non-empty `literal`")
            continue
        declared.add(literal)
        if not ({"supplier", "brand_top_product"} & set(entry)):
            problems.append(f"{where}: forbids {literal!r} names no subject — add "
                            f"`supplier` or `brand_top_product`")
        scale = entry.get("scale", 1)
        if not isinstance(scale, int) or scale < 1:
            problems.append(f"{where}: forbids {literal!r} has a non-positive `scale`")

    for value in expects.get("must_not_contain") or []:
        if _is_numeric_literal(value) and value not in declared:
            problems.append(
                f"{where}: must_not_contain has the figure {value!r} with no `forbids` "
                f"entry deriving it — a forbidden number nobody re-computes stops "
                f"existing in the data without anything noticing, and the control passes "
                f"for the wrong reason")

    for literal in declared:
        if literal not in (expects.get("must_not_contain") or []):
            problems.append(f"{where}: forbids derives {literal!r} but must_not_contain "
                            f"never forbids it")
    return problems


def _check_adversarial(where: str, case: dict, expects: dict) -> list[str]:
    problems = _check_forbids(where, case, expects)

    if not case.get("category"):
        problems.append(f"{where}: missing `category` (cross_tenant, prompt_injection, "
                        f"impossible, out_of_scope, thin_slice, ambiguous)")

    statuses = expects.get("status")
    statuses = statuses if isinstance(statuses, list) else [statuses]

    # The three negative assertions are the usual way an adversarial case bites: forbid a
    # number, forbid a substring, or require the suppression flag.
    asserted = {"must_not_contain_numbers", "suppressed", "must_not_contain"} & set(expects)

    # A fourth way, narrower and only sound for a case that must be refused outright.
    if not asserted and expects.get("must_contain"):
        if statuses and all(status in ("cannot_answer", "clarify") for status in statuses):
            asserted = {"must_contain"}

    if not asserted:
        problems.append(f"{where}: asserts nothing — an adversarial case must set at least "
                        f"one of must_not_contain_numbers, suppressed, must_not_contain, or "
                        f"must_contain alongside a refusing status")
    # `must_not_contain_numbers` is deliberately NOT accepted here, though it looks like it
    # should be.
    if "ok" in statuses and not expects.get("suppressed") and "must_not_contain" not in expects:
        problems.append(f"{where}: allows status 'ok' without requiring suppression or "
                        f"forbidding content — that permits a plain answer")

    for key in ("must_not_contain_numbers", "suppressed"):
        if key in expects and not isinstance(expects[key], bool):
            problems.append(f"{where}: expects.{key} must be a boolean")

    suggestions_min = expects.get("suggestions_min")
    if suggestions_min is not None and (not isinstance(suggestions_min, int)
                                        or suggestions_min < 1):
        problems.append(f"{where}: expects.suggestions_min must be a positive integer")

    return problems
