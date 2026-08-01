# UX remediation — complete

Fourteen items from `PLAN_UX.md`, itself written from a hands-on browser session as Anna
Lindqvist (Nordström Audio AB). One commit each, on top of the P0+P1+P2 baseline. Working
tree clean.

P0 fixed what was broken, P1 what was wrong, P2 built what was never there. **U fixed what a
supplier actually sees** — which turned out to be a different list, because a system can be
correct in every test and still look unfinished ten seconds into a demo.

## Final state

| Check | Result |
|---|---|
| `pytest -q` (no database) | **618 passed, 262 skipped** |
| `POSTGRES_HOST=localhost pytest -q` (with database) | **+14 integration passed** |
| `ruff check .` | clean |
| `mypy api mcp_server` | clean, 30 source files |
| `npx tsc --noEmit` (web) | clean |
| `npx vitest run` (web) | **44 passed** |
| `npx vite build` (web) | builds |
| `docker compose up --build` | stack healthy, API and web serving |

Entering this plan: 551 unit, 14 integration, 22 web. The web count doubling is where the
work was: most of U is what a person sees, and most of what a person sees had no test.

## What was built

| # | Item | Commit |
|---|---|---|
| **U0** | **visible in the first ten seconds** | |
| 1 | Render the narrative properly (markdown → structure) | `943633a` |
| 2 | Default the period filter to `Senaste 12 mån` | — no change needed |
| 3 | Chart subtitle derived from the selected period | `205aada` |
| 4 | Stop showing internal chart rejections to the user | `943633a` |
| 5 | Keep the status message honest through the turn | `9524e9d` |
| **U1** | **the previous-period feature** | |
| 6 | Overlay the comparison series on the trend chart | `f7f6c92` |
| 7 | Market-share KPI gets a comparison | `5d2bcd9` |
| 8 | Sparkline behind every KPI | `25ef29a` |
| 9 | Comparison-basis selector (period / year / none) | `3705154` |
| **U2** | **the differentiators** | |
| 10 | Show the chart before the prose | `c8fe680` |
| 11 | Produkter becomes the movers page | `323dd74` |
| 12 | Every number is a question | `9a35698` |
| 13 | Campaign annotations on the trend line | `7a76d47` |
| 14 | Verification pass + this document | `8a109db` |

## The one screen that carries the plan

Open the app as Anna. Within ten seconds, and all of it live-verified rather than inferred:

- **Four KPI tiles, four deltas.** Before this pass, *Andel av kategori* permanently read
  "Ingen jämförelseperiod" — and it is the one tile that matters most. It now reads
  **−0,9 p.e. against +13,1 % sales**: absolute sales rising while category share falls is
  the single most valuable thing this product can tell a supplier, and it was the one number
  that could not move.
- **A sparkline under three of them.** An arrow gives direction; twelve points give shape.
- **A trend line with its comparison behind it**, muted and dashed, legended as the period it
  actually is — *Nettoförsäljning (jul 2024–jun 2025)*, not `net_sales_sek_compare`.
- **Six dashed campaign markers** on that line, one per campaign window in the calendar,
  with one sentence saying what they are.
- **A basis selector** that changes every delta and the overlay together.

The comparison data was already being fetched and thrown away. Three separate symptoms in the
review — the chart with one line, the KPI that never moved, the developer-jargon caveat —
were one feature 90 % built. U1 was mostly un-blocking what existed.

## What running it found

Four defects that no test was looking for, all found in the browser during item 14 and all
fixed in `8a109db`. They are recorded here because *that a verification pass found anything*
is the argument for having one.

1. **The chat stream spelled time windows differently from every other route.** `TimeWindow`'s
   field is `from_`, because `from` is a Python keyword. Every other producer of an
   `AnswerCard` goes through a FastAPI `response_model`, which serialises by alias; the SSE
   stream called `model_dump_json()` bare, so the wire carried `from_` and the client read
   `undefined` for the start of every window. It had been latent since the SSE contract
   existed, and only surfaced because item 10's chart-first preview is the first card with no
   model-supplied subtitle to fall back on. It rendered `undefined–2026-06-30` on screen.

2. **`/api/result` built its column list by hand instead of calling `to_columns`.** Two copies
   of one rule, and the copy feeding the chart's legend and the CSV header was the stale one —
   so item 6's period naming reached the card's table view and not the legend beside it.

3. **The trend axis read `2025-07-01` where it meant `jul 2025`.** `UX_REVIEW.md` §3 quoted
   exactly this and item 3 only fixed the subtitle next to it. Every date bucket comes back
   as its first day, so the value alone cannot say whether it is a month or a day — but the
   column key can, because it is the dimension key the compiler grouped by.

