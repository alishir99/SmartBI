"""Tests for the numeric validator — §9.2, the second line of the grounding defence.

The first line is structural: the model never sees the values the chart draws. But the
narrative *is* generated text, so it can still contain a number that came from nowhere. This
is the component that catches that, and these tests are the evidence that it does.

Each test states the failure it prevents, because "the validator has tests" is worth much less
than "the validator provably rejects a plausible fabricated total".
"""

from __future__ import annotations

import pytest

from api.agent.validate import extract_numbers, validate_narrative
from api.result_cache import CachedResult


def result(rows, columns=None, row_count=None) -> CachedResult:
    columns = columns or [
        {"key": "month", "type": "date", "label": "Månad"},
        {"key": "net_sales_sek", "type": "number", "label": "Nettoförsäljning", "unit": "SEK"},
    ]
    return CachedResult(
        query_id="q_test", supplier_id=1, tool="query_sales", tool_args={},
        columns=columns, rows=rows, row_count=row_count if row_count is not None else len(rows),
        truncated=False,
        meta={"time_range": {"from": "2025-07-01", "to": "2026-06-30"}},
    )


MONTHLY = result([
    {"month": "2026-01-01", "net_sales_sek": 3_120_450.25},
    {"month": "2026-02-01", "net_sales_sek": 2_890_100.00},
    {"month": "2026-03-01", "net_sales_sek": 3_450_900.50},
])


# ------------------------------------------------------------------ it accepts truth

def test_exact_value_from_the_result_passes():
    check = validate_narrative(
        "Försäljningen i mars 2026 var 3 450 900,50 kr exkl. moms.", [MONTHLY])
    assert check.ok, check.violations


def test_sum_of_the_rows_is_an_allowed_derivation():
    total = 3_120_450.25 + 2_890_100.00 + 3_450_900.50
    check = validate_narrative(
        f"Totalt under kvartalet uppgick försäljningen till {total:,.2f} kr."
        .replace(",", " ").replace(".", ","), [MONTHLY])
    assert check.ok, check.violations


def test_magnitude_rounding_is_accepted():
    """"3,45 Mkr" is a rounding of 3 450 900,50 — a human would write it that way, and
    rejecting it would make the validator unusable in practice."""
    check = validate_narrative("Mars landade på 3,45 Mkr.", [MONTHLY])
    assert check.ok, check.violations


def test_dates_and_periods_are_not_treated_as_measurements():
    check = validate_narrative(
        "Under perioden 2025-07-01 till 2026-06-30, vecka 12, Q1 2026, "
        "var toppmånaden mars.", [MONTHLY])
    assert check.ok, check.violations


def test_small_counting_integers_are_allowed():
    """"topp 10" and "3 av 6 varumärken" are structure, not data."""
    check = validate_narrative("Här är topp 3 månaderna av 3 möjliga.", [MONTHLY])
    assert check.ok, check.violations


def test_a_year_is_not_a_hallucinated_number():
    check = validate_narrative("Jämfört med 2025 är trenden uppåt.", [MONTHLY])
    assert check.ok, check.violations


# ----------------------------------------------------------------- it rejects fiction

def test_a_fabricated_total_is_rejected():
    """The exact failure this project exists to prevent: a confident, plausible, wrong total."""
    check = validate_narrative(
        "Försäljningen under kvartalet var 12 900 000,00 kr.", [MONTHLY])
    assert not check.ok
    assert "12 900 000,00" in check.violations[0]


def test_a_number_close_but_not_equal_is_rejected():
    check = validate_narrative("Mars var 3 450 999,00 kr.", [MONTHLY])
    assert not check.ok


def test_an_invented_percentage_is_rejected():
    check = validate_narrative("Försäljningen ökade 8,2 % jämfört med förra året.", [MONTHLY])
    assert not check.ok, "no delta column exists in this result, so 8,2 % came from nowhere"


