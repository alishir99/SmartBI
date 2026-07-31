# P1 remediation — complete

Nine items from `FULLSTACK_REVIEW.md` §9 (P1), one commit each, on top of the 31-commit P0
baseline. Working tree clean, 40 commits total.

## Final state

| Check | Result |
|---|---|
| `pytest -q` (no database) | **420 passed, 250 skipped** |
| `POSTGRES_HOST=localhost pytest -q -m integration` | **7 passed** |
| `ruff check .` | clean |
| `npx tsc --noEmit` (web) | clean |
| `npx vitest run` (web) | **22 passed** |
| `npm run build` (web) | builds |
| `docker compose up` **from a clean clone, no `.env`** | full stack healthy, app serves |
| `eval/run_eval.py --adversarial` (live) | **28 / 29** |

Test count entering this pass was 386; web tests were 15. Every item below carries tests, and
the three regressions that had a "this could never happen" comment above them — the unbounded
loop, the retry that drops `tools`, and the stale negative controls — each have a test that
was confirmed to **fail against the previous code** before the fix went in.

## What was fixed

| # | Item | Commit | How it was verified |
|---|---|---|---|
| 1 | D4 + D5 — every order line discounted; returns clamped onto the last day | `bb7d409` | measured from the emitted CSV: 33.4 % of lines discounted (was 100 %), 7.9 % off-campaign vs 100 % at 22.5 % on the 126 campaign days; final-day returns 19 against a median of 14 (was 252) |
| 2 | Re-derive every literal the regeneration invalidated | `6988f18` | the traceability guard caught all of it — 40 failures the moment the CSVs changed; 85 literals re-derived from `eval/oracle.py`, idempotent on a second pass |
| 3 | Q4 — the adversarial negative controls had gone dead | `ecd9ed3` | both halves of the new guard confirmed to bite: an undeclared figure fails `cases.validate`, a literal that does not match its derivation fails the test |
| 4 | B6/B7 — unbounded loop, no LLM timeout, retry dropped `tools` | `1e90c77` | 3 tests, all confirmed failing against the old code (one as a runaway-loop assertion) |
| 5 | Prompt caching + usage accounting | `cf8e0d3` | 6 tests including a provider that reports no usage at all; the cached prefix proven to go only to Anthropic |
| 6 | Q8 — `_result_for` untested | `b520b0e` | 7 cases; `market_share` suppression turned out to be covered already by P0's 22 tests |
| 7 | Q5 — eval report collapsed every check into one boolean | `85f720e` | 8 tests on the accounting; rendered live in the adversarial run below |
| 8 | A11y — muted text failed contrast, charts had no accessible name | `c76d83b` | contrast re-measured rather than taken on trust, and the review's one token turned out to be two; 7 description tests |
| 9 | Q9 — `docker compose up` did not work from a clean clone | `aca33cf` | **real clean clone, no `.env`, no CSVs**: db healthy → seed generated 810 629 lines and loaded them → mcp healthy → api and web serving |

## Verified live, not inferred

The stack was reseeded (`seed.py --force`) and `mcp`/`api` restarted before any of this, so
every figure below comes from the running system on the corrected data.

**D4 — `discount_rate` per month, through MCP.** The defect made this a flat 22.5 % line for
all 24 months, which is why *"how did Black Week compare?"* had no answer:

```
2025-07  0.59 %    2025-11 13.22 %    2026-03  0.91 %
2025-08 13.46 %    2025-12  7.72 %    2026-04 10.31 %
2025-09  0.61 %    2026-01 13.20 %    2026-05  0.70 %
2025-10  0.75 %    2026-02  0.99 %    2026-06  6.49 %
```

**D5 — the final day is ordinary again.** Returns on 2026-06-30 sit at the daily median, and
net sales land −0.8 % against that weekday's own median across coverage. (A naive comparison
against a mixed-weekday median reads −21.8 %, which is the Tuesday factor, not a defect —
worth stating because it is the number a reader would otherwise reach for.)

**End-to-end agreement.** The clean-clone dashboard returned **49 360 103,36 SEK**, byte-identical
to the golden literal re-derived in `6988f18`. Generator, CSV, Postgres, MCP and API all agree
on the same number by independent paths. `category_share_pct` read **29,6 %**, so P0's D3 fix
holds on the new data, and market share on `last_7_days` returned **0 rows above 100 %** with
the snapping recorded in `meta.time_range` — P0's D1 fix likewise.

**The adversarial suite, re-run live: 28 / 29**, inside the documented 27–29 band. The single
failure (`injection_fake_system_block`) refused correctly but repeated the competitor's *name*
in the sentence saying it does not exist in the data. **No figure leaked.** That is the shape
of case the README already says flips between runs.

The new per-family reporting, from that same run:

```
pass rate by check family:
  prose        73/74   checks  ( 98.6%)   the narrative — the model
  routing      39/39   checks  (100.0%)   tools, dimensions, chart and status — the plan
```

No `grounded` row because adversarial cases assert refusals, not rows — which is itself the
split doing its job rather than a gap.

## Two things worth knowing that were not in the plan

**The review found one contrast token; there were two.** `--text-muted` was the named one, but
`--axis-text` carried the identical failing value and is the one that matters more — every tick
on every axis, at 11 px. Both fixed; measured at 4.87:1 worst case against the backgrounds they
actually appear on.

**Three of the four dead adversarial literals came back on their own.** `174`, `158` and (as
`119`) `118` were correct figures that the discount bug had deflated. They are competitor
turnovers in MSEK, and fixing the generator restored them. The same is true of README:263 —
its "848 MSEK" only became true with this pass; under the bug the data was 707 MSEK. That is
the clearest available evidence of how far the defect had moved the dataset.

## What was deliberately not done

**The golden suite was not re-measured.** Regenerating the data invalidated the measured
36–40/52 figure, and re-running both suites twice is real spend on a live key. The README now
marks those numbers as pre-regeneration rather than quietly presenting them as current. The
*expected* values are not stale — the test suite re-derives all 52 on every run — only the
observed pass rate is.

**`get_capabilities` was not folded into the cached prefix.** The review costs it at one round
trip and −25 % latency. It changes what the model sees and what the golden set observes in
`tools_called`, so it needs its own verification pass rather than riding along with the caching
change it superficially resembles.

**Two ARIA roles still promise keyboard behaviour nobody wrote** — `PeriodFilter`'s `radiogroup`
and `Geography`'s `tablist`. Those are behaviour rather than labelling and belong with their
components. The map's 21 counties were in the same list and *were* fixed, because there the
honest fix was deleting a false `role="button"` rather than implementing an interaction.

Everything else in the P1 row of §9 is done. P2 — provenance per tool call, aggregates in the
preview envelope, sign/superlative validation, the rollup-vs-fact reconciliation, the
post-aggregate compiler stage, multi-turn eval cases, rate limiting — remains untouched and
out of scope for this pass.
