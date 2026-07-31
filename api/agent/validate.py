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

from ..result_cache import PREVIEW_ROWS, CachedResult

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


_PERCENT_WORDS = {"%", "procent"}
_MONEY_WORDS = {"kr", "sek", "kronor"}
_COUNT_WORDS = {"st", "styck", "enheter"}


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

        if suffix in _PERCENT_WORDS:
            unit_class = "percent"
        elif suffix in _MONEY_WORDS or suffix in SCALES:
            # A magnitude suffix is always money here: "3,45 Mkr", "2 tusen". No percentage
            # is written with one.
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


def candidates_by_result(
        results: Iterable[CachedResult]) -> list[tuple[str, dict[str, list[float]]]]:
    """Every value the model may legitimately have used, kept per result so an accepted
    literal can name the query that licensed it.

    A list of pairs, not a dict keyed by `query_id`: two results sharing an id would
    overwrite each other and report a grounded number as a fabrication.
    """
    by_result: list[tuple[str, dict[str, list[float]]]] = []

    for result in results:
        buckets: dict[str, list[float]] = {"money": [], "percent": [], "count": [],
                                           "unknown": []}
        unit_of = {column["key"]: _class_of_unit(column.get("unit"))
                   for column in result.columns}

        def add(bucket: str, *values: float, _buckets=buckets) -> None:
            _buckets[bucket].extend(values)

        add("count", float(result.row_count))

        # Whether the rows we hold ARE the whole result. Aggregate derivations below are only
        # sound when they are: if the tool capped the result at MAX_ROWS, the sum of what we
        # have is not the total, and accepting it would let "totalt X kr" pass while being
        # the sum of an arbitrary subset. That is precisely the failure the system prompt
        # warns the model about, so the validator must not quietly permit it.
        complete = len(result.rows) >= result.row_count

        # `limit` is the one tool argument that legitimately shows up in prose ("topp 10").
        limit = result.tool_args.get("limit")
        if isinstance(limit, int) and not isinstance(limit, bool):
            add("count", float(limit))

        numeric_keys = result.numeric_columns()
        for key in numeric_keys:
            values = _numbers_in(result.rows, key)
            if not values:
                continue

            own = unit_of.get(key, "unknown")
            add(own, *values)                                           # the cells themselves

            # Shares and pairwise deltas are licensed only over the rows the model saw: a
            # 500-row result otherwise yields ~1 000 percentages blanketing [-100, 100], and
            # the model cannot honestly derive a share for a row it never received. Whole-
            # series derivations below stay over every row — the envelope hands those over.
            seen = values[:PREVIEW_ROWS]

            if complete:
                total = sum(values)
                # A sum or a mean is the same kind of quantity as the column it came from:
                # summing kronor gives kronor. A sum of percentages is meaningless, but
                # harmless to keep — nothing in prose quotes one.
                add(own, total, total / len(values))
                if total:
                    # Share is a percentage NO MATTER what the column's unit is: this is the
                    # derivation that turns kronor into a proportion, and it is the reason a
                    # `%` literal has any legitimate claim on a money column at all.
                    add("percent", *(100.0 * value / total for value in seen))

            # delta between adjacent rows stays available either way — it is local to two rows
            # and does not depend on holding the whole series.
            for previous, current in pairwise(seen):
                add(own, current - previous)
                if previous:
                    add("percent", 100.0 * (current - previous) / abs(previous))

            if complete:
                # first→last is a statement about the series as a whole, so it needs the
                # whole series.
                add(own, values[-1] - values[0])
                if values[0]:
                    add("percent", 100.0 * (values[-1] - values[0]) / abs(values[0]))

            # delta against the comparison period, when compare_to produced a paired column.
            # The percentage form already exists as a cell (`*_delta_pct`, computed in SQL);
            # only the absolute difference needs deriving.
            compare_key = f"{key}_compare"
            if compare_key in numeric_keys:
                for row in result.rows:
                    now, before = row.get(key), row.get(compare_key)
                    if (isinstance(now, (int, float)) and not isinstance(now, bool)
                            and isinstance(before, (int, float))
                            and not isinstance(before, bool)):
                        add(unit_of.get(key, "unknown"), float(now) - float(before))

        # Candidates stay SIGNED. The magnitude check looks for the literal at either sign
        # (see `_matching_sign`), so prose may still say "ökade med 4,2 %" for a delta of
        # -4.2 — but storing the mirror image would erase the very fact the direction check
        # needs. Sign-blind matching is a property of the *lookup*, not of the data.
        for values in buckets.values():
            values.sort()
        by_result.append((result.query_id, buckets))

    return by_result


