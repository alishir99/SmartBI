"""Numeric validation of the model's prose (§9.2)."""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise

from ..config import settings
from ..i18n import current as current_language
from ..result_cache import PREVIEW_ROWS, CachedResult

# Number grammar is per-language: Swedish writes "1 234,5 Mkr", English "1,234.5M". Reading one
# with the other's rules turns a real figure into a false rejection - the expensive direction.

# Space, no-break space, narrow no-break space, thin space.
_SPACES = " \\u00a0\\u202f\\u2009"


@dataclass(frozen=True)
class NumberGrammar:
    """How one language writes a measurement."""

    #: suffix -> multiplier, e.g. "mkr" -> 1e6
    scales: dict[str, float]
    percent: frozenset[str]
    percent_points: frozenset[str]
    money: frozenset[str]
    count: frozenset[str]
    #: character class of everything that groups thousands
    thousands: str
    #: the decimal separator; anything else in `frac` position groups thousands
    decimal: str
    #: spans whose digits are never measurements
    masks: tuple[re.Pattern[str], ...]

    @property
    def units(self) -> frozenset[str]:
        return self.percent | self.percent_points | self.money | self.count

    @property
    def number(self) -> re.Pattern[str]:
        # Longest suffix first, so "kronor" isn't read as "kr" plus stray letters. The trailing
        # `(?!\w)` keeps a one-letter magnitude honest: without it "12 months" reads as 12M.
        alternatives = "|".join(
            re.escape(word) for word in sorted([*self.scales, *self.units],
                                               key=len, reverse=True))
        return re.compile(
            r"(?<![\d.,])"
            rf"(?P<int>\d{{1,3}}(?:{self.thousands}\d{{3}})+|\d+)"
            r"(?P<frac>[.,]\d+)?"
            rf"(?!\d)(?:\s*(?P<suffix>{alternatives})(?!\w))?",
            re.I,
        )


_SV_MONTHS = (r"jan(?:uari)?|feb(?:ruari)?|mar(?:s)?|apr(?:il)?|maj|jun(?:i)?|jul(?:i)?|"
              r"aug(?:usti)?|sep(?:t|tember)?|okt(?:ober)?|nov(?:ember)?|dec(?:ember)?")
_EN_MONTHS = (r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
              r"aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?")

# ISO shapes are language-independent, so both grammars start from these.
_ISO_MASKS = (
    re.compile(r"\d{4}-\d{2}-\d{2}"),                       # ISO date
    re.compile(r"\d{4}-\d{2}\b"),                           # ISO month
    re.compile(r"#\s*\d+"),                                  # rank chip
)


def _month_masks(months: str) -> tuple[re.Pattern[str], ...]:
    return (re.compile(rf"\d{{1,2}}\s*(?:{months})\.?", re.I),      # "14 jan"
            re.compile(rf"(?:{months})\.?\s*\d{{4}}", re.I))         # "jun 2026"


SV = NumberGrammar(
    scales={"mdkr": 1e9, "miljarder": 1e9, "miljard": 1e9,
            "mkr": 1e6, "msek": 1e6, "miljoner": 1e6, "miljon": 1e6, "mnkr": 1e6,
            "tkr": 1e3, "ksek": 1e3, "tusen": 1e3},
    percent=frozenset({"%", "procent"}),
    # Longer than "procent" and therefore matched before it: "12,2 procentenheter" must not
    # be read as 12,2 %.
    percent_points=frozenset({"p.e.", "procentenheter", "procentenhet"}),
    money=frozenset({"kr", "sek", "kronor"}),
    count=frozenset({"st", "styck", "stycken", "enheter"}),
    # The period is here because a model occasionally reaches for it ("12.400.000").
    thousands=f"[{_SPACES}.]",
    decimal=",",
    masks=(*_ISO_MASKS, *_month_masks(_SV_MONTHS),
           re.compile(r"\b(?:v|vecka|vv)\.?\s*\d{1,2}\b", re.I),   # ISO week
           re.compile(r"\b[qk][1-4]\b", re.I),                      # Q2 / K2
           re.compile(r"\bkvartal\s*\d\b", re.I),
           re.compile(r"\b(?:nr|plats|placering)\.?\s*\d+\b", re.I),
           re.compile(r"\btopp\s*\d+\b", re.I),   # "topp 10" is a limit, not a value
           re.compile(r"\b\d+:[ae]\b")),           # ordinal "2:a"
)

