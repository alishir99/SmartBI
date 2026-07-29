# P0 remediation — complete

Twelve items from `FULLSTACK_REVIEW.md` §9, one commit each, on top of a 19-commit baseline
history. Working tree clean, 30 commits total.

## Final state

| Check | Result |
|---|---|
| `pytest -q` (no database) | **386 passed, 250 skipped** |
| `POSTGRES_HOST=localhost pytest -q -m integration` | **7 passed** |
| `ruff check mcp_server api scripts eval` | clean |
| `npx tsc --noEmit` (web) | clean |
| `npm test` (web) | **15 passed** |
| `npm run build` (web) | builds |
| `docker compose up` | full stack healthy, app serves |

Test count at the start of this pass was 322. **Every fix below carries tests**, and three of
the modules touched — `market_share.py`, the agent loop, and the dashboard route — had **no**
test coverage at all before.

## What was fixed

| # | Item | Commit | How it was verified |
|---|---|---|---|
| 0 | Incremental git history | `228783d..904a750` | 19 commits, build artefacts excluded |
| 1 | D1 — market share could exceed 100 % | `d634e0b` | 22 new unit tests; share ≤ 100 % on a `last_7_days` window against the live database |
| 2 | D2 — `compare_to` + date dimension gave all-NULL deltas | `4fb70b2` | real ordinal-join fix, not the `SpecError` fallback; 5 new compare tests; generated SQL inspected |
| 3 | D3 — headline KPI understated by 9 points | `964a324` | **live: 20.6 % → 29.5 %** on the demo tenant; 10 new tests |
| 4 | B1 — validator was opt-out via a model-set field | `d8688c3` | 8 new loop tests; 4 of them fail against the old gate |
| 5 | Q1/Q2 — CI could not pass, pytest failed on a clean clone | `0ee6d7f` | 7 real integration tests, pass against the seeded stack and skip without it; both invocations exit 0 |
| 6 | Q3 — README claims that did not hold | `cce5c56` | counts recounted; determinism now proven by test |
| 7 | S2 — `.env` shipped inside every Python image | `c5f51cb` | **live: `.env` present in the old image, gone from the rebuilt one**, app still serves |
| 8 | S1 — published internal ports + default secrets | `2af83b2` | **live: 8081 and 5432 unreachable from the host**, demo overlay restores both, both services refuse to boot on defaults |
| 9 | F1/F2 — pie colours, leaked internal columns | `d267cec` | 4 new chart tests; live check that a real `query_market_share` payload loses `category_id` and `suppressed` |
| 10 | F5/F4 — stream cancel, suggestion chip | `3567737` | **live in the browser**: cancelling produces no error; a turn mounts the slide-over below `xl` |
| 11 | F3 — share button led nowhere | `c8d19ec` | control hidden, endpoint kept, gap documented in the README |

## Verified live vs. verified by test

**Live, against the running stack:** D1, D3, S1, S2, F2, F5, F4, and the integration suite.
Screenshots of the browser pass are in the session transcript.

**By test only:**

- **F1 (pie colours).** The colour logic is pure and now has four tests, but the fix could not
  be reproduced in the browser: `propose_chart` never proposes a `pie` — it routes
  categorical-by-categorical to `stacked_bar` deliberately, because a pie with twenty-one
  slices is unreadable. A pie appears only when the *model* overrides the chart spec, and it
  did not do so on the runs attempted. Worth one manual look if a pie ever shows up.
- **F4 (slide-over).** Verified in the browser, but with `window.matchMedia` patched to report
  a sub-`xl` viewport, because Chrome was maximised and ignored every resize request. The
  app's own decision code ran unmodified; only what the environment reported was changed. The
  slide-over mounted with the expected `role="dialog"` and `xl:hidden` wrapper. A real
  1366×768 window would be a stronger check.
- **`mypy`.** CI runs it; it is not installed in the local venv, so the type-check step was not
  exercised on this machine. `ruff` and `tsc` both pass.

## Two things you need to do

1. **The DeepSeek key in `.env` is still live and still needs rotating.** It was committed to
   the repository and baked into three Docker image layers, so it must be treated as public.
   Nothing in this pass touched the value — that was your call to keep. `.gitignore` and
   `.dockerignore` now both exclude the file, so a rotated key stays out.
2. **`SOLVIGO_ENV=dev` was appended to your local `.env`.** Without it the API and the MCP
   server now refuse to start on the in-repo defaults. It is in `.env.example` too, so a fresh
   `cp .env.example .env` already has it.

## Known, deliberately left

- **`README.md:12` links to `../IMPLEMENTATION_PLAN.md`**, which lives outside the git repo, so
  a reviewer who clones gets a dead link on the second line. Left untouched pending your call
  on whether that document should ship inside the repo.
- **The share feature is half-built** — the token is real, the reading route does not exist.
  Hidden rather than removed, and written up in the README's known-gaps section.
- **D4 (campaign discount) and the rest of P1** were out of scope for this pass.

## One thing worth knowing

Item 6 turned up a bug outside its own scope: `generate_data.py`, `seed.py` and
`embed_entities.py` all crashed with `UnicodeEncodeError` on a Windows console, because they
print Swedish names to a cp1252 stdout. The very first command in the README died before
writing a row. Fixed in `scripts/console.py`; all three now start cleanly.
