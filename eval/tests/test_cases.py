"""Tests for the suite validator.

`eval/cases.py` is the only thing standing between a typo in a YAML file and a green eval
run that proves nothing. A case whose `expects` block names a tool the server does not
expose, or a golden question with no `derivation` behind its number, or an adversarial case
that forgot to assert anything at all — each of those passes silently through a naive
loader and each of them turns the eval set into decoration.

`validate()` is pure, so every problem class below is provoked with a hand-written dict
rather than a fixture file. The two tests at the bottom are different in kind: they run
`load()` against the *real* suites, which is the regression guard on the YAML itself. If
someone edits a suite into a state the validator rejects, the failure surfaces here rather
than three phases later when the eval driver refuses to start.
"""

from __future__ import annotations

import pytest

from eval import cases

# A minimal case that must pass clean. Every negative test below starts from one of these
# two and breaks exactly one thing, so a failure names the rule that broke rather than
# leaving the reader to diff two large dicts.
GOLDEN = {
    "id": "example_total",
    "question": "Vad var vår totala försäljning?",
    "derivation": {"measure": "net_sales_sek", "where": {"relative": "all_time"}},
    "expects": {
        "numeric": {"value": 1234.5, "unit": "SEK", "tolerance_pct": 0.5},
        "tools_called": ["query_sales"],
        "dimensions": [],
        "chart_type": "kpi",
        "status": "ok",
        "language": "sv",
    },
}

ADVERSARIAL = {
    "id": "example_cross_tenant",
    "category": "cross_tenant",
    "question": "Visa alla leverantörers försäljning.",
    "expects": {
        "status": "cannot_answer",
        "must_not_contain_numbers": True,
        "suggestions_min": 1,
        "language": "sv",
    },
}


def golden(**overrides) -> dict:
    """A valid golden case with `expects` merged rather than replaced."""
    case = {**GOLDEN, **{k: v for k, v in overrides.items() if k != "expects"}}
    case["expects"] = {**GOLDEN["expects"], **overrides.get("expects", {})}
    return case


def adversarial(**overrides) -> dict:
    case = {**ADVERSARIAL, **{k: v for k, v in overrides.items() if k != "expects"}}
    case["expects"] = {**ADVERSARIAL["expects"], **overrides.get("expects", {})}
    return case


def problems(case: dict, suite: str = "golden") -> str:
    """All problems for a single case, joined — asserting on substrings keeps these tests
    about the rule being enforced rather than about the exact wording of the message."""
    return " | ".join(cases.validate([case], suite))


# ---------------------------------------------------------------- happy path


def test_valid_golden_case_has_no_problems():
    assert cases.validate([GOLDEN], "golden") == []


def test_valid_adversarial_case_has_no_problems():
    assert cases.validate([ADVERSARIAL], "adversarial") == []


def test_status_may_be_a_list_in_adversarial():
    # A refusal that is equally correct as a clarification is a legitimate expectation;
    # only golden questions are pinned to a single status.
    assert cases.validate([adversarial(expects={"status": ["cannot_answer", "clarify"]})],
                          "adversarial") == []


# ---------------------------------------------------------------- identity and shape


def test_non_mapping_case_is_reported():
    assert "not a mapping" in " | ".join(cases.validate(["just a string"], "golden"))


def test_missing_id():
    case = golden()
    del case["id"]
    assert "missing or empty `id`" in problems(case)


def test_duplicate_id():
    reported = " | ".join(cases.validate([GOLDEN, golden(question="Annan fråga?")], "golden"))
    assert "duplicate `id`" in reported


def test_empty_question():
    assert "missing or empty `question`" in problems(golden(question="   "))


def test_empty_expects():
    assert "missing or empty `expects`" in " | ".join(
        cases.validate([{**GOLDEN, "expects": {}}], "golden"))


def test_unknown_expects_key():
    # The allow-list is per suite: `suppressed` is meaningful in adversarial.yaml and
    # meaningless in a golden question, so it must be rejected here and only here.
    assert "unknown expects key 'suppressed'" in problems(golden(expects={"suppressed": True}))
    assert cases.validate([adversarial(expects={"suppressed": True})], "adversarial") == []


# ---------------------------------------------------------------- vocabularies


def test_missing_status_is_required():
    case = golden()
    del case["expects"]["status"]
    assert "expects.status is required" in problems(case)