def test_a_delta_present_in_the_result_is_accepted():
    with_delta = result(
        [{"month": "2026-03-01", "net_sales_sek": 3_450_900.50,
          "net_sales_sek_delta_pct": 8.2}],
        columns=[
            {"key": "month", "type": "date", "label": "Månad"},
            {"key": "net_sales_sek", "type": "number", "label": "Netto", "unit": "SEK"},
            {"key": "net_sales_sek_delta_pct", "type": "number", "label": "Förändring",
             "unit": "%"},
        ])
    check = validate_narrative("Ökningen var 8,2 % mot samma period förra året.", [with_delta])
    assert check.ok, check.violations


def test_every_violation_is_reported_not_just_the_first():
    check = validate_narrative("Jan var 9 999 999,00 kr och feb var 8 888 888,00 kr.",
                               [MONTHLY])
    assert not check.ok
    assert len(check.violations) == 2


# ------------------------------------------------------- it spans several tool results

def test_a_number_from_any_result_in_the_turn_is_accepted():
    """One turn may run more than one query; a number from the earlier one is still grounded."""
    regions = result(
        [{"region": "Stockholms län", "net_sales_sek": 33_696_254.00}],
        columns=[{"key": "region", "type": "text", "label": "Län"},
                 {"key": "net_sales_sek", "type": "number", "label": "Netto", "unit": "SEK"}])
    check = validate_narrative(
        "Stockholm stod för 33 696 254,00 kr, och mars gav 3 450 900,50 kr.",
        [MONTHLY, regions])
    assert check.ok, check.violations


# ---------------------------------------------------------------- preview discipline

def test_summing_a_preview_as_if_it_were_everything_is_rejected():
    """The subtle failure mode: the model gets 25 of 1 200 rows and adds them up, presenting
    the partial sum as a total. The sum of the preview is not a value in the full result."""
    preview = result(
        [{"month": "2026-01-01", "net_sales_sek": 1_000.00},
         {"month": "2026-02-01", "net_sales_sek": 2_000.00}],
        row_count=1_200)
    check = validate_narrative("Totalt 3 000,00 kr under perioden.", [preview])
    assert not check.ok, "a partial sum must not pass as a total when row_count > rows seen"


# ------------------------------------------------------------------------ extraction

@pytest.mark.parametrize("text,expected", [
    ("3 450 900,50 kr", 3_450_900.50),
    # The magnitude suffix is resolved during extraction, so "3,45 Mkr" arrives as kronor.
    ("3,45 Mkr", 3_450_000.0),
    ("1 234 st", 1234.0),
    ("8,2 %", 8.2),
])
def test_swedish_number_formats_are_parsed(text, expected):
    numbers = extract_numbers(text)
    assert numbers, f"nothing extracted from {text!r}"
    assert any(abs(n.value - expected) < 0.01 for n in numbers), \
        f"{text!r} -> {[n.value for n in numbers]}"


def test_empty_narrative_is_vacuously_valid():
    check = validate_narrative("", [MONTHLY])
    assert check.ok
    assert check.checked == 0


# --------------------------------------------------------------- names that carry digits

PRODUCT_COLUMNS = [
    {"key": "product", "type": "text", "label": "Produkt"},
    {"key": "net_sales_sek", "type": "number", "label": "Nettoförsäljning", "unit": "SEK"},
]

TOP_LIST = [
    {"product": "Nordström TV N100 Pro", "net_sales_sek": 8824779.51},
    {"product": "Vidar Hörlurar V191 Studio", "net_sales_sek": 4251150.76},
]


