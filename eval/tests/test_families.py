"""Pass rates per check family — the resolution the case-level score destroys."""

from __future__ import annotations

from eval import grade
from eval.grade import CaseResult, Failure, family_of, family_rates


def result(checks: list[str], failed: list[str] = ()) -> CaseResult:
    return CaseResult(
        case_id="c", suite="golden", question="q",
        checks_run=list(checks),
        failures=[Failure(check, "boom") for check in failed])


def test_every_graded_key_has_a_family():
    """The guard run_eval.py enforces before any HTTP happens, pinned as a unit test too."""
    assert grade.GRADED_KEYS <= set(grade.CHECK_FAMILIES)


def test_the_two_families_that_matter_are_kept_apart():
    """The header's claim, as an assertion: values-from-the-cache and words-about-them are never in
    the same bucket."""
    assert grade.CHECK_FAMILIES["series"] == "grounded"
    assert grade.CHECK_FAMILIES["top_n"] == "grounded"
    assert grade.CHECK_FAMILIES["suppressed"] == "grounded"
    assert grade.CHECK_FAMILIES["numeric"] == "prose"
    assert grade.CHECK_FAMILIES["must_not_contain"] == "prose"


def test_rates_are_counted_per_check_not_per_case():
    """A case asserting six things and failing one is not the same evidence as a case asserting one
    thing and failing it, and a per-case rate cannot tell them apart."""
    rates = family_rates([
        result(["series", "top_n", "rank"], failed=["rank"]),
        result(["series"]),
    ])
    assert rates["grounded"] == (3, 4)


def test_a_family_nobody_asserted_is_absent_rather_than_perfect():
    rates = family_rates([result(["series", "top_n"])])
    assert rates["grounded"] == (2, 2)
    assert "prose" not in rates, "an unasserted family reported as 100 % is a fabricated claim"


def test_a_transport_failure_does_not_count_against_the_model():
    """grade.py scores a rate limit or a dropped stream as a failed case, so an unknown share of
    the reported non-determinism is infrastructure rather than the model."""
    rates = family_rates([result([], failed=["transport"])])
    assert rates["transport"] == (0, 1)
    assert "prose" not in rates
    assert "grounded" not in rates


def test_the_grounded_and_prose_split_survives_a_mixed_run():
    rates = family_rates([
        result(["series", "numeric", "chart_type"], failed=["numeric"]),
        result(["series", "numeric", "chart_type"], failed=["numeric", "chart_type"]),
        result(["top_n", "must_contain"]),
    ])
    assert rates["grounded"] == (3, 3)      # the architecture held throughout
    assert rates["prose"] == (1, 3)         # the model did not
    assert rates["routing"] == (1, 2)


def test_an_unknown_check_is_filed_rather_than_dropped():
    assert family_of("something_new") == "routing"
    assert family_rates([result([], failed=["something_new"])])["routing"] == (0, 1)


def test_to_dict_carries_the_families_for_the_json_report():
    payload = result(["series", "numeric"], failed=["numeric"]).to_dict()
    assert payload["families"]["grounded"] == {"passed": 1, "total": 1}
    assert payload["families"]["prose"] == {"passed": 0, "total": 1}
    assert payload["failures"][0]["family"] == "prose"
