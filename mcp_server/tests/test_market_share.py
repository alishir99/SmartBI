"""Tests for the one tool that reads beyond the caller's own rows.

The k-anonymity suppression here is the headline privacy claim, and until now it was
exercised only end-to-end through the non-deterministic LLM path — a safety invariant
verified by a flaky test. These are the pure-function tests it should have had.

The window-snapping tests pin the fix for shares above 100 %: the own-brand and peer
figures come from monthly rollups, so the category total has to cover the same whole
months or the ratio is a full month divided by a part month.
"""

from datetime import date

import pytest

from mcp_server.tools.market_share import (
    MIN_BRANDS,
    MIN_TRANSACTIONS,
    _row,
    _snap_to_whole_months,
)

# --------------------------------------------------------------------------- snapping

@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        # The dashboard's own last_7_days chip — the window that produced 119.66 % live.
        ((date(2026, 6, 24), date(2026, 6, 30)), (date(2026, 6, 1), date(2026, 6, 30))),
        # Spanning a boundary widens on both ends.
        ((date(2026, 5, 15), date(2026, 6, 14)), (date(2026, 5, 1), date(2026, 6, 30))),
        # 30-day month.
        ((date(2026, 4, 10), date(2026, 4, 10)), (date(2026, 4, 1), date(2026, 4, 30))),
        # February, common year.
        ((date(2026, 2, 3), date(2026, 2, 3)), (date(2026, 2, 1), date(2026, 2, 28))),
        # February, leap year — the month-length arithmetic must not assume 28.
        ((date(2024, 2, 3), date(2024, 2, 3)), (date(2024, 2, 1), date(2024, 2, 29))),
        # December, so the "next month" step has to roll the year over.
        ((date(2025, 12, 5), date(2025, 12, 20)), (date(2025, 12, 1), date(2025, 12, 31))),
        # Multi-year window.
        ((date(2024, 7, 1), date(2026, 6, 30)), (date(2024, 7, 1), date(2026, 6, 30))),
    ],
)
def test_snap_widens_to_month_boundaries(requested, expected):
    assert _snap_to_whole_months(requested) == expected


def test_snap_is_idempotent():
    """An already-aligned window must survive untouched, or meta would claim a
    snap that did not happen and the source chip would misdescribe the number."""
    aligned = (date(2026, 1, 1), date(2026, 3, 31))
    assert _snap_to_whole_months(aligned) == aligned
    assert _snap_to_whole_months(_snap_to_whole_months(aligned)) == aligned


def test_snapped_window_never_narrows():
    """Widening is safe; narrowing would drop data the caller asked for."""
    requested = (date(2026, 3, 17), date(2026, 5, 2))
    first, last = _snap_to_whole_months(requested)
    assert first <= requested[0]
    assert last >= requested[1]


# ------------------------------------------------------------------------ suppression

def _record(**overrides):
    base = {
        "brand": "Nordström Audio",
        "subcategory": "Hörlurar",
        "category_id": 11,
        "own_net_sek": 250.0,
        "own_units": 10,
        "category_net_sek": 1000.0,
        "n_transactions": MIN_TRANSACTIONS,
        "n_brands": MIN_BRANDS,
        "leader_net_sek": 400.0,
        "rank": 2,
    }
    return base | overrides


def test_share_is_returned_when_the_field_is_thick_enough():
    row = _row(_record())
    assert row["suppressed"] is False
    assert row["share_pct"] == 25.0
    assert row["rank"] == 2


@pytest.mark.parametrize(
    "thin",
    [
        {"n_brands": MIN_BRANDS - 1},
        {"n_transactions": MIN_TRANSACTIONS - 1},
        {"n_brands": MIN_BRANDS - 1, "n_transactions": MIN_TRANSACTIONS - 1},
        {"n_brands": 0},
        {"n_brands": None},
        {"n_transactions": None},
    ],
)
def test_thin_slices_are_suppressed(thin):
    row = _row(_record(**thin))
    assert row["suppressed"] is True
    assert row["reason"]


@pytest.mark.parametrize(
    "leaky",
    ["share_pct", "rank", "category_net_sek", "leader_share_pct"],
)
def test_suppression_withholds_everything_derivable(leaky):
    """Leaving rank in while removing share would still narrow a competitor's
    revenue, so the whole derivable set has to go together."""
    row = _row(_record(n_brands=MIN_BRANDS - 1))
    assert leaky not in row


def test_thresholds_are_inclusive_at_the_boundary():
    assert _row(_record(n_brands=MIN_BRANDS))["suppressed"] is False
    assert _row(_record(n_transactions=MIN_TRANSACTIONS))["suppressed"] is False


def test_zero_category_total_yields_none_not_a_division_error():
    row = _row(_record(category_net_sek=0))
    assert row["share_pct"] is None
    assert row["leader_share_pct"] is None