def test_model_numbers_in_product_names_are_not_numeric_claims():
    """The regression that suppressed every top-list answer.

    Swedish SKUs carry model numbers, so a top-N answer is mostly digits that are part of
    names. The validator read them as figures and demanded they appear in the result — "191
    St" was the worst, parsing the "St" of "Studio" as the unit `st`. The prose was hidden on
    exactly the question suppliers ask most.
    """
    check = validate_narrative(
        "Nordström TV N100 Pro sålde för 8 824 779,51 kr, följd av Vidar Hörlurar V191 "
        "Studio på 4 251 150,76 kr.",
        [result(TOP_LIST, columns=PRODUCT_COLUMNS)])
    assert check.ok, check.violations


def test_masking_a_name_does_not_excuse_a_fabricated_figure():
    """The mask must not become a hole: only the name is blanked, never a number beside it."""
    check = validate_narrative(
        "Nordström TV N100 Pro sålde för 9 999 999 kr.",
        [result(TOP_LIST, columns=PRODUCT_COLUMNS)])
    assert not check.ok
    assert "9 999 999 kr" in check.violations[0]


# --------------------------------------------------------------- provenance per tool call

def named(query_id: str, rows, columns=None, row_count=None) -> CachedResult:
    entry = result(rows, columns=columns, row_count=row_count)
    entry.query_id = query_id
    return entry


REGION_COLUMNS = [
    {"key": "region", "type": "text", "label": "Län"},
    {"key": "net_sales_sek", "type": "number", "label": "Netto", "unit": "SEK"},
]


def test_each_accepted_figure_names_the_query_that_licensed_it():
    """The B8 fix. `validate_narrative` has always checked the prose against every result the
    turn produced, while the card carried one `query_id` — so a number grounded in result A
    shipped beside a chart of result B and a source chip describing B. The mapping existed
    inside the check and was thrown away at the last step."""
    months = named("q_months", [
        {"month": "2026-03-01", "net_sales_sek": 3_450_900.50}])
    regions = named("q_regions", [
        {"region": "Stockholms län", "net_sales_sek": 33_696_254.00}],
        columns=REGION_COLUMNS)

    check = validate_narrative(
        "Mars gav 3 450 900,50 kr och Stockholm stod för 33 696 254,00 kr.",
        [months, regions])

    assert check.ok, check.violations
    assert [(a.literal, a.query_id) for a in check.attributions] == [
        ("3 450 900,50 kr", "q_months"),
        ("33 696 254,00 kr", "q_regions"),
    ]
    assert check.query_ids() == ["q_months", "q_regions"]


def test_a_figure_several_queries_could_explain_is_attributed_to_the_first():
    """Ambiguity is resolved by order rather than left unattributed: the turn ran the queries
    in sequence, and the first one that accounts for the figure is the one the model was
    looking at when it wrote the sentence."""
    first = named("q_first", [{"month": "2026-01-01", "net_sales_sek": 1_000.00}])
    second = named("q_second", [{"month": "2026-02-01", "net_sales_sek": 1_000.00}])

    check = validate_narrative("Det blev 1 000,00 kr.", [first, second])

    assert check.ok
    assert check.attributions[0].query_id == "q_first"


def test_two_results_sharing_a_query_id_do_not_erase_each_other():
    """Ids are unique in production, and this must not *depend* on it. Keying the candidate
    sets by id would make one result silently overwrite the other, and a perfectly grounded
    number would be reported as a fabrication — a validator failing closed on a bookkeeping
    detail is worse than one that never looked."""
    a = named("q_same", [{"month": "2026-01-01", "net_sales_sek": 1_111.00}])
    b = named("q_same", [{"month": "2026-02-01", "net_sales_sek": 2_222.00}],
              row_count=1)

    check = validate_narrative("Först 1 111,00 kr, sedan 2 222,00 kr.", [a, b])

    assert check.ok, check.violations
    assert len(check.attributions) == 2


def test_a_fabricated_figure_is_attributed_to_nothing():
    months = named("q_months", [{"month": "2026-03-01", "net_sales_sek": 3_450_900.50}])

    check = validate_narrative("Mars gav 9 900 000,00 kr.", [months])

    assert not check.ok
    assert check.attributions == []
