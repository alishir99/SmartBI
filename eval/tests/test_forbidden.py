"""Re-derivation of every forbidden figure in adversarial.yaml.

The counterpart to test_expectations.py, for the suite that actually carries the safety
claim. Its absence was a real hole rather than a theoretical one: `174`, `118`, `158` and
`22 105` were once genuine competitor figures, a data regeneration moved all four, and
nothing noticed. Four negative controls spent that whole period forbidding strings the data
could no longer produce — passing unconditionally, proving nothing, and still being counted
as evidence that no competitor figure ever reached a card.

A negative control has to be live to be a control. So each forbidden number declares a
`forbids` entry saying which competitor figure it is, this module re-computes it from the
CSVs on every run, and eval/cases.py rejects any numeric literal that no entry accounts for.
Between them the two checks close the loop: a number cannot enter the file untraceably, and
a number already in it cannot go stale quietly.

What would go undetected without this file: a forbidden value drifting off the data, which
turns a safety assertion into a no-op that still reports green.
"""

from __future__ import annotations

import pytest

from eval import cases
from eval.oracle import Oracle

pytestmark = pytest.mark.skipif(
    not (Oracle().data_dir / "fact_sales_line.csv").exists(),
    reason=("data/generated is missing — regenerate with: "
            "python scripts/generate_data.py --seed 42"))

ADVERSARIAL = cases.load("adversarial").cases
WITH_FORBIDS = [case for case in ADVERSARIAL if case.get("forbids")]
CASE_IDS = [case["id"] for case in WITH_FORBIDS]


@pytest.fixture(scope="module")
def oracle() -> Oracle:
    return Oracle()


def test_the_controls_that_rotted_are_covered():
    """The four cases that went dead are the reason this module exists. If one of them
    loses its `forbids` block, the regression is back and silent again."""
    assert set(CASE_IDS) >= {
        "cross_tenant_named_competitor",
        "cross_tenant_compare_named",
        "cross_tenant_competitor_top_products",
        "injection_roleplay_bypass",
    }


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_forbidden_literal_still_derives(case_id, oracle):
    case = next(c for c in WITH_FORBIDS if c["id"] == case_id)
    for entry in case["forbids"]:
        derived = oracle.derive_forbidden(entry)
        subject = entry.get("supplier") or entry.get("brand_top_product")
        assert derived == entry["literal"], (
            f"{case_id}: forbidden literal drifted off the data\n"
            f"    adversarial.yaml forbids: {entry['literal']!r}\n"
            f"    derived from the CSVs:    {derived!r}\n"
            f"    subject: {subject!r} at scale {entry.get('scale', 1)}\n"
            f"    the control is forbidding a string the data no longer produces, so it "
            f"passes for the wrong reason — update the literal to the derived value")


@pytest.mark.parametrize("case_id", CASE_IDS)
def test_forbidden_figure_is_not_the_tenants_own(case_id, oracle):
    """A control that forbids the tenant's own number would fail every honest answer.
    Every subject here has to be someone else."""
    case = next(c for c in WITH_FORBIDS if c["id"] == case_id)
    for entry in case["forbids"]:
        if supplier := entry.get("supplier"):
            assert supplier != "Nordström Audio AB", (
                f"{case_id}: forbids the demo tenant's own figure")
        if brand := entry.get("brand_top_product"):
            owned = set(oracle.slice()["brand"].unique())
            assert brand not in owned, (
                f"{case_id}: {brand!r} is a brand the tenant owns — forbidding its figure "
                f"asserts nothing about cross-tenant leakage")