4. **Item 9 regressed honesty on `Hela perioden`.** Removing the per-period comparison gate
   was right: the gate existed because the user had not chosen a basis, and now they do. But
   "samma period förra året" across the full two years reaches a year before the warehouse
   begins, so half the comparison is missing and the tile read **+113 %** for a business that
   did not double. The user chose the basis; they cannot see that the window falls off the end
   of the data. When the comparison window is not inside coverage, every delta is withheld and
   the chart drops the overlay with it.

The fourth is the one worth keeping. A control that lets the user ask for something the data
cannot answer is not more honest than one that decides for them — it just moves the mistake.

## Re-walking `UX_REVIEW.md`

Every observation, marked fixed, deliberately not fixed, or superseded. A UX review that is
not re-walked is a list of opinions.

| Observation | Outcome |
|---|---|
| §1 Literal `**` and collapsed lists in the narrative | **Fixed** (1) — prompt + server-side strip; highlights moved to `insights[]` |
| §2a Trend chart draws one line under `compare_to` | **Fixed** (6) |
| §2b Validator vocabulary in a user-facing caveat | **Fixed** (4) — moved to `chart.override` in the log |
| §3 Subtitle disagrees with the x-axis | **Fixed** (3), and the axis itself fixed in (14) |
| §4 *Andel av kategori* can never move | **Fixed** (7) |
| §5 App opens on a screen with no comparison | **Not a defect** (2) — `DEFAULT_PERIOD` was already correct; the review saw persisted `localStorage`. See "Known and accepted" below |
| Smaller: status stuck on "Hämtar…" for 25 s | **Fixed** (5) |
| Rec. §1a Comparison on the trend | **Fixed** (6) |
| Rec. §1b Sparkline per KPI | **Fixed** (8), except the share tile — see below |
| Rec. §4 Chart before prose | **Fixed** (10) |
| Rec. §5 Produkter has no reason to exist | **Fixed** (11) — risers and fallers |
| Ideas: click a number to ask about it | **Fixed** (12) |
| Ideas: campaign annotations | **Fixed** (13), without names — see below |
| Ideas: "sedan sist" digest, saved questions | **Deliberately not fixed** — storage and scheduling, not polish; belongs with the alerting work |
| 21-county bar chart, page length | **Deliberately not fixed** — a layout debate, and it should follow U1 since the overlay changed the trend card's height |
| Truncated product labels | **Deliberately not fixed** — Recharts axis ticks are awkward to make hoverable; the table view gives full names |
| Latency itself | **Superseded** — (5) and (10) make the wait honest and shorter-feeling; making it actually shorter is prompt-caching work noted in `P1_COMPLETE.md` |

## Known and accepted

Three things a reader should know, recorded as decisions rather than omissions.

**Campaign markers have no names.** `dim_date` carries `campaign_id` and its days; the names
("Black Week", "Mellandagsrea") live only in the generator's reference data and were never
loaded into the warehouse. Naming them needs a `dim_campaign` table — a data model change,
which this plan scopes out. The marker therefore says *that* a campaign ran, never what it
was called. That still turns an unexplained November spike into an explained one, which is
what the item asked for, but it is less than the item imagined.

**The market-share tile has no sparkline.** `query_market_share` aggregates over the whole
window and has no month dimension, so there is no series to draw without changing the tool's
shape. Noted in the code rather than faked.

**Period and basis persist in `localStorage`.** This is what made the original review open on
*Hela perioden* — the reviewer's own earlier choice, not a defect, and item 2 kept the
persistence deliberately. Item 9 adds a second persisted choice, and *Ingen jämförelse* is a
worse thing to land on than *Hela perioden* was, because it switches off everything U1 built.
It is still the user's explicit choice being honoured, so it stands; but a demo on a
previously-used browser should check the two pills before starting.

## Verified live rather than by test

The claims above that came from the running stack, not from a fixture:

- All four KPI deltas, the share tile among them, on `last_12_months` / *vs förra året*.
- Sparklines: 12 points on three tiles, 0 on the share tile.
- Six campaign markers, at the six campaign months, on a monthly axis; `K3 2024`-style labels
  on the quarterly one.
- `Hela perioden` withholding every delta and the overlay after fix 4.
- The movers page ranking both directions, the fallers axis running −32 → 0.
- Two live chat turns: the chart-first preview on screen while the status still read
  *Sammanställer svaret…*, then the full card with clean prose, real bullets, and the
  comparison overlay.
- All four KPI values as focusable buttons carrying the right Swedish question, including
  *"…andelen av kategorin 0,9 procentenheter…"* rather than percent-of-a-percent.