EN = NumberGrammar(
    scales={"bn": 1e9, "billion": 1e9, "billions": 1e9,
            "m": 1e6, "mn": 1e6, "million": 1e6, "millions": 1e6,
            "k": 1e3, "thousand": 1e3, "thousands": 1e3},
    percent=frozenset({"%", "percent", "pct"}),
    percent_points=frozenset({"pp", "p.p.", "percentage point", "percentage points"}),
    # The deployment's own currency code, built at import from the same setting the tools
    # stamp onto every result.
    money=frozenset({settings.app_currency.lower(), "units of currency"}),
    count=frozenset({"pcs", "units", "unit"}),
    # No period: in English a period is the decimal point, and treating it as a grouper is
    # exactly the misread this grammar exists to prevent.
    thousands=f"[{_SPACES},]",
    decimal=".",
    masks=(*_ISO_MASKS, *_month_masks(_EN_MONTHS),
           re.compile(r"\b(?:w|wk|week)\.?\s*\d{1,2}\b", re.I),
           re.compile(r"\bq[1-4]\b", re.I),
           re.compile(r"\bquarter\s*\d\b", re.I),
           re.compile(r"\b(?:no|rank|position)\.?\s*\d+\b", re.I),
           re.compile(r"\btop\s*\d+\b", re.I),
           re.compile(r"\b\d+(?:st|nd|rd|th)\b", re.I)),          # ordinal "2nd"
)

GRAMMARS: dict[str, NumberGrammar] = {"sv": SV, "en": EN}


def grammar() -> NumberGrammar:
    """The grammar for the language this turn is being answered in."""
    return GRAMMARS.get(current_language(), SV)

# Bare integers in this range with no unit are read as calendar years, not as measurements.
_YEAR_MIN, _YEAR_MAX = 1990, 2099

# A bare integer no larger than this, and no larger than the row count, is accepted as a count
# of things on screen ("de 10 största") rather than a measurement.
_MAX_COUNTING_INTEGER = 50

# Guards against floating-point noise once a value has been multiplied by 1e6.
_FLOAT_EPSILON = 1e-6

# Ceiling on the tolerance a round number may imply, relative to itself: loose enough to keep
# honest roundings, tight enough that it can't launder a fabricated figure.
_ROUND_NUMBER_MAX_REL = 0.02


@dataclass(frozen=True)
class NumberLiteral:
    raw: str
    value: float
    tolerance: float
    #: True when the literal carried no magnitude suffix, so "12,4" may still mean 12,4 Mkr.
    implicit_scale_allowed: bool
    #: True when the literal is a plain integer with no unit at all.
    bare_integer: bool
    #: "percent" | "money" | "count" | "unknown", read off the unit it carried.
    unit_class: str = "unknown"
    #: Character offset in the (masked) narrative, so the words around it can be read.
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
    #: One entry per accepted numeric literal, in the order they appear in the prose.
    attributions: list[Attribution] = field(default_factory=list)


def mask_entity_names(text: str, results: Iterable[CachedResult],
                      extra_names: Iterable[str] = ()) -> str:
    """Blank out entity names carried by the results before numbers are extracted."""
    names = {value for result in results for row in result.rows
             for value in row.values()
             if isinstance(value, str) and any(char.isdigit() for char in value)}
    # Names the turn *resolved* but that no row carries (a filter, not a group-by column) also
    # need masking, or a product like "N178 Pro" gets its digits read as a number.
    names |= {name for name in extra_names
              if isinstance(name, str) and any(char.isdigit() for char in name)}
    masked = text
    for name in sorted(names, key=len, reverse=True):
        masked = re.sub(re.escape(name), lambda match: " " * len(match.group(0)),
                        masked, flags=re.I)
    return masked


def mask_non_measurements(text: str) -> str:
    """Blank out dates, ISO weeks, quarters, ranks and "top N", preserving length."""
    masked = text
    for pattern in grammar().masks:
        masked = pattern.sub(lambda match: " " * len(match.group(0)), masked)
    return masked


def _parse_number(integer_part: str, fraction_part: str | None,
                  rules: NumberGrammar) -> tuple[float, int]:
    """Return (value, decimal count), read the way `rules` writes numbers."""
    digits = re.sub(rules.thousands, "", integer_part)
    if fraction_part is None:
        return float(digits), 0

    separator, fraction = fraction_part[0], fraction_part[1:]
    # Not the decimal separator, and exactly three digits: this is a thousands group the
    # integer pattern missed, not a fraction ("12.400" is 12400 in Swedish, 12.4 in English).
    if separator != rules.decimal and len(fraction) == 3:
        return float(digits + fraction), 0
    return float(f"{digits}.{fraction}"), len(fraction)


