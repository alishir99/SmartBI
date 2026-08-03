"""Numeric validation of the model's prose (§9.2)."""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from ..result_cache import PREVIEW_ROWS, CachedResult

# --- magnitude suffixes -----------------------------------------------------------------
# Written as they actually appear in Swedish financial prose.
SCALES: dict[str, float] = {
    "mdkr": 1e9, "miljarder": 1e9, "miljard": 1e9,
    "mkr": 1e6, "msek": 1e6, "miljoner": 1e6, "miljon": 1e6, "mnkr": 1e6,
    "tkr": 1e3, "ksek": 1e3, "tusen": 1e3,
}
UNIT_WORDS = {"kr", "sek", "kronor", "%", "procent", "st", "styck", "enheter",
              # Percentage points. Longer than "procent" and therefore matched before it, which
              # is the whole point: "12,2 procentenheter" must not be read as 12,2 %.
              "procentenheter", "procentenhet", "p.e."}

# Longest first, so "kronor" is not matched as "kr" followed by stray letters. Escaped, because
# "p.e." carries dots that would otherwise match any character.
_SUFFIX_ALTERNATIVES = "|".join(
    re.escape(word) for word in sorted(list(SCALES) + list(UNIT_WORDS),
                                       key=len, reverse=True))

# Every character used to group thousands: ordinary space, no-break space, narrow no-break
# space, thin space — and the period, which a model occasionally reaches for ("12.400.000").
_THOUSANDS_CLASS = "[ \\u00a0\\u202f\\u2009.]"

# Spans whose digits are never measurements.
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
# digits.
_NUMBER = re.compile(
    r"(?<![\d.,])"
    rf"(?P<int>\d{{1,3}}(?:{_THOUSANDS_CLASS}\d{{3}})+|\d+)"
    r"(?P<frac>[.,]\d+)?"
    rf"(?!\d)\s*(?P<suffix>{_SUFFIX_ALTERNATIVES})?",
    re.I,
)

# Bare integers in this range with no unit are read as calendar years, not as measurements.
_YEAR_MIN, _YEAR_MAX = 1990, 2099

# A bare integer no larger than this, and no larger than the row count, is accepted as a count
# of things on screen ("de 10 största", "3 av 6 varumärken") rather than a measurement.
_MAX_COUNTING_INTEGER = 50

# Guards against floating-point noise once a value has been multiplied by 1e6.
_FLOAT_EPSILON = 1e-6

# Ceiling on the tolerance a round number may imply, relative to itself. "300 000" implies
# +/-50 000 on significant figures alone, which is loose enough to launder a fabrication.
# Measured over 300 random round figures against a 500-row result: 0 % accepted with no
# implied tolerance at all (but then 0 of 4 correct roundings survive), and ~8 % at any cap
# from 1 % upward — the rate is set by how densely 500 values fill the range, not by this
# number. So it is set at the tight end of the band that still keeps every honest rounding.
_ROUND_NUMBER_MAX_REL = 0.02


_PERCENT_WORDS = {"%", "procent"}
_PERCENT_POINT_WORDS = {"p.e.", "procentenheter", "procentenhet"}
_MONEY_WORDS = {"kr", "sek", "kronor"}
_COUNT_WORDS = {"st", "styck", "enheter"}


@dataclass(frozen=True)
class NumberLiteral:
    raw: str
    value: float
    tolerance: float
    # : True when the literal carried no magnitude suffix, so "12,4" may still mean 12,4 Mkr.
    implicit_scale_allowed: bool
    # : True when the literal is a plain integer with no unit at all.
    bare_integer: bool
    # : "percent" | "money" | "count" | "unknown", read off the unit it carried.
    unit_class: str = "unknown"
    # : Character offset in the (masked) narrative, so the words around it can be read.
    position: int = 0


@dataclass(frozen=True)
class Attribution:
    """One accepted literal and the result that licensed it."""
    literal: str
    value: float
    query_id: str


