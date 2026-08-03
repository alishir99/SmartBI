# API contract — frozen interface between backend and frontend

This file is the coordination point for parallel work. **Backend and frontend are built
against this document, not against each other.** If you need to change a shape here, say so
explicitly rather than changing it silently — someone else has already coded against it.

Money is always SEK excluding VAT. Text shown to users is Swedish; code, comments and
identifiers are English.

---

## Auth

```
POST /api/auth/login       {email, password}  →  {access_token, token_type: "bearer", user}
GET  /api/auth/me                             →  User
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

All other endpoints require `Authorization: Bearer <token>`. `supplier_id` is taken from the
verified token and never from a request body or query string.

Demo accounts (seeded, password `demo1234`):

| email | supplier |
|---|---|
| `anna@nordstromaudio.se` | Nordström Audio AB (the demo tenant) |
| `erik@lagerkvisthem.se` | Lagerkvist Hem AB (for showing isolation live) |

---

## Core shared types

```ts
type Column = {
  key: string
  type: "date" | "text" | "number"
  label: string
  unit?: "SEK" | "st" | "%" | null
}

// The model emits a ChartSpec. It never emits values — only which columns to draw.
type ChartSpec = {
  type: "line" | "bar" | "stacked_bar" | "area" | "pie" | "kpi" | "table"
  x: string | null            // column key
  y: string[]                 // one or more measure column keys
  series: string | null       // column key to split series by
  sort: "asc" | "desc" | null
  limit: number | null
  title: string
  subtitle: string | null
  markers: string[]           // x values worth a line; server-owned, stripped off model specs
  marker_label: string | null // what those lines mean, shown under the plot
}

type Provenance = {
  tool: string               // "query_sales" | "query_market_share" | "dashboard"
  source: string             // "mv_sales_daily (rollup)" | "fact_sales_line" | ...
  scope: string              // "supplier:8f2a" — hashed, not the raw id
  currency: "SEK"
  vat: "exkl. moms"
  time_range: { from: string; to: string }        // ISO dates
  compare_range: { from: string; to: string } | null
  coverage: { from: string; to: string }
  filters_applied: Record<string, unknown>
  row_count: number
  truncated: boolean
  executed_at: string        // ISO timestamp
  tool_args: Record<string, unknown>              // shown when the chip is expanded
}

// The single unit both the dashboard and the chat produce. One card type, two producers —
// which is what lets a chat answer be pinned next to a standard tile.
type AnswerCard = {
  card_id: string | null     // set once saved
  status: "ok" | "cannot_answer" | "clarify" | "validation_failed"
  narrative: string          // Swedish prose; empty when status != "ok"
  insights: string[]
  caveats: string[]
  chart: ChartSpec | null
  query_id: string | null    // fetch full data from /api/result/{query_id}
  columns: Column[]
  provenance: Provenance | null
  suggestions: string[]      // for cannot_answer / clarify: what CAN be asked
}
```

### Status semantics — the frontend must render these differently

| status | meaning | render |
|---|---|---|
| `ok` | answered from tool data | narrative + chart + source chip |
| `clarify` | entity ambiguous, needs a choice | question + clickable candidate chips, no chart |
| `cannot_answer` | outside what the data can answer | explanation + `suggestions` as clickable prompts |
| `validation_failed` | a number in the prose did not match the data, twice | chart only, prose suppressed, visible warning |

`validation_failed` is not an error state to hide. It is the guarantee working, and the UI
should say so plainly: *"Svarstexten kunde inte verifieras mot datan och har därför
utelämnats. Diagrammet nedan kommer direkt från databasen."*

---

## Dashboard — deterministic, no LLM

```
GET /api/dashboard?period=…  →  { kpis: Kpi[], cards: AnswerCard[] }
```

Goes through the same MCP tools as the chat, server-side, with no model involved. Same
numbers, same provenance, guaranteed.

`period` is a key from `PERIODS`; an unknown value falls back to the default rather than
erroring. The comparison follows the filter and is not separately selectable: every delta is
measured against the window immediately before the selected one (`compare_to:
previous_period`). It reaches the KPI deltas, the trend overlay and the share tile together,
so no two numbers on the screen are measured against different windows.

```ts
type Kpi = {
  key: "net_sales_sek" | "category_share_pct" | "units" | "avg_price_sek"
  label: string              // "Försäljning", "Andel av kategori", ...
  value: number
  unit: "SEK" | "st" | "%"
  delta_pct: number | null   // vs the previous window; percentage *points* when unit is "%"
  delta_label: string | null // "vs föregående period"; null when there is nothing to compare
  rank_label: string | null  // "#2 av 6 varumärken"
  spark: number[]            // the measure over the period's own grain, oldest first; [] if none
}
```

`delta_pct` is null when the comparison window returned nothing to compare against, or falls
outside the data's coverage — the tile then reads "Ingen jämförelseperiod".

Cards returned, in order: the sales trend over the period's own grain, top 10 products, sales
by region. Each is a full `AnswerCard` with `chart` and `query_id` set. The trend card's title
follows the grain ("Försäljning per månad", "…per vecka"), and it carries a derived
`net_sales_sek_ma` column — a trailing three-bucket mean drawn as a line over the bars.

```
GET /api/movers?period=…  →  { cards: AnswerCard[] }
```

Biggest risers then biggest fallers, ten each, sorted on the derived `net_sales_sek_delta_pct`
column. This is the one place that column is on the value axis — everywhere else a percentage
next to kronor is the bug the filter exists for. The comparison is the window before the
selected one, as everywhere else.

---

## Chat — SSE

```
POST /api/chat   { question: string, history?: {role, content}[] }
```

Responds `text/event-stream`. Each event is `data: <json>\n\n`:

```ts
type ChatEvent =
  | { type: "status";   message: string }                    // "Hämtar försäljning…"
  | { type: "tool_call"; tool: string; args: object }         // shown as a progress chip
  | { type: "tool_result"; tool: string; row_count: number }
  | { type: "token";    text: string }                        // narrative, streamed
  | { type: "preview";  card: AnswerCard }                    // chart only; not terminal
  | { type: "card";     card: AnswerCard }                    // terminal on success
  | { type: "error";    message: string }                     // terminal on failure