def _class_of_unit(unit: str | None) -> str:
    """A column's unit, as the same vocabulary a literal is classified into."""
    if unit == "%":
        return "percent"
    if unit == "SEK":
        return "money"
    if unit == "st":
        return "count"
    return "unknown"


# A literal may only match candidates of its own kind, so a `%` claim cannot match a raw SEK
# cell. Without this, ~32 % of fabricated percentages passed. `unknown` stays permissive
# both ways: a bare "12,4" is no evidence either way, and this file prefers admitting a
# true-ish number to suppressing a true one.
_ALLOWED_CLASSES: dict[str, tuple[str, ...]] = {
    "percent": ("percent", "unknown"),
    "money": ("money", "unknown"),
    "count": ("count", "unknown"),
    "unknown": ("money", "percent", "count", "unknown"),
}


def _matches(candidates: Sequence[float], value: float, tolerance: float) -> bool:
    index = bisect.bisect_left(candidates, value - tolerance)
    return index < len(candidates) and candidates[index] <= value + tolerance


def _matching_sign(buckets: dict[str, list[float]], allowed: tuple[str, ...],
                   value: float, tolerance: float) -> int | None:
    """Whether the value matches, and with which sign it was found.

    Returns +1 or -1 for the sign of the candidate that matched, or None for no match. The
    sign is what `_direction_disagrees` needs: candidates are mirrored across zero so the
    *magnitude* check stays indifferent to how the prose phrases a change, and the direction
    is then checked once, against the verb, where the information actually lives.
    """
    for bucket in allowed:
        values = buckets.get(bucket)
        if not values:
            continue
        # Both signs are tried explicitly, which is what keeps the magnitude check indifferent
        # to phrasing now that the candidates are no longer stored mirrored. "ökade med 4,2 %"
        # and a stored delta of -4.2 still match here; whether that phrasing is *honest* is
        # the direction check's question, not this one's.
        positive = _matches(values, abs(value), tolerance)
        negative = _matches(values, -abs(value), tolerance)
        if positive and negative:
            return 0    # the data holds both; direction is unconstrained
        if positive:
            return 1
        if negative:
            return -1
    return None


# Swedish direction verbs, as they appear in the prose a sales model writes. Deliberately
# short: this is a check on the *most consequential* claim in a sales answer, not a general
# sentiment model, and every word here has to be unambiguous about direction on its own.
_RISING = ("ökade", "ökat", "ökar", "ökning", "steg", "stigit", "stiger", "växte", "växt",
           "växer", "tillväxt", "uppgång", "förbättrades", "förbättring", "starkare",
           "högre", "upp")
_FALLING = ("minskade", "minskat", "minskar", "minskning", "föll", "fallit", "faller",
            "sjönk", "sjunkit", "sjunker", "tappade", "tappat", "tappar", "tapp",
            "nedgång", "försämrades", "försämring", "svagare", "lägre", "ned", "ner")

# How far back from a literal to look for the verb that gives it a direction. One clause,
# roughly: "försäljningen ökade med 8,2 %" is 26 characters, and widening this far enough to
# span a sentence boundary would start reading the direction of a *different* claim.
_DIRECTION_WINDOW = 60


def _stated_direction(text: str, position: int) -> int | None:
    """+1 for a rise, -1 for a fall, None when the prose does not say.

    Read from the words *before* the literal, because Swedish puts the verb first: "steg med
    8,2 %", "tappade 4 procent". Looking forward as well would catch the verb belonging to the
    next clause.
    """
    window = text[max(0, position - _DIRECTION_WINDOW):position].lower()
    rising = max((window.rfind(word) for word in _RISING), default=-1)
    falling = max((window.rfind(word) for word in _FALLING), default=-1)
    if rising < 0 and falling < 0:
        return None
    # The nearest verb wins: "försäljningen ökade i mars men minskade med 8,2 % i april".
    return 1 if rising > falling else -1


# Swedish superlatives that name a winner. "störst" and "bäst" are the two a sales answer
# actually reaches for; the rest are the forms a model varies into.
_SUPERLATIVES = ("störst", "störste", "bäst", "bäste", "högst", "toppar", "topp",
                 "mest sålda", "mest sålde", "ledande", "vinnare")