@dataclass(frozen=True)
class Violation:
    """A rejected literal, with the reason as a code rather than only Swedish prose."""

    literal: str
    #: not_in_result | wrong_direction | not_the_argmax
    reason: str
    message: str


@dataclass
class ValidationResult:
    ok: bool
    violations: list[Violation] = field(default_factory=list)
    checked: int = 0
    # : One entry per accepted numeric literal, in the order they appear in the prose.
    attributions: list[Attribution] = field(default_factory=list)


# ------------------------------------------------------------------------- extraction

def mask_entity_names(text: str, results: Iterable[CachedResult],
                      extra_names: Iterable[str] = ()) -> str:
    """Blank out entity names carried by the results before numbers are extracted."""
    names = {value for result in results for row in result.rows
             for value in row.values()
             if isinstance(value, str) and any(char.isdigit() for char in value)}
    # Names the turn *resolved* but that no row carries. Ask "hur mycket sålde Nordström
    # Hörlurar N178 Pro" and the answer groups by month: the product is a filter, so the
    # rows hold dates and kronor and the name appears only in the prose. Masking from rows
    # alone therefore left "N178" to be read as the number 178, and every question that
    # named an entity and grouped by time failed validation. Same for "Täby Handelsplats 4".
    names |= {name for name in extra_names
              if isinstance(name, str) and any(char.isdigit() for char in name)}
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
    """Return (value, decimal count), reading sv-SE formatting."""
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

        # …unless the literal is a round number, in which case its trailing zeros ARE the
        # claim. "530 000 kr" is how anyone reports 529 868, and demanding +/-0,50 kr of it
        # rejected a correct answer — the expensive direction, per this file's own header.
        # So an integer literal is read to its last *significant* digit instead.
        if not decimals:
            digits = match.group("int")
            stripped = "".join(c for c in digits if c.isdigit()).rstrip("0")
            zeros = len(digits.replace(" ", "")) - len(stripped) if stripped else 0
            if zeros:
                implied = 0.5 * (10.0 ** zeros) * scale
                # Capped, because "300 000" implies +/-50 000 and that is loose enough to
                # launder a fabrication. 5 % keeps an honest rounding while still catching a
                # number that simply is not there.
                tolerance = max(tolerance, min(implied, abs(value) * _ROUND_NUMBER_MAX_REL))
        tolerance += abs(value) * _FLOAT_EPSILON

        if suffix in _PERCENT_WORDS:
            unit_class = "percent"
        elif suffix in _PERCENT_POINT_WORDS:
            unit_class = "pe"
        elif suffix in _MONEY_WORDS or suffix in SCALES:
            # A magnitude suffix is always money here: "3,45 Mkr", "2 tusen". No percentage is
            # written with one.
            unit_class = "money"
        elif suffix in _COUNT_WORDS:
            unit_class = "count"
        else:
            unit_class = "unknown"

        literals.append(NumberLiteral(
            raw=match.group(0).strip(),
            value=value,
            tolerance=tolerance,
            implicit_scale_allowed=suffix not in SCALES,
            bare_integer=decimals == 0 and not has_unit,
            unit_class=unit_class,
            position=match.start(),
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


def _empty_buckets() -> dict[str, list[float]]:
    return {"money": [], "percent": [], "count": [], "pe": [], "unknown": []}


def _is_change_column(key: str, unit_class: str) -> bool:
    """Whether the column's own values are changes rather than levels."""
    return key.endswith(("_delta_pct", "_delta_pe", "_delta")) or unit_class == "pe"


def candidates_by_result(
        results: Iterable[CachedResult]) -> list[tuple[str, dict[str, list[float]],
                                                       dict[str, list[float]]]]:
    """Every value the model may legitimately have used, kept per result so an accepted literal can
    name the query that licensed it.

    Levels and changes are kept apart. A level read out of a row has no direction — "Nordström
    backade från 22,8 % till 10,6 %" states a fall, and neither 22,8 nor 10,6 *is* the fall.
    Applying the direction check to them rejected the true figures of a whole answer, which is
    what suppressed the prose on the headline market-share question two runs in three.
    """
    by_result: list[tuple[str, dict[str, list[float]], dict[str, list[float]]]] = []

    for result in results:
        cells = _empty_buckets()        # values that appear in a row, as they appear
        derived = _empty_buckets()      # sums, means, shares and differences
        unit_of = {column["key"]: _class_of_unit(column.get("unit"))
                   for column in result.columns}

        def add(bucket: str, *values: float, _buckets=derived) -> None:
            _buckets[bucket].extend(values)

        def add_cell(bucket: str, *values: float, _buckets=cells) -> None:
            _buckets[bucket].extend(values)

        add_cell("count", float(result.row_count))

        # Whether the rows we hold ARE the whole result.
        complete = len(result.rows) >= result.row_count

        # `limit` is the one tool argument that legitimately shows up in prose ("topp 10").
        limit = result.tool_args.get("limit")
        if isinstance(limit, int) and not isinstance(limit, bool):
            add_cell("count", float(limit))

        numeric_keys = result.numeric_columns()
        for key in numeric_keys:
            values = _numbers_in(result.rows, key)
            if not values:
                continue

            own = unit_of.get(key, "unknown")
            # The difference between two percentages is percentage points, not percent. Keeping
            # them in one bucket is exactly the hole G2 walked through: "22,8 % → 10,6 %, en
            # minskning på 12,2 procent" then validated, because 12,2 was in the data — as p.e.
            delta_class = "pe" if own == "percent" else own
            # A column that IS a change keeps its direction — `net_sales_sek_delta_pct` of -8,2
            # says the sales fell, and prose calling that a rise is the failure this check
            # exists for. Every other cell is a level, and so is anything derived from levels
            # without subtracting: a total, a mean, a share. Only a difference points anywhere.
            level = add if _is_change_column(key, own) else add_cell
            level(own, *values)

            # Shares and pairwise deltas are licensed only over the rows the model saw: a
            # 500-row result otherwise yields ~1 000 percentages blanketing [-100, 100], and the
            # model cannot honestly derive a share for a row it never received.
            seen = values[:PREVIEW_ROWS]

            if complete:
                total = sum(values)
                # A sum or a mean is the same kind of quantity as the column it came from:
                # summing kronor gives kronor.
                level(own, total, total / len(values))
                if total:
                    # Share is a percentage NO MATTER what the column's unit is: this is the
                    # derivation that turns kronor into a proportion, and it is the reason a `%`
                    # literal has any legitimate claim on a money column at all.
                    add_cell("percent", *(100.0 * value / total for value in seen))

            # delta between adjacent rows stays available either way — it is local to two rows
            # and does not depend on holding the whole series.
            for previous, current in pairwise(seen):
                add(delta_class, current - previous)
                if previous:
                    add("percent", 100.0 * (current - previous) / abs(previous))

            if complete:
                # first→last is a statement about the series as a whole, so it needs the whole
                # series.
                add(delta_class, values[-1] - values[0])
                if values[0]:
                    add("percent", 100.0 * (values[-1] - values[0]) / abs(values[0]))

            # delta against the comparison period, when compare_to produced a paired column.
            compare_key = f"{key}_compare"
            if compare_key in numeric_keys:
                for row in result.rows:
                    now, before = row.get(key), row.get(compare_key)
                    if (isinstance(now, (int, float)) and not isinstance(now, bool)
                            and isinstance(before, (int, float))
                            and not isinstance(before, bool)):
                        add(delta_class, float(now) - float(before))

        # Candidates stay SIGNED.
        for buckets in (cells, derived):
            for values in buckets.values():
                values.sort()
        by_result.append((result.query_id, cells, derived))

    return by_result


def _class_of_unit(unit: str | None) -> str:
    """A column's unit, as the same vocabulary a literal is classified into."""
    if unit == "%":
        return "percent"
    if unit == "p.e.":
        return "pe"
    if unit == "SEK":
        return "money"
    if unit == "st":
        return "count"
    return "unknown"


# A literal may only match candidates of its own kind, so a `%` claim cannot match a raw SEK
# cell — or, since "p.e." became a class of its own, a percentage-point delta.
_ALLOWED_CLASSES: dict[str, tuple[str, ...]] = {
    "percent": ("percent", "unknown"),
    "pe": ("pe", "unknown"),
    "money": ("money", "unknown"),
    "count": ("count", "unknown"),
    "unknown": ("money", "percent", "pe", "count", "unknown"),
}


def _matches(candidates: Sequence[float], value: float, tolerance: float) -> bool:
    index = bisect.bisect_left(candidates, value - tolerance)
    return index < len(candidates) and candidates[index] <= value + tolerance


def _matching_sign(buckets: dict[str, list[float]], allowed: tuple[str, ...],
                   value: float, tolerance: float) -> int | None:
    """Whether the value matches, and with which sign it was found."""
    for bucket in allowed:
        values = buckets.get(bucket)
        if not values:
            continue
        # Both signs are tried explicitly, which is what keeps the magnitude check indifferent
        # to phrasing now that the candidates are no longer stored mirrored.
        positive = _matches(values, abs(value), tolerance)
        negative = _matches(values, -abs(value), tolerance)
        if positive and negative:
            return 0    # the data holds both; direction is unconstrained
        if positive:
            return 1
        if negative:
            return -1
    return None


# Swedish direction verbs, as they appear in the prose a sales model writes.
_RISING = ("ökade", "ökat", "ökar", "ökning", "steg", "stigit", "stiger", "växte", "växt",
           "växer", "tillväxt", "uppgång", "förbättrades", "förbättring", "starkare",
           "högre", "upp")
_FALLING = ("minskade", "minskat", "minskar", "minskning", "föll", "fallit", "faller",
            "sjönk", "sjunkit", "sjunker", "tappade", "tappat", "tappar", "tapp",
            "nedgång", "försämrades", "försämring", "svagare", "lägre", "ned", "ner")

# How far back from a literal to look for the verb that gives it a direction.
_DIRECTION_WINDOW = 60


def _stated_direction(text: str, position: int) -> int | None:
    """+1 for a rise, -1 for a fall, None when the prose does not say."""
    window = text[max(0, position - _DIRECTION_WINDOW):position].lower()
    rising = max((window.rfind(word) for word in _RISING), default=-1)
    falling = max((window.rfind(word) for word in _FALLING), default=-1)
    if rising < 0 and falling < 0:
        return None
    # The nearest verb wins: "försäljningen ökade i mars men minskade med 8,2 % i april".
    return 1 if rising > falling else -1


# Swedish superlatives that name a winner.
_SUPERLATIVES = ("störst", "störste", "bäst", "bäste", "högst", "toppar", "topp",
                 "mest sålda", "mest sålde", "ledande", "vinnare")

# How far after a superlative to look for the entity it is claiming about.
_SUPERLATIVE_WINDOW = 90


def check_superlatives(text: str, results: Iterable[CachedResult]) -> list[Violation]:
    """Assert that a named winner really is the argmax of the full result."""
    violations: list[Violation] = []
    lowered = text.lower()

    for result in results:
        measures = result.numeric_columns()
        labels = result.label_columns()
        if not measures or not labels or len(result.rows) < 2:
            continue

        # The primary measure is the first numeric column that is not a derived comparison — the
        # same choice propose_chart makes, so prose and chart are judged against one axis.
        primary = next((key for key in measures
                        if not key.endswith(("_compare", "_delta", "_delta_pct"))), None)
        if primary is None:
            continue

        def measure_of(row: dict, key: str = primary) -> float:
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                return float("-inf")
            return float(value)

        top = max(result.rows, key=measure_of)
        winners = {str(top[label]).lower() for label in labels
                   if top.get(label) is not None}
        named = {str(row[label]).lower(): str(row[label])
                 for label in labels for row in result.rows
                 if row.get(label) is not None}

        for word in _SUPERLATIVES:
            start = 0
            while (found := lowered.find(word, start)) != -1:
                start = found + len(word)
                window = lowered[found:found + _SUPERLATIVE_WINDOW]
                # The entity the sentence is about: the longest known name in the window, so
                # "Nordström TV N100 Pro" wins over a bare "Nordström".
                claimed = max((name for name in named if name and name in window),
                              key=len, default=None)
                if claimed is None or claimed in winners:
                    continue
                violations.append(Violation(
                    literal=named[claimed], reason="not_the_argmax",
                    message=f"\"{named[claimed]}\" utpekas som störst/bäst, men det är inte "
                            f"den högsta raden för {primary} i resultatet."))
    return violations


def _find(buckets: dict[str, list[float]], allowed: tuple[str, ...],
          literal: NumberLiteral, scales: tuple[float, ...]) -> int | None:
    """The literal against one bucket set, at each scale it may have been written on."""
    return next((found for found in
                 (_matching_sign(buckets, allowed, literal.value * scale,
                                 literal.tolerance * scale) for scale in scales)
                 if found is not None), None)


def _direction_disagrees(text: str, literal: NumberLiteral, sign: int) -> bool:
    """The B3 hole."""
    if sign == 0:
        return False
    stated = _stated_direction(text, literal.position)
    return stated is not None and stated != sign


# -------------------------------------------------------------------------- validation

def validate_narrative(text: str, results: Iterable[CachedResult],
                       entity_names: Iterable[str] = ()) -> ValidationResult:
    """Check every numeric literal in `text` against the cached result sets."""
    results = list(results)
    by_result = candidates_by_result(results)
    max_rows = max((result.row_count for result in results), default=0)
    literals = extract_numbers(mask_entity_names(text, results, entity_names))

    violations: list[Violation] = []
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
        # thousands and as millions.
        scales = ((1.0, 1e3, 1e6)
                  if literal.implicit_scale_allowed
                  and literal.unit_class not in ("percent", "pe")
                  else (1.0,))
        allowed = _ALLOWED_CLASSES[literal.unit_class]

        # Results are tried in the order the turn produced them, so a figure that several
        # queries could account for is attributed to the first one that could — which is the one
        # the model was looking at when it wrote the sentence.
        source, sign = None, 0

        # Levels first, across every result: a literal that appears in some row is a level
        # wherever it sits, and no sentence makes a level point in a direction.
        for query_id, cells, _derived in by_result:
            if _find(cells, allowed, literal, scales) is not None:
                source, sign = query_id, 0
                break

        if source is None:
            for query_id, _cells, derived in by_result:
                found = _find(derived, allowed, literal, scales)
                if found is not None:
                    source, sign = query_id, found
                    break

        if source is not None:
            if _direction_disagrees(text, literal, sign):
                violations.append(Violation(
                    literal=literal.raw, reason="wrong_direction",
                    message=f"\"{literal.raw}\" finns i resultatet, men åt andra hållet: "
                            f"texten beskriver en förändring i motsatt riktning mot vad "
                            f"datan visar."))
                continue
            attributions.append(Attribution(literal=literal.raw, value=literal.value,
                                            query_id=source))
            continue

        violations.append(Violation(
            literal=literal.raw, reason="not_in_result",
            message=f"\"{literal.raw}\" finns inte i resultatet och är inte en tillåten "
                    f"härledning (summa, medel, förändring eller andel) av något värde "
                    f"i det."))

    # Entity claims, which carry no digits at all and were therefore invisible to everything
    # above.
    violations += check_superlatives(text, results)

    return ValidationResult(ok=not violations, violations=violations,
                            checked=len(literals), attributions=attributions)