```

Streaming the *tool calls* is a trust feature, not a latency feature — the user watches the
system go to the database.

`preview` carries a card with the chart and an empty narrative, emitted as soon as a row
tool returns — seconds before the prose is written and validated. It may arrive more than
once in a turn; each one replaces the last, and the terminal `card` replaces them all. The
chart was never the untrusted half — it is drawn from the cached rows via
`/api/result/{query_id}`, not from the model — so showing it early costs nothing in trust.
The prose is still withheld until it has been validated. A stream that ends on a `preview`
ended early and is an error, not an answer.

---

## Result data — where charts get their numbers

```
GET /api/result/{query_id}?offset=0&limit=1000
  →  { query_id, columns: Column[], rows: object[], row_count, truncated }
```

The chart is drawn from this, never from the model's output. Cached server-side, scoped to
the requesting tenant; another tenant's `query_id` returns 404, not 403 (a 403 would confirm
the id exists).

---

## Saved views, export, share

```
GET    /api/cards                →  AnswerCard[]
POST   /api/cards                {title, chart, tool_name, tool_args}  →  AnswerCard
DELETE /api/cards/{card_id}      →  204
GET    /api/export/{query_id}.csv → text/csv  (sv-SE: semicolon separated, comma decimal)
POST   /api/share                {card_id, mode: "snapshot" | "live"} → {url, expires_at}
GET    /api/shared/{token}       →  SharedView          ← no Authorization header
```

Saving persists the **spec plus the tool arguments**, not a screenshot, so a saved card
re-runs live against fresh data. `POST /api/cards` caps a supplier at 200 saved views.

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

The only unauthenticated route in the API. Everything it may read comes from the signed
token: which card, and whose scope the query runs under — so the reader cannot widen either,
and a live link always re-executes as the supplier who shared it, never as whoever opens it.
The rows travel inline because `/api/result` is scoped to a logged-in tenant, and no
`card_id` reaches the reader because every control keyed to it is an authenticated call.
Every failure — expired, tampered with, card deleted, wrong supplier — returns the same 404
and the same sentence.

`mode: "snapshot"` is accepted, carried in the token, and served as `live`: freezing rows
means storing them.

---

## Formatting rules the frontend owns

- `sv-SE` number formatting: space as thousands separator, comma as decimal
- Magnitude switching, with the unit always on the axis: `< 100 tkr` → `kr`,
  `< 10 Mkr` → `tkr`, otherwise `Mkr`
- Percentages: one decimal
- Deltas always carry the comparison period as a label — never a bare `▲ 8,2 %`
- ISO weeks; Swedish month names
- Every card states period, scope and "exkl. moms"
- Empty and suppressed states are designed, not accidental

## Error shape

```ts
{ detail: string }   // FastAPI default; 401 unauthenticated, 403 wrong tenant, 422 bad body
```