# How far after a superlative to look for the entity it is claiming about. One clause:
# "den bäst säljande produkten är Nordström TV N100 Pro" is about 50 characters.
_SUPERLATIVE_WINDOW = 90


def check_superlatives(text: str, results: Iterable[CachedResult]) -> list[str]:
    """Assert that a named winner really is the argmax of the full result.

    The other half of the B3 gap. `validate_narrative` checks digits, so *"den bäst säljande
    produkten är X"* was completely unverifiable — no number appears in it at all, and it is
    among the most common things a supplier asks. The model sees 25 of up to 500 rows, so
    before the preview carried server-computed extremes it was answering superlatives from a
    sample and naming the wrong row while the chart drew the right one.

    Deliberately conservative, because a false rejection here suppresses a correct answer:
    it fires only when a superlative word is followed, within one clause, by a name that the
    result actually contains in a label column. An unrecognised name, a superlative about
    something that is not a row, or a result with no obvious primary measure all stay silent.
    A guard that only speaks when it is sure is worth more than one that argues.
    """
    violations: list[str] = []
    lowered = text.lower()

    for result in results:
        measures = result.numeric_columns()
        labels = result.label_columns()
        if not measures or not labels or len(result.rows) < 2:
            continue

        # The primary measure is the first numeric column that is not a derived comparison —
        # the same choice propose_chart makes, so prose and chart are judged against one axis.
        primary = next((key for key in measures
                        if not key.endswith(("_compare", "_delta_pct"))), None)
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
                violations.append(
                    f"\"{named[claimed]}\" utpekas som störst/bäst, men det är inte den "
                    f"högsta raden för {primary} i resultatet."
                )
    return violations


def _direction_disagrees(text: str, literal: NumberLiteral, sign: int) -> bool:
    """The B3 hole. `candidates` are mirrored across zero, so a delta of -8.2 licenses the
    literal "8,2" — and the *verb* is what says which way it went. Nothing read the verb, so
    "Försäljningen ÖKADE med 8,2 %" passed against data showing a fall of exactly that much.
    That is the single most consequential claim in a sales answer, and it was unverifiable.

    Only fires when the matched candidate exists at one sign only. When the data holds both
    +x and -x there is nothing to contradict, and asserting otherwise would invent a
    violation out of an ambiguity.
    """
    if sign == 0:
        return False
    stated = _stated_direction(text, literal.position)
    return stated is not None and stated != sign


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
        #
        # A percentage never gets the implicit rescaling. That allowance exists so an
        # unsuffixed money figure can be read as millions, and applying it to a `%` literal is
        # what let "Marknadsandelen var 2,89 %" match a revenue of 2 890 100. A percentage is
        # written at the scale it means.
        scales = ((1.0, 1e3, 1e6)
                  if literal.implicit_scale_allowed and literal.unit_class != "percent"
                  else (1.0,))
        allowed = _ALLOWED_CLASSES[literal.unit_class]

        # Results are tried in the order the turn produced them, so a figure that several
        # queries could account for is attributed to the first one that could — which is the
        # one the model was looking at when it wrote the sentence.
        source, sign = None, 0
        for query_id, buckets in by_result:
            found = next(
                (found for found in
                 (_matching_sign(buckets, allowed, literal.value * scale,
                                 literal.tolerance * scale) for scale in scales)
                 if found is not None),
                None)
            if found is not None:
                source, sign = query_id, found
                break

        if source is not None:
            if _direction_disagrees(text, literal, sign):
                violations.append(
                    f"\"{literal.raw}\" finns i resultatet, men åt andra hållet: texten "
                    f"beskriver en förändring i motsatt riktning mot vad datan visar."
                )
                continue
            attributions.append(Attribution(literal=literal.raw, value=literal.value,
                                            query_id=source))
            continue

        violations.append(
            f"\"{literal.raw}\" finns inte i resultatet och är inte en tillåten härledning "
            f"(summa, medel, förändring eller andel) av något värde i det."
        )

    # Entity claims, which carry no digits at all and were therefore invisible to everything
    # above. "Den bäst säljande produkten är X" is among the most common questions a supplier
    # asks and was the one kind of answer nothing could check.
    violations += check_superlatives(text, results)

    return ValidationResult(ok=not violations, violations=violations,
                            checked=len(literals), attributions=attributions)
