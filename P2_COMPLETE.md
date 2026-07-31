# P2 remediation — complete

Eight items from `FULLSTACK_REVIEW.md` §8 (the ranked "going beyond the ask" list) and §9's
P2 row, one commit each, on top of the 51-commit P0+P1 baseline. Working tree clean.

P0 fixed what was broken. P1 fixed what was wrong. **P2 built what was never there** — so
every item here could have made the system worse by being half-done, and three of them were
verified against a live Postgres rather than against the SQL they emit. That distinction
turned out to matter more than expected (see "What running it found").

## Final state

| Check | Result |
|---|---|
| `pytest -q` (no database) | **526 passed, 276 skipped** |
| `POSTGRES_HOST=localhost pytest -q -m integration` | **14 passed** |
| `ruff check .` | clean |
| `psql -f db/sql/tests/isolation.sql` | all assertions passed |
| `npx tsc --noEmit` (web) | clean |
| `npx vitest run` (web) | **22 passed** |
| `npm run build` (web) | builds |
| `docker compose up` from a clean clone, no `.env` | stack healthy, API and web serving |

Entering P2: 420 unit, 7 integration. The integration count doubling is the point of this
pass rather than a side effect.

## What was built

| # | Item | §8 | Commit |
|---|---|---|---|
| 1 | Rollup-vs-fact reconciliation | ★4 | `dd4321f` |
| 2 | `isolation.sql`: adversarial assertions | ★7 | `2299d8b` |
| 3 | Aggregates in the preview envelope | ★2 | `9980855` |
| 4 | Provenance per tool call | ★1 | `87c9438` |
| 5 | Sign and superlative validation | ★6 | `dc2d20e` |
| 6 | One post-aggregate stage in the compiler | ★8 | `d351a4e` |
| 7 | Multi-turn eval coverage | §9 | `1bbf242` |
| 8 | Rate limiting + per-tenant cost cap | §9 | `3b6e6a8` |

## The three numbers worth quoting

**Every figure in the prose is attributed to the tool call that produced it.** Verified live
on a turn that runs three queries: nine figures, each attributed, and **four of the nine came
from queries that are not the chart's source**. Under the previous model all nine claimed to
come from the chart. The review predicted no competing submission would have this; it is now
literally true rather than aspirational.

**Fabricated percentages: 32 % accepted → 1 %.** (The review measured ~40 % on its own
fixture; 32 % is the same defect on mine.) Three causes, all closed: candidates are tagged
with a unit class so a `%` claim cannot match a raw SEK cell; percentages no longer get the
implicit ×1e6 rescaling that let *"marknadsandelen var 2,89 %"* match a revenue of 2 890 100;
and row-wise share and delta derivations are limited to the rows the model was actually shown,
because a 500-row result was generating a thousand percentage candidates blanketing
[−100, 100].

**False rejects: 0 / 19.** Measured deliberately, because a tightened validator that
suppresses correct answers is worse than the loose one it replaced. Every real cell, the sum,
the mean, both extremes, a rounded Mkr form and a share of total all still pass. Both rates
were measured, not only the flattering one.

## What running it found

Three defects that only appear when the code meets a real database, and all three had been
sitting behind green test suites.

**`compare_to` over a non-date dimension could never execute.** P0 replaced `USING (product)`
with `ON c.product IS NOT DISTINCT FROM pv.product` so a NULL group would match rather than be
dropped. It reads better and Postgres cannot run it — no hash or merge join is available for
that operator, and `FULL OUTER JOIN` has no third strategy:

```
FeatureNotSupportedError: FULL JOIN is only supported with merge-joinable
or hash-joinable join conditions
```

So every year-on-year comparison by product, brand or region raised at run time for the whole
of P0 and P1. It survived because `test_compiler.py` parses emitted SQL with `sqlglot` and
never executes it, and no integration test paired `compare_to` with anything but a date. Two
green suites and a feature that could not run. This was my own P0 fix, not something inherited.

**The default `ORDER BY` was partial, not absent.** The review's B2 named the missing ordering;
the subtler half was that ordering by the leading *date* dimension alone still leaves the
trailing period's rows in whatever sequence the plan produced — and "whatever the plan
produced" differs between the rollup and the fact table. Found by writing a reconciliation test
that failed with the two sources returning *different regions* for the same month.

**A 20-turn chat cap would have throttled the project's own eval.** `run_eval.py --all` logs in
as one demo user and puts 85 questions through `/api/chat` at concurrency 4. The limit was
raised to 100 per five minutes: above the heaviest legitimate client, three orders of magnitude
below a runaway loop. A rate limit that trips during a demo is worse than no rate limit.

## What was deliberately not done

**The golden suite was not re-measured.** Items 3, 5 and 6 all change answer quality, and a
live golden run is the only thing that would actually quantify them — but it is real spend on
the user's key, and the P1 precedent is that this is the user's call. The README still marks
its 36–40/52 figure as pre-regeneration. The *expected* values are not stale: all 56 cases are
re-derived on every test run.

**The four dimensions are exposed but have no golden cases.** `month_of_year`, `weekday`,
`is_holiday` and `campaign_id` are queryable and integration-tested against real columns, but
no golden question asks a seasonality question yet. Writing those needs a live run to grade,
which is the same spend decision as above.

**Two ARIA roles still promise keyboard behaviour nobody wrote** (`PeriodFilter`'s `radiogroup`,
`Geography`'s `tablist`) — carried over from P1, still behaviour rather than labelling.

**The eval agent flagged three things it was not scoped to fix**, recorded here so they are not
lost: `mom_september_vs_august_2025` no longer tests a decline (the data now rises there, so the
suite has no falling pair and the sign assertion is untested by any real case); several
`# derived:` comments in `golden_questions.yaml` cite figures that no longer match their own
literals; and `cases.py::_check_golden` has a dead branch that silently accepts `status: [ok]`.

## Scorecard against the review's own criteria

Every §8 item is now done: §8.1 provenance, §8.2 aggregates, §8.3 eval split (P1), §8.4
reconciliation, §8.5 fail-closed secrets (P0), §8.6 sign and superlative, §8.7 isolation
assertions, §8.8 post-aggregate stage. §9's P2 row is done apart from the golden re-measurement
above.