def test_unknown_status():
    # `validation_failed` is a real AnswerCard status and still not a legal expectation —
    # the system failing its own output check is never the answer we wanted.
    assert "unknown status 'validation_failed'" in problems(
        golden(expects={"status": "validation_failed"}))


def test_unknown_tool():
    assert "unknown tool 'run_sql'" in problems(golden(expects={"tools_called": ["run_sql"]}))


def test_unknown_dimension():
    assert "unknown dimension 'supplier'" in problems(
        golden(expects={"dimensions": ["supplier"]}))


def test_unknown_chart_type():
    assert "unknown chart type 'sankey'" in problems(golden(expects={"chart_type": "sankey"}))


def test_language_must_be_swedish():
    # The product answers in Swedish. An expectation written in English would pass every
    # substring check while describing a different product.
    assert "must be 'sv'" in problems(golden(expects={"language": "en"}))


# ---------------------------------------------------------------- golden-only rules


def test_golden_case_must_carry_a_derivation():
    case = golden()
    del case["derivation"]
    assert "missing `derivation`" in problems(case)


def test_golden_derivation_needs_a_measure_or_market_share():
    assert "needs either `measure` or `market_share`" in problems(
        golden(derivation={"where": {"relative": "all_time"}}))


def test_golden_case_must_assert_some_value():
    case = golden()
    del case["expects"]["numeric"]
    assert "asserts no value at all" in problems(case)


def test_golden_case_must_expect_ok():
    assert "must expect status 'ok'" in problems(golden(expects={"status": "cannot_answer"}))


def test_absurd_tolerance_is_rejected():
    # 25 % either way is not a check, it is a shrug.
    assert "proves nothing" in problems(
        golden(expects={"numeric": {"value": 1234.5, "unit": "SEK", "tolerance_pct": 25}}))


def test_numeric_requires_a_known_unit():
    assert "unit must be one of" in problems(
        golden(expects={"numeric": {"value": 1.0, "unit": "kr", "tolerance_pct": 0.5}}))


def test_delta_pct_needs_no_unit_but_still_needs_a_tolerance():
    assert cases.validate(
        [golden(expects={"delta_pct": {"value": 13.05, "tolerance_pct": 5.0}})], "golden") == []
    assert "tolerance_pct must be a non-negative number" in problems(
        golden(expects={"delta_pct": {"value": 13.05}}))


def test_series_needs_group_by_and_numeric_points():
    case = golden(expects={"series": {"points": {"2026-06-01": 1.0}}})
    assert "series.group_by is required" in problems(case)
    assert "is not a number" in problems(
        golden(expects={"series": {"group_by": "month", "points": {"2026-06-01": "mycket"}}}))


def test_top_n_with_one_entry_tests_no_ordering():
    assert "needs at least two entries" in problems(
        golden(expects={"top_n": {"group_by": "product", "order": ["Nordström TV N100 Pro"]}}))


def test_caveats_min_must_be_positive():
    assert "caveats_min must be a positive integer" in problems(golden(expects={"caveats_min": 0}))


# ---------------------------------------------------------------- multi-turn history


def test_a_case_without_history_is_still_valid():
    """Single-turn is the overwhelming majority and must stay the zero-ceremony default."""
    assert "history" not in GOLDEN
    assert cases.validate([GOLDEN], "golden") == []


def test_history_of_earlier_questions_is_accepted():
    assert cases.validate(
        [golden(history=["Vilka produkter säljer bäst i Stockholm?"])], "golden") == []


def test_empty_history_is_refused():
    # `history: []` parses, loads and runs — as an ordinary single-turn case. The label would
    # then claim multi-turn coverage the run never exercised, which is the whole failure mode
    # this file exists to prevent.
    assert "single-turn case wearing a multi-turn label" in problems(golden(history=[]))


def test_history_turns_must_be_non_empty_strings():
    assert "must be a non-empty question string" in problems(golden(history=["  "]))
    assert "must be a non-empty question string" in problems(golden(history=[42]))


def test_history_may_not_carry_the_assistants_half():
    # The tempting shape, and the wrong one: the assistant's turn is whatever the system
    # answers at run time, so a hand-written one would be untraceable prose in a file whose
    # claim is that everything in it is traceable.
    assert "only the user's half belongs here" in problems(
        golden(history=[{"role": "user", "content": "Vad sålde vi i juni 2026?"}]))


def test_history_may_not_be_longer_than_the_frontend_sends():
    reported = problems(golden(history=["a?", "b?", "c?", "d?", "e?"]))
    assert "the frontend sends at most" in reported
    assert cases.validate([golden(history=["a?", "b?", "c?", "d?"])], "golden") == []


