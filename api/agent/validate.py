"""Numeric validation of the model's prose (§9.2).

The structural guarantee (§9.1) covers the chart: its values come from the cache, not from
the model. The *narrative* is generated text, so it gets a second, explicit check — every
numeric literal in it must be findable in the cached result set, or be a whitelisted
derivation of it (sum / mean / delta / share) within a rounding tolerance.

Three design points worth reading before changing anything here:

**Tolerance is derived from the literal, not configured.** "12,4 Mkr" is a claim accurate to
±0,05 Mkr, i.e. ±50 000 kr; "8,2 %" is a claim accurate to ±0,05. So the tolerance for a
literal is half a unit of its own last decimal place, scaled by its magnitude suffix. A fixed
relative tolerance would be simultaneously too loose for percentages and too tight for
rounded millions.

**False positives are the expensive failure.** Suppressing a correct answer looks like a
broken product; letting through a number that is right to within half its own last digit does
not. Where the two trade off — implicit magnitudes, small counting integers — this file leans
towards accepting, and each such allowance is commented with what it costs.

**Dates, weeks, ranks and quarters are masked out before extraction.** "jan–jun 2026" and
"#2 av 7" contain digits that are not measurements, and treating them as measurements would
make the validator fire on almost every well-formed Swedish answer.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from ..result_cache import CachedResult

# --- magnitude suffixes -----------------------------------------------------------------
# Written as they actually appear in Swedish financial prose. `mdkr` is included because a
# model that has seen Swedish annual reports will occasionally reach for it.
SCALES: dict[str, float] = {
    "mdkr": 1e9, "miljarder": 1e9, "miljard": 1e9,
    "mkr": 1e6, "msek": 1e6, "miljoner": 1e6, "miljon": 1e6, "mnkr": 1e6,
    "tkr": 1e3, "ksek": 1e3, "tusen": 1e3,
}
UNIT_WORDS = {"kr", "sek", "kronor", "%", "procent", "st", "styck", "enheter"}

# Longest first, so "kronor" is not matched as "kr" followed by stray letters.
_SUFFIX_ALTERNATIVES = "|".join(
    sorted(list(SCALES) + list(UNIT_WORDS), key=len, reverse=True))

# Every character used to group thousands: ordinary space, no-break space, narrow no-break
# space, thin space — and the period, which a model occasionally reaches for ("12.400.000").
# Spelled as escapes rather than typed, because an invisible character inside a character
# class is a bug the next editor to touch this line will silently undo.
_THOUSANDS_CLASS = "[ \\u00a0\\u202f\\u2009.]"

# Spans whose digits are never measurements. Masked to spaces before extraction so that the
# surrounding text keeps its offsets and the remaining numbers keep their context.
_MONTHS = (r"jan(?:uari)?|feb(?:ruari)?|mar(?:s)?|apr(?:il)?|maj|jun(?:i)?|jul(?:i)?|"
           r"aug(?:usti)?|sep(?:t|tember)?|okt(?:ober)?|nov(?:ember)?|dec(?:ember)?")
_MASKS = [
    re.compile(r"\d{4}-\d{2}-\d{2}"),                       # ISO date
    re.compile(r"\d{4}-\d{2}\b"),                           # ISO month
    re.compile(rf"\d{{1,2}}\s*(?:{_MONTHS})\.?", re.I),     # "14 jan"
    re.compile(rf"(?:{_MONTHS})\.?\s*\d{{4}}", re.I),        # "jun 2026"
    re.compile(r"\b(?:v|vecka|vv)\.?\s*\d{1,2}\b", re.I),   # ISO week
    re.compile(r"\b[qk][1-4]\b", re.I),                      # Q2 / K2
    re.compile(r"\bkvartal\s*\d\b", re.I),
    re.compile(r"#\s*\d+"),                                  # rank chip
    re.compile(r"\b(?:nr|plats|placering)\.?\s*\d+\b", re.I),
    re.compile(r"\btopp\s*\d+\b", re.I),                     # "topp 10" is a limit, not a value
    re.compile(r"\b\d+:[ae]\b"),                             # ordinal "2:a"
]

# Integer part: grouped thousands first ("1 234 567", "12.400.000"), otherwise a plain run of
# digits. Grouped first so that "1 234" reads as one number and not as two.
_NUMBER = re.compile(
    r"(?<![\d.,])"
    rf"(?P<int>\d{{1,3}}(?:{_THOUSANDS_CLASS}\d{{3}})+|\d+)"
    r"(?P<frac>[.,]\d+)?"
    rf"(?!\d)\s*(?P<suffix>{_SUFFIX_ALTERNATIVES})?",
    re.I,
)

# Bare integers in this range with no unit are read as calendar years, not as measurements.
# The cost: a genuine "2 024 st" written without its thousands separator would be skipped.
# The benefit: "jan–jun 2026" does not raise a violation on every single answer.
_YEAR_MIN, _YEAR_MAX = 1990, 2099

# A bare integer no larger than this, and no larger than the row count, is accepted as a
# count of things on screen ("de 10 största", "3 av 6 varumärken") rather than a measurement.
# Deliberately small: it widens the whitelist, and the widening has to stay negligible next
# to the magnitudes an actual sales figure has.
_MAX_COUNTING_INTEGER = 50

# Guards against floating-point noise once a value has been multiplied by 1e6.
_FLOAT_EPSILON = 1e-6


@dataclass(frozen=True)
class NumberLiteral:
    raw: str
    value: float
    tolerance: float
    #: True when the literal carried no magnitude suffix, so "12,4" may still mean 12,4 Mkr.
    implicit_scale_allowed: bool
    #: True when the literal is a plain integer with no unit at all.
    bare_integer: bool


@dataclass(frozen=True)
class Attribution:
    """One accepted literal and the result that licensed it.

    The point of keeping this rather than a bare pass/fail: a turn may run several queries,
    the validator has always checked the prose against all of them, and the card carried a
    single `query_id`. So a number grounded in one result could ship beside a chart and a
    source chip describing a different one — traceability pointing at the wrong query. Now
    every accepted figure names its own source.
    """
    literal: str
    value: float
    query_id: str


@dataclass
class ValidationResult:
    ok: bool
    violations: list[str] = field(default_factory=list)
    checked: int = 0
    #: One entry per accepted numeric literal, in the order they appear in the prose.
    attributions: list[Attribution] = field(default_factory=list)

    def query_ids(self) -> list[str]:
        """Distinct results that licensed at least one figure, in first-use order."""
        seen: dict[str, None] = {}
        for attribution in self.attributions:
            seen.setdefault(attribution.query_id, None)
        return list(seen)


# ------------------------------------------------------------------------- extraction

def mask_entity_names(text: str, results: Iterable[CachedResult]) -> str:
    """Blank out entity names carried by the results before numbers are extracted.

    Swedish retail SKUs are named with model numbers — "Nordström TV N100 Pro", "Vidar
    Hörlurar V191 Studio" — and a top-list answer is mostly product names. Extracting digits
    from them produced violations for 139, 217, 282 and, worst of all, "191 St", where the
    "St" of "Studio" was read as the unit `st`. Every top-N answer therefore failed
    validation and had its prose suppressed: the guard was firing hardest on the single most
    common question a supplier asks.

    The names come from the result rows themselves, so this narrows what counts as a claim
    using the same data the claim is checked against — it never masks a figure, only text the
    tool already returned. Longest first, so "N100 Pro" is consumed before a bare "100".
    """
    names = {value for result in results for row in result.rows
             for value in row.values()
             if isinstance(value, str) and any(char.isdigit() for char in value)}
    masked = text
    for name in sorted(names, key=len, reverse=True):
        masked = re.sub(re.escape(name), lambda match: " " * len(match.group(0)),
                        masked, flags=re.I)
    return masked


def mask_non_measurements(text: str) -> str:
    """Blank out dates, ISO weeks, quarters, ranks and `topp N`, preserving length."""
    masked = text
    for pattern in _MASKS:
        masked = pattern.sub(lambda match: " " * len(match.group(0)), masked)
    return masked


def _parse_number(integer_part: str, fraction_part: str | None) -> tuple[float, int]:
    """Return (value, decimal count), reading sv-SE formatting.

    A comma is always a decimal separator. A period is a decimal separator *unless* it is
    followed by exactly three digits, which in Swedish text means it was a thousands
    separator ("12.400.000"). Getting this wrong by a factor of a thousand in either
    direction is the difference between a passing and a failing check, so it is explicit
    rather than left to `float()`.
    """
    digits = re.sub(rf"{_THOUSANDS_CLASS}|\.", "", integer_part)
    if fraction_part is None:
        return float(digits), 0

    separator, fraction = fraction_part[0], fraction_part[1:]
    if separator == "." and len(fraction) == 3:
        return float(digits + fraction), 0
    return float(f"{digits}.{fraction}"), len(fraction)


def extract_numbers(text: str) -> list[NumberLiteral]:
    """Every numeric claim in the narrative, with the tolerance its own precision implies."""
    literals: list[NumberLiteral] = []
    for match in _NUMBER.finditer(mask_non_measurements(text)):
        value, decimals = _parse_number(match.group("int"), match.group("frac"))
        suffix = (match.group("suffix") or "").lower()
        scale = SCALES.get(suffix, 1.0)
        has_unit = bool(suffix)

        value *= scale
        # Half a unit of the literal's last decimal place, in the literal's own magnitude.
        tolerance = 0.5 * (10.0 ** -decimals) * scale
        tolerance += abs(value) * _FLOAT_EPSILON

        literals.append(NumberLiteral(
            raw=match.group(0).strip(),
            value=value,
            tolerance=tolerance,
            implicit_scale_allowed=suffix not in SCALES,
            bare_integer=decimals == 0 and not has_unit,
        ))
    return literals


# ------------------------------------------------------------------------- candidates

def _numbers_in(rows: Sequence[dict], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = row.get(key)
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def build_candidates(results: Iterable[CachedResult]) -> tuple[list[float], int]:
    """Every value the model is allowed to have used, plus the largest row count seen.

    Sorted, so a literal is checked with a binary search rather than a scan over what can be
    a hundred thousand values.

    Kept as the merged view because callers outside validation (and the eval grader) want one
    flat set. `candidates_by_result` is the same computation kept per result, which is what
    lets a passing literal name the query that licensed it.
    """
    results = list(results)
    merged: list[float] = []
    for _query_id, candidates in candidates_by_result(results):
        merged.extend(candidates)
    merged.sort()
    max_rows = max((result.row_count for result in results), default=0)
    return merged, max_rows


def candidates_by_result(
        results: Iterable[CachedResult]) -> list[tuple[str, list[float]]]:
    """The same derivation as `build_candidates`, kept separately per result.

    Attribution is the whole reason. `validate_narrative` runs against every result the turn
    produced while the card carried a single `query_id`, so prose grounded in result A could
    ship beside a chart of result B and a source chip describing B's filters and time range —
    the artefact whose entire purpose is traceability, pointing at the wrong query. Keeping
    the candidate sets apart means a literal that passes can say which result it came from,
    and the card can carry all of them.

    A list of pairs rather than a dict keyed by `query_id`. Ids are unique in production, but
    a dict makes uniqueness load-bearing for *correctness*: two results sharing an id would
    silently overwrite each other and a perfectly grounded number would be reported as a
    fabrication. A validator must not fail closed on a bookkeeping detail, so position is the
    key and the id is only carried along.
    """
    by_result: list[tuple[str, list[float]]] = []

    for result in results:
        candidates: list[float] = []
        candidates.append(float(result.row_count))

        # Whether the rows we hold ARE the whole result. Aggregate derivations below are only
        # sound when they are: if the tool capped the result at MAX_ROWS, the sum of what we
        # have is not the total, and accepting it would let "totalt X kr" pass while being
        # the sum of an arbitrary subset. That is precisely the failure the system prompt
        # warns the model about, so the validator must not quietly permit it.
        complete = len(result.rows) >= result.row_count

        # `limit` is the one tool argument that legitimately shows up in prose ("topp 10").
        limit = result.tool_args.get("limit")
        if isinstance(limit, int) and not isinstance(limit, bool):
            candidates.append(float(limit))

        numeric_keys = result.numeric_columns()
        for key in numeric_keys:
            values = _numbers_in(result.rows, key)
            if not values:
                continue

            candidates.extend(values)                                   # the cells themselves

            if complete:
                total = sum(values)
                candidates.append(total)                                # sum
                candidates.append(total / len(values))                  # mean
                if total:
                    # share: each value as a percentage of its column total
                    candidates.extend(100.0 * value / total for value in values)

            # delta between adjacent rows stays available either way — it is local to two rows
            # and does not depend on holding the whole series.
            for previous, current in pairwise(values):
                candidates.append(current - previous)
                if previous:
                    candidates.append(100.0 * (current - previous) / abs(previous))

            if complete:
                # first→last is a statement about the series as a whole, so it needs the
                # whole series.
                candidates.append(values[-1] - values[0])
                if values[0]:
                    candidates.append(100.0 * (values[-1] - values[0]) / abs(values[0]))

            # delta against the comparison period, when compare_to produced a paired column.
            # The percentage form already exists as a cell (`*_delta_pct`, computed in SQL);
            # only the absolute difference needs deriving.
            compare_key = f"{key}_compare"
            if compare_key in numeric_keys:
                for row in result.rows:
                    current, previous = row.get(key), row.get(compare_key)
                    if isinstance(current, (int, float)) and isinstance(previous, (int, float)):
                        candidates.append(float(current) - float(previous))

        # Prose says "ökade med 4,2 %" for a delta of -4.2 as readily as for +4.2; the sign
        # lives in the verb, which is not something a numeric check can read.
        candidates.extend([-value for value in candidates])
        candidates.sort()
        by_result.append((result.query_id, candidates))

    return by_result


def _matches(candidates: Sequence[float], value: float, tolerance: float) -> bool:
    index = bisect.bisect_left(candidates, value - tolerance)
    return index < len(candidates) and candidates[index] <= value + tolerance


# -------------------------------------------------------------------------- validation

def validate_narrative(text: str, results: Iterable[CachedResult]) -> ValidationResult:
    """Check every numeric literal in `text` against the cached result sets.

    Passing several results is intentional: one turn may run more than one query, and a
    number in the prose may legitimately come from any of them.
    """
    results = list(results)
    by_result = candidates_by_result(results)
    max_rows = max((result.row_count for result in results), default=0)
    literals = extract_numbers(mask_entity_names(text, results))

    violations: list[str] = []
    attributions: list[Attribution] = []

    for literal in literals:
        if (literal.bare_integer and literal.value.is_integer()
                and _YEAR_MIN <= literal.value <= _YEAR_MAX):
            continue
        if (literal.bare_integer
                and literal.value.is_integer()
                and 0 <= literal.value <= min(max_rows, _MAX_COUNTING_INTEGER)):
            continue

        # Try the literal as written, then — only when it carried no magnitude suffix — as
        # thousands and as millions. "12,4" in a sentence about millions is a rounding of
        # 12 412 331, not a hallucination, and the tolerance scales with the reading.
        scales = (1.0, 1e3, 1e6) if literal.implicit_scale_allowed else (1.0,)

        # Results are tried in the order the turn produced them, so a figure that several
        # queries could account for is attributed to the first one that could — which is the
        # one the model was looking at when it wrote the sentence.
        source = next(
            (query_id for query_id, candidates in by_result
             if any(_matches(candidates, literal.value * scale, literal.tolerance * scale)
                    for scale in scales)),
            None)
        if source is not None:
            attributions.append(Attribution(literal=literal.raw, value=literal.value,
                                            query_id=source))
            continue

        violations.append(
            f"\"{literal.raw}\" finns inte i resultatet och är inte en tillåten härledning "
            f"(summa, medel, förändring eller andel) av något värde i det."
        )

    return ValidationResult(ok=not violations, violations=violations,
                            checked=len(literals), attributions=attributions)
