# API contract — backend ↔ frontend

The coordination point for parallel work. Both sides build against this file, not against each
other. Change a shape here out loud — someone has already coded against it.

Money is `APP_CURRENCY` (ISO-4217), excluding VAT unless a tool says otherwise. UI text follows
`APP_LANGUAGE` (`sv` or `en`); code and identifiers are English. Nothing below hardcodes SEK —
the currency rides on the data, see `Provenance.currency` and `Column.unit`.

---

## Auth

```
POST /api/auth/login   {email, password}  →  {access_token, token_type: "bearer", user}
GET  /api/auth/me                         →  User
```

```ts
type User = {
  user_id: number
  email: string
  display_name: string
  role: "supplier_viewer" | "supplier_admin" | "retail_analyst" | "system_admin"
  supplier_id: number | null
  supplier_name: string | null
}
```

Every other endpoint needs `Authorization: Bearer <token>`. `supplier_id` comes from the
verified token, never from a body or query string.

Demo accounts (seeded, password `demo1234`):

| email | supplier |
|---|---|
| `ali@solvigo.se` | Nordström Audio AB (the demo tenant) |
| `sara@solvigo.se` | Lagerkvist Hem AB (for showing isolation live) |

---

## Shared types

```ts
type Column = {
  key: string
  type: "date" | "text" | "number"
  label: string
  unit?: string | null        // ISO-4217 code, or "st" | "%" | "p.e."
}

// The model emits a ChartSpec. It never emits values — only which columns to draw.
type ChartSpec = {
  type: "line" | "bar" | "stacked_bar" | "area" | "pie" | "kpi" | "table"
  x: string | null            // column key
  y: string[]                 // measure column keys
  series: string | null       // column key to split series by
  sort: "asc" | "desc" | null
  limit: number | null
  title: string
  subtitle: string | null
  markers: string[]           // x values worth a line; server-owned, stripped off model specs
  marker_label: string | null
}

type Provenance = {
  tool: string                // "query_sales" | "query_market_share" | "dashboard"
  source: string              // "mv_sales_daily (rollup)" | "fact_sales_line" | ...
  scope: string               // "supplier:8f2a" — hashed, never the raw id
  currency: string            // ISO-4217, from the tool's own meta
  vat: "excl" | "incl"        // a code, not a phrase: the reader's language picks the words
  time_range: { from: string; to: string }
  compare_range: { from: string; to: string } | null
  coverage: { from: string; to: string }
  filters_applied: Record<string, unknown>
  row_count: number
  truncated: boolean
  executed_at: string
  tool_args: Record<string, unknown>
}

type ToolCallRecord = {                 // one result the turn produced
  query_id: string
  tool: string
  provenance: Provenance
  row_count: number
}

type Claim = {                          // one accepted figure, and what licensed it
  literal: string
  query_id: string
}

// The single unit both the dashboard and the chat produce. One card type, two producers —
// which is what lets a chat answer be pinned next to a standard tile.
type AnswerCard = {
  card_id: string | null      // set once saved
  status: "ok" | "cannot_answer" | "clarify" | "validation_failed" | "explain"
  narrative: string           // empty unless status is "ok"
  insights: string[]
  caveats: string[]
  chart: ChartSpec | null
  query_id: string | null     // the chart's source; fetch via /api/result/{query_id}
  columns: Column[]
  provenance: Provenance | null   // the chart's; kept for compatibility, equals its sources[] entry
  sources: ToolCallRecord[]       // every result the turn produced, the chart's first
  claims: Claim[]                 // which query licensed each figure in the narrative
  suggestions: string[]           // for cannot_answer / clarify: what CAN be asked
}
```

`tool`, `source`, `scope` and `tool_args` are carried for saving, re-running and sharing —
**not rendered**. A chip leading with `mv_sales_daily (rollup)` reads as the app handing out its
own plumbing; the chip says what was counted, over which period, from how many rows.

Provenance is per tool call, not per card: a turn calling two tools caches both under their own
`query_id`, so the chip can attribute each figure to the query that produced it.

### Status semantics — the frontend renders these differently

| status | meaning | render |
|---|---|---|
| `ok` | answered from tool data | narrative + chart, source chip in chat (not on dashboard tiles — the page header already states period, supplier and unit) |
| `clarify` | entity ambiguous | question + clickable candidate chips, no chart |
| `cannot_answer` | outside what the data can answer | explanation + `suggestions` as clickable prompts |
| `explain` | a question about the card, not the data | narrative under an "about this chart" heading, no chart |
| `validation_failed` | a figure in the prose didn't match the data, twice | chart only, prose suppressed, visible warning |

`explain` answers "what does the dashed line mean?" — no query, so no result. It's exempt from
the rule that turns a resultless `ok` into `cannot_answer`, but keeps the numeric check, which
then runs against an empty result set: an explanation that states a figure has nothing to state
it from, and gets suppressed. Explanations describe what is drawn; numbers need a tool call.

`validation_failed` is not an error to hide — it's the guarantee working. Say so plainly: the
prose couldn't be verified and was withheld, the chart comes straight from the database.

---

## Dashboard — deterministic, no LLM

```
GET /api/dashboard?period=…  →  { kpis: Kpi[], cards: AnswerCard[] }
GET /api/movers?period=…     →  { cards: AnswerCard[] }
```

Goes through the same MCP tools as the chat, server-side, no model involved. Same numbers,
same provenance, guaranteed.

