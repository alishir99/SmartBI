"""Re-derivation of every literal in golden_questions.yaml."""

from __future__ import annotations

import pytest

from eval import cases
from eval.oracle import Oracle

pytestmark = pytest.mark.skipif(
    not (Oracle().data_dir / "fact_sales_line.csv").exists(),
    reason=("data/generated is missing — regenerate with: "
            "python scripts/generate_data.py --seed 42"),
)

GOLDEN = cases.load("golden").cases
CASE_IDS = [case["id"] for case in GOLDEN]


@pytest.fixture(scope="module")
def oracle() -> Oracle:
    return Oracle()


@pytest.fixture(scope="module")
def derived(oracle) -> dict[str, dict]:
    """Every derivation, run once."""
    return {case["id"]: oracle.derive(case["derivation"]) for case in GOLDEN}


def case_by_id(case_id: str) -> dict:
    return next(case for case in GOLDEN if case["id"] == case_id)


def within(expected: float, actual: float, tolerance_pct: float) -> bool:
    """Tolerances are relative to the expected magnitude, matching how the YAML states them."""
    if expected == 0:
        return actual == 0
    return abs(actual - expected) <= abs(expected) * tolerance_pct / 100


def report(case_id: str, what: str, expected, actual, tolerance_pct: float) -> str:
    """The whole point of a custom message here: the reader has to be able to tell "the data was
    regenerated" from "this literal was never right", and that needs the delta."""
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)) and expected:
        drift = f"{100 * (actual - expected) / expected:+.2f} %"
    else:
        drift = "n/a"
    return (f"{case_id}: {what} drifted\n"
            f"    expects (golden_questions.yaml): {expected!r}\n"
            f"    derived (eval/oracle.py):        {actual!r}\n"
            f"    drift: {drift}   tolerance: ±{tolerance_pct} %\n"
            f"    if the data was regenerated, update the literal; otherwise the "
            f"literal was never supported by the data")


def numeric_from(spec: dict, result: dict):
    """Which key of the derivation bag a `numeric` expectation refers to."""
    if spec.get("unit") == "%" and result.get("share_pct") is not None:
        return result["share_pct"]
    return result.get("value")


# ---------------------------------------------------------------- structural


def test_every_golden_case_has_a_unique_id():
    assert len(CASE_IDS) == len(set(CASE_IDS))


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_derivation_runs(case_id, derived):
    """A derivation that raises, or that produces none of the keys its expectations name, is a
    broken traceability claim even before any number is compared."""
    assert derived[case_id], f"{case_id}: derivation produced nothing"


# ---------------------------------------------------------------- values


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_numeric_expectation_still_derives(case_id, derived):
    spec = case_by_id(case_id)["expects"].get("numeric")
    if spec is None:
        pytest.skip("no numeric expectation")
    actual = numeric_from(spec, derived[case_id])
    assert actual is not None, f"{case_id}: derivation produced no value to compare"
    tolerance = spec["tolerance_pct"]
    assert within(spec["value"], actual, tolerance), report(
        case_id, f"numeric ({spec.get('unit')})", spec["value"], actual, tolerance)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_delta_pct_expectation_still_derives(case_id, derived):
    spec = case_by_id(case_id)["expects"].get("delta_pct")
    if spec is None:
        pytest.skip("no delta_pct expectation")
    actual = derived[case_id].get("delta_pct")
    assert actual is not None, (
        f"{case_id}: expects a delta but the derivation has no `compare_where` window")
    tolerance = spec["tolerance_pct"]
    # Sign matters more than magnitude here: mom_june_vs_may_2026 exists to catch an answer that
    # reports a decline as growth, and a tolerance band could otherwise straddle zero.
    assert (actual < 0) == (spec["value"] < 0), report(
        case_id, "delta_pct sign", spec["value"], actual, tolerance)
    assert within(spec["value"], actual, tolerance), report(
        case_id, "delta_pct", spec["value"], actual, tolerance)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_series_points_still_derive(case_id, derived):
    spec = case_by_id(case_id)["expects"].get("series")
    if spec is None:
        pytest.skip("no series expectation")
    tolerance = spec.get("tolerance_pct", 0.5)
    # `by()` yields dates as date objects and years as ints; YAML keys are always strings.
    actual_points = {str(label): value for label, value in (derived[case_id].get("series")
                                                            or {}).items()}
    assert actual_points, f"{case_id}: derivation produced no series"

    drifted = []
    for label, expected in spec["points"].items():
        label = str(label)
        if label not in actual_points:
            drifted.append(f"{label}: absent from the derived series "
                           f"(derived labels: {sorted(actual_points)})")
        elif not within(expected, actual_points[label], tolerance):
            drifted.append(report(case_id, f"series[{label!r}] (grouped by "
                                           f"{spec.get('group_by')})",
                                  expected, actual_points[label], tolerance))
    assert not drifted, "\n".join(drifted)


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_top_n_ordering_still_derives(case_id, derived):
    spec = case_by_id(case_id)["expects"].get("top_n")
    if spec is None:
        pytest.skip("no top_n expectation")
    expected = list(spec["order"])
    actual = derived[case_id].get("order")
    assert actual is not None, (
        f"{case_id}: expects an ordering but the derivation sets no `top`")
    # `prefix_only` means the case pins the head of the ranking and is indifferent to the tail —
    # the useful contract when the ordering below the cut is near-tied.
    compared = actual[:len(expected)] if spec.get("prefix_only") else actual
    pairs = zip(expected, compared, strict=False)
    first_diff = next((i for i, (a, b) in enumerate(pairs) if a != b), len(compared))
    assert compared == expected, (
        f"{case_id}: top_n ordering by {spec.get('group_by')} drifted "
        f"(prefix_only={bool(spec.get('prefix_only'))})\n"
        f"    expects:  {expected}\n"
        f"    derived:  {actual}\n"
        f"    first difference at position {first_diff}")


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_rank_and_peer_count_still_derive(case_id, derived):
    expects = case_by_id(case_id)["expects"]
    checked = False
    for key in ("rank", "n_brands"):
        if key not in expects:
            continue
        checked = True
        actual = derived[case_id].get(key)
        assert actual == expects[key], report(case_id, key, expects[key], actual, 0.0)
    if not checked:
        pytest.skip("no rank or n_brands expectation")


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_market_share_cases_stay_above_the_k_threshold(case_id, derived):
    """golden_questions.yaml states that none of its market-share questions should trip the
    k-anonymity guard — the thin subcategory lives in adversarial.yaml."""
    share = case_by_id(case_id)["derivation"].get("market_share")
    if share is None:
        pytest.skip("not a market-share case")
    n_brands = derived[case_id]["n_brands"]
    assert n_brands >= 5, (
        f"{case_id}: subcategory {share['subcategory']!r} now holds {n_brands} brands, "
        f"below the k-threshold of 5 — this question would be suppressed, so it no longer "
        f"belongs in the golden set")