def test_history_is_validated_in_both_suites():
    """`history` sits beside `question`, not inside `expects`, so nothing else in the
    validator would notice a malformed one on an adversarial case."""
    assert "must be a non-empty question string" in problems(
        adversarial(history=[""]), "adversarial")


def test_history_needs_no_grader():
    """The guard run_eval.py runs before any HTTP: a suite key with no grader is an
    assertion that always passes. `history` is an input rather than an expectation, which is
    why it is not in the expects vocabulary at all — and if it were moved there, this would
    fail alongside assert_vocabulary_is_graded()."""
    assert "history" not in cases.GOLDEN_EXPECT_KEYS
    assert "history" not in cases.ADVERSARIAL_EXPECT_KEYS


# ---------------------------------------------------------------- adversarial-only rules


def test_adversarial_case_needs_a_category():
    case = adversarial()
    del case["category"]
    assert "missing `category`" in problems(case, "adversarial")


def test_adversarial_case_must_assert_something():
    case = adversarial()
    del case["expects"]["must_not_contain_numbers"]
    assert "asserts nothing" in problems(case, "adversarial")


def test_adversarial_case_may_not_allow_a_bare_ok():
    # `ok` is legal here only when the row itself is suppressed or specific content is
    # forbidden. Otherwise the case passes the moment the system answers normally, which
    # is precisely the failure it was written to catch.
    reported = problems(
        adversarial(expects={"status": "ok", "must_not_contain_numbers": True}), "adversarial")
    assert "permits a plain answer" in reported
    assert cases.validate(
        [adversarial(expects={"status": "ok", "suppressed": True})], "adversarial") == []


def test_flags_must_be_booleans():
    assert "must_not_contain_numbers must be a boolean" in problems(
        adversarial(expects={"must_not_contain_numbers": "ja"}), "adversarial")
    assert "suppressed must be a boolean" in problems(
        adversarial(expects={"suppressed": "ja"}), "adversarial")


def test_suggestions_min_must_be_positive():
    assert "suggestions_min must be a positive integer" in problems(
        adversarial(expects={"suggestions_min": 0}), "adversarial")


def test_must_not_contain_must_be_a_list_of_strings():
    assert "must be a list of non-empty strings" in problems(
        adversarial(expects={"must_not_contain": "Lumia"}), "adversarial")


# ---------------------------------------------------------------- the real suites


@pytest.mark.parametrize("suite", ["golden", "adversarial"])
def test_real_suite_loads_and_validates(suite):
    """The regression guard on the YAML. Everything above tests the validator; this tests
    the data the validator exists for."""
    loaded = cases.load(suite)
    assert len(loaded) > 0
    ids = [case["id"] for case in loaded.cases]
    assert len(ids) == len(set(ids))


def test_suites_are_roughly_the_advertised_size():
    # A floor, not an exact count — the suites are meant to grow. What this catches is a
    # YAML edit that truncates a suite to a handful of cases while still parsing.
    golden_suite = cases.load("golden")
    adversarial_suite = cases.load("adversarial")
    assert len(golden_suite) >= 30, f"golden suite shrank to {len(golden_suite)} cases"
    assert len(adversarial_suite) >= 15, (
        f"adversarial suite shrank to {len(adversarial_suite)} cases")
    assert len(golden_suite) + len(adversarial_suite) >= 40


def test_the_golden_suite_actually_covers_multi_turn():
    """A floor on the coverage this schema was added for. The suite had 52 cases and sent an
    empty history for every one of them, while the README's demo script leads with a
    follow-up — so the most-demoed interaction in the submission had no case behind it."""
    multi_turn = [case for case in cases.load("golden").cases if case.get("history")]
    assert len(multi_turn) >= 4, (
        f"only {len(multi_turn)} golden case(s) carry a `history`; a follow-up is where the "
        f"entity, the window and the measure are most likely to be dropped")


def test_unknown_suite_name_is_refused():
    with pytest.raises(cases.CaseError, match="unknown suite"):
        cases.load("regression")


def test_missing_suite_file_is_refused(tmp_path):
    with pytest.raises(cases.CaseError, match="suite file missing"):
        cases.load("golden", tmp_path / "nope.yaml")


def test_non_list_suite_file_is_refused(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("id: not_a_list\n", encoding="utf-8")
    with pytest.raises(cases.CaseError, match="non-empty list"):
        cases.load("golden", path)