def extract_numbers(text: str) -> list[NumberLiteral]:
    """Every numeric claim in the narrative, with the tolerance its own precision implies."""
    rules = grammar()
    literals: list[NumberLiteral] = []
    for match in rules.number.finditer(mask_non_measurements(text)):
        value, decimals = _parse_number(match.group("int"), match.group("frac"), rules)
        suffix = (match.group("suffix") or "").lower()
        scale = rules.scales.get(suffix, 1.0)
        has_unit = bool(suffix)

        value *= scale
        # Half a unit of the literal's last decimal place, in the literal's own magnitude.
        tolerance = 0.5 * (10.0 ** -decimals) * scale

        if not decimals:
            digits = match.group("int")
            stripped = "".join(c for c in digits if c.isdigit()).rstrip("0")
            zeros = len(digits.replace(" ", "")) - len(stripped) if stripped else 0
            if zeros:
                # A round integer's trailing zeros ARE the claim: "530 000" is how anyone
                # reports 529 868, so it's read to its last *significant* digit instead.
                implied = 0.5 * (10.0 ** zeros) * scale
                tolerance = max(tolerance, min(implied, abs(value) * _ROUND_NUMBER_MAX_REL))
        tolerance += abs(value) * _FLOAT_EPSILON

        if suffix in rules.percent:
            unit_class = "percent"
        elif suffix in rules.percent_points:
            unit_class = "pe"
        elif suffix in rules.money or suffix in rules.scales:
            # A magnitude suffix is always money here: "3,45 Mkr" - no percentage is written
            # with one.
            unit_class = "money"
        elif suffix in rules.count:
            unit_class = "count"
        else:
            unit_class = "unknown"

        literals.append(NumberLiteral(
            raw=match.group(0).strip(),
            value=value,
            tolerance=tolerance,
            implicit_scale_allowed=suffix not in rules.scales,
            bare_integer=decimals == 0 and not has_unit,
            unit_class=unit_class,
            position=match.start(),
        ))
    return literals



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

    Levels and changes are kept apart. A level read out of a row has no direction - "Nordström
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
            # The difference between two percentages is percentage points, not percent -
            # keeping them in one bucket let a p.p. change validate as if it were a percent.
            delta_class = "pe" if own == "percent" else own
            # A column that IS a change keeps its direction; every other cell is a level (a
            # total, a mean, a share). Only a difference points anywhere.
            level = add if _is_change_column(key, own) else add_cell
            level(own, *values)

            # Shares and pairwise deltas are licensed only over the rows the model saw: the
            # model cannot honestly derive a share for a row it never received.
            seen = values[:PREVIEW_ROWS]

            if complete:
                total = sum(values)
                # A sum or a mean is the same kind of quantity as the column it came from.
                level(own, total, total / len(values))
                if total:
                    # Share is a percentage no matter the column's unit - the derivation that
                    # gives a `%` literal any legitimate claim on a money column at all.
                    add_cell("percent", *(100.0 * value / total for value in seen))

            # Delta between adjacent rows stays available either way - it's local to two rows
            # and doesn't depend on holding the whole series.
            for previous, current in pairwise(seen):
                add(delta_class, current - previous)
                if previous:
                    add("percent", 100.0 * (current - previous) / abs(previous))

            if complete:
                # first→last is a statement about the series as a whole, so it needs the
                # whole series.
                add(delta_class, values[-1] - values[0])
                if values[0]:
                    add("percent", 100.0 * (values[-1] - values[0]) / abs(values[0]))

            # Delta against the comparison period, when compare_to produced a paired column.
            compare_key = f"{key}_compare"
            if compare_key in numeric_keys:
                for row in result.rows:
                    now, before = row.get(key), row.get(compare_key)
                    if (isinstance(now, (int, float)) and not isinstance(now, bool)
                            and isinstance(before, (int, float))
                            and not isinstance(before, bool)):
                        add(delta_class, float(now) - float(before))

        # Candidates stay signed, so a match can report which direction the data supports.
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
    if unit and unit not in ("st", "%"):
        return "money"
    if unit == "st":
        return "count"
    return "unknown"


# A literal only matches candidates of its own kind - a `%` claim can't match a raw SEK cell,
# nor a percentage-point delta now that "p.e." is its own class.
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
        # Both signs tried explicitly, so the magnitude check stays indifferent to phrasing.
        positive = _matches(values, abs(value), tolerance)
        negative = _matches(values, -abs(value), tolerance)
        if positive and negative:
            return 0
        if positive:
            return 1
        if negative:
            return -1
    return None


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
    return 1 if rising > falling else -1


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

        # Same choice propose_chart makes, so prose and chart are judged against one axis.
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
                # Longest known name in the window wins, so "Nordström TV N100 Pro" beats a
                # bare "Nordström".
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

        scales = ((1.0, 1e3, 1e6)
                  if literal.implicit_scale_allowed
                  and literal.unit_class not in ("percent", "pe")
                  else (1.0,))
        allowed = _ALLOWED_CLASSES[literal.unit_class]

        source, sign = None, 0

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

    violations += check_superlatives(text, results)

    return ValidationResult(ok=not violations, violations=violations,
                            checked=len(literals), attributions=attributions)