`period` is a key from `PERIODS`; an unknown value falls back to the default rather than
erroring. The comparison follows the filter and isn't separately selectable — every delta is
measured against the window immediately before the selected one (`compare_to: previous_period`),
and that reaches the KPI deltas, the trend overlay and the share tile together. No two numbers
on screen are measured against different windows.

```ts
type Kpi = {
  key: "net_sales_sek" | "category_share_pct" | "units" | "avg_price_sek"
  label: string
  value: number
  unit: string               // ISO-4217, or "st" | "%"
  delta_pct: number | null   // vs the previous window; percentage *points* when unit is "%"
  delta_label: string | null // null when there is nothing to compare
  rank_label: string | null  // "#2 of 6 brands"
  spark: number[]            // the measure over the period's own grain, oldest first; [] if none
}
```

`net_sales_sek` keeps its name — it's an identifier the compiler, the eval and every saved card
look up by. The currency is in `unit`, not the name.

`delta_pct` is null when the comparison window returned nothing or falls outside coverage; the
tile then reads as having no comparison period.

`/api/dashboard` returns, in order: sales trend over the period's own grain, top 10 products,
sales by region. Each is a full `AnswerCard` with `chart` and `query_id` set. The trend card
carries a derived `net_sales_sek_ma` column — a trailing three-bucket mean drawn as a line
over the bars.

`/api/movers` returns biggest risers then biggest fallers, ten each, on the derived
`net_sales_sek_delta_pct` column. That's the one place a percentage sits on the value axis;
everywhere else a percentage next to money is the bug the filter exists to prevent.

---

## Chat — SSE

```
POST /api/chat   { question: string, history?: {role, content}[] }
```

Responds `text/event-stream`, each event `data: <json>\n\n`:

```ts
type ChatEvent =
  | { type: "status";      message: string }
  | { type: "tool_call";   tool: string; args: object }      // shown as a progress chip
  | { type: "tool_result"; tool: string; row_count: number }
  | { type: "token";       text: string }                    // narrative, streamed
  | { type: "preview";     card: AnswerCard }                // chart only; not terminal
  | { type: "card";        card: AnswerCard }                // terminal on success
  | { type: "error";       message: string }                 // terminal on failure
```

Streaming the *tool calls* is a trust feature, not a latency one — the user watches the system
go to the database.

`preview` carries a chart with an empty narrative, emitted as soon as a row tool returns. It
can arrive more than once; each replaces the last, and the terminal `card` replaces them all.
The chart was never the untrusted half — it's drawn from cached rows, not from the model — so
showing it early costs nothing, while the prose stays withheld until validated. A stream
ending on a `preview` ended early: that's an error, not an answer.

---

## Result data — where charts get their numbers

```
GET /api/result/{query_id}?offset=0&limit=1000
  →  { query_id, columns: Column[], rows: object[], row_count, truncated }
```

The chart is drawn from this, never from the model's output. Cached server-side and scoped to
the requesting tenant; another tenant's `query_id` returns **404, not 403** — a 403 would
confirm the id exists.

Every row tool call in a turn is cached under its own id, so any `sources[i].query_id` is
fetchable, not just the chart's.

---

## Saved views, export, share

```
GET    /api/cards                 →  AnswerCard[]
POST   /api/cards                 {title, chart, tool_name, tool_args}  →  AnswerCard
DELETE /api/cards/{card_id}       →  204
GET    /api/export/{query_id}.csv →  text/csv   (separator and decimal follow APP_LOCALE)
POST   /api/share                 {card_id, mode: "snapshot" | "live"}  →  {url, expires_at}
GET    /api/shared/{token}        →  SharedView        ← no Authorization header
```

Saving persists the **spec plus the tool arguments**, not a screenshot, so a saved card re-runs
live against fresh data. `POST /api/cards` caps a supplier at 200 saved views.

`url` is `{public_web_url}/#/delad/{token}` — a hash route, because the router is one.

```ts
type SharedView = {
  card: AnswerCard          // card_id and query_id are null: see below
  result: ResultPage        // the rows, inline
  shared_by: string         // supplier name, for a reader with no session
  expires_at: string
  mode: "snapshot" | "live" // always "live" today
}
```

The only unauthenticated route. Everything it may read is in the signed token — which card, and
whose scope the query runs under — so a reader can't widen either, and a live link re-executes
as the supplier who shared it, never as whoever opens it. Rows travel inline because
`/api/result` needs a logged-in tenant, and no `card_id` reaches the reader because every
control keyed to it is an authenticated call. Every failure — expired, tampered, deleted, wrong
supplier — returns the same 404 and the same sentence.

`mode: "snapshot"` is accepted and carried in the token, but served as `live`: freezing rows
means storing them.

---

## Formatting the frontend owns

Formatting goes through `Intl` with `APP_LOCALE`; there are no hand-written month names or
magnitude ladders. Three rules `Intl` won't give you:

- **One scale per axis, not per value.** `notation: 'compact'` scales each tick separately and
  puts "900k" under "1.2M". Pick the magnitude once per chart; take only the *label* from `Intl`.
- **Check the integer part before abbreviating.** Japanese groups in myriads — `Intl` writes
  1,000,000 as "100万". A locale that can't write the divisor as a lone 1 gets no abbreviation
  rather than a wrong one.
- **The unit lives on the axis, never repeated per tick.**

Plus: percentages to one decimal; deltas always carry their comparison period as a label, never
a bare arrow; every card states period, scope and VAT basis; empty and suppressed states are
designed, not accidental.

## Error shape

```ts
{ detail: string }   // FastAPI default; 401 unauthenticated, 403 wrong tenant, 422 bad body
```
