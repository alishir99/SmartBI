# AI-native försäljningsdashboard — Design rationale

**Case:** Solvigo utvecklarcase — "BI utan BI-avdelning"
**Author:** Ali Shirzad
**Written:** 2026-07-27, before the code

> This document is the design rationale, written as the plan and kept as written. Every
> significant choice is stated as *decision → alternatives considered → why this one*.
> Where the build later departed from it, the README is what shipped and this is what was
> intended; the gap is itself part of the answer.

---

## 1. What the case actually asks for

Restated from `utvecklarcase-solvigo.pdf`, in the order it will be graded:

| # | Requirement | Where it's addressed |
|---|---|---|
| 1 | Ready-made answers on arrival — a standard dashboard per supplier (trend, market share, top lists) with zero configuration | §7 Frontend, §5 Data model |
| 2 | Natural-language questions **with charts generated on demand** | §6 Agent, §8 Chart contract |
| 3 | Numbers must be trustworthy, in a unit that means something to the customer | §9 Grounding |
| 4 | Save / export / share views | §10 |
| 5 | Frontend React/Vite, backend Python/FastAPI | §4 |
| 6 | **Data only reachable through an MCP server** — the LLM must use it | §4, §6 |
| 7 | A data source the MCP server reads from | §5 |

The five questions they deliberately left unanswered — and my short answers:

| Their question | My answer in one line |
|---|---|
| How does the LLM go from free text to a correct aggregate without inventing numbers? | A typed semantic-layer MCP tool + the numbers never pass through the model's token stream (§9). |
| How do you model the data, and raw vs precomputed behind the MCP server? | Star schema is the truth; rollups exist for latency **and as a privacy boundary** (§5.3). |
| How do you keep a supplier scoped, and what may they see about others? | Tenant ID comes from the JWT, never from the model; competitors only as k-anonymised aggregates (§11). |
| How do you present an answer so it becomes a saveable chart/card? | The model emits a validated `ChartSpec`, not values; cards are the shared unit between dashboard and chat (§8, §10). |
| How do you handle questions the data can't answer? | A capability catalogue the model can read + an explicit `cannot_answer` path that suggests what *is* possible (§9.4). |

---

## 2. Product concept (what the user sees)

A supplier (e.g. a manufacturer whose brand is sold through the retailer) logs in and lands on
a **finished dashboard** — not an empty chat box.

```
┌──────────────────────────────────────────────────────────────────────┐
│  Solvigo Insights          Leverantör: Nordströms Audio AB    [ ⌄ ]  │
├────────────┬─────────────────────────────────────────────────────────┤
│ Översikt   │  Försäljning     Andel av      Sålda        Snittpris   │
│ Produkter  │   12,4 Mkr        kategori     enheter        349 kr    │
│ Geografi   │   ▲ 8,2 %          18,3 %       35 512        ▼ 2,1 %   │
│ Mina vyer  │                    #2 av 7                              │
│            ├─────────────────────────────────────────────────────────┤
│            │  [ Försäljning per månad   ditt märke vs kategoriindex ] │
│            ├──────────────────────────┬──────────────────────────────┤
│            │ [ Topp 10 produkter ]    │ [ Försäljning per region ]   │
│            └──────────────────────────┴──────────────────────────────┘
│            ┌─── Fråga din data ─────────────────────────────────────┐ │
│            │ "Vilka produkter säljer bäst i Stockholm?"             │ │
│            │   resolve_entities →  query_sales (1 243 rader)      │ │
│            │  [ genererat stapeldiagram ]      [ Spara] [⬇ CSV]   │ │
│            │  Källa: query_sales · Sthlm län · 2026-01→06 · 14:32   │ │
│            └────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

**The product thesis, stated for the video:** "BI without a BI department" means the user must
never *build* anything. The dashboard is the answer to the questions we already know they have.
The chat is a **deepening mechanism**, not the entry point. Both produce the same object — a
**card** — so anything the chat produces can be pinned next to the standard tiles. That single
decision (one card type, two producers) is what keeps the product from feeling like "a chatbot
bolted onto a dashboard".

---

## 3. Decision log (the short version)

| # | Decision | Chosen | Rejected alternatives | Why |
|---|---|---|---|---|
| D1 | LLM provider | **DeepSeek `deepseek-v4-pro`, driven through the Anthropic SDK** against `https://api.deepseek.com/anthropic` | Claude direct; Gemini + Google ADK; OpenAI | Availability decided this: the API key I have is DeepSeek's. DeepSeek ships an Anthropic-compatible endpoint with full `tools` support (`name` / `input_schema` / `description`), which is near-1:1 with MCP's own tool schema — so the code stays Anthropic-shaped and moving to real Claude is a `base_url` plus model-name change, nothing more. That makes "the provider is swappable at one file" a demonstrable fact rather than a claim. Costs, stated honestly: `cache_control` is ignored on this endpoint, so the prompt-caching saving in §6.4 does not apply; and the data leaves the EU, which weakens the residency half of §15. |
| D2 | Agent orchestration | **Explicit bounded tool loop + a thin 3-stage pipeline** (plan → execute → validate/render) | LangGraph, Google ADK, Anthropic SDK Tool Runner | The Tool Runner is the natural choice against real Claude, but it rides on `anthropic-beta` headers that the DeepSeek endpoint does not accept — so the loop is written out by hand, roughly 40 lines with a tool-call cap and a retry. LangGraph/ADK add graph and state machinery for what is a single bounded loop. |
| D3 | **MCP wiring** | Backend is the **MCP client**; MCP server is an internal service | Anthropic's hosted MCP connector (`mcp_servers` param) | The connector requires a publicly reachable MCP server and moves tenant credentials to the model provider. Being the client ourselves is what lets us inject `supplier_id` server-side and intercept every result before the model sees it. **This is the load-bearing security decision.** |
| D4 | MCP transport | **Streamable HTTP** | stdio | stdio couples the MCP server to the API process lifecycle. HTTP lets it be its own container, its own Cloud Run service with `ingress: internal`, and independently scalable/testable. |
| D5 | **Tool surface shape** | **One flexible, typed semantic-layer query tool** (`query_sales`) + 3 supporting tools | (a) Text-to-SQL tool; (b) one tool per question type (`get_top_products`, `get_trend`, …) | (a) is unsafe and untestable: injection, fan-out double counting on a star schema, no place to attach units, and tenant scoping via string-injected `WHERE` is fragile. (b) cannot answer questions we didn't anticipate — and **they will ask unseen questions live**. A cube-style query tool is bounded *and* composable. |
| D6 | Database | **PostgreSQL 16 + pgvector + pg_trgm** | DuckDB/Parquet, SQLite, ClickHouse | Matches the stack in the ad (Postgres + pgvector, Cloud SQL). RLS gives defence-in-depth on tenancy — no analytical DB in this class offers that. pgvector earns its place on entity resolution (§5.4), not as decoration. |
| D7 | Dataset | **Generated synthetic Swedish retail data (seeded, deterministic)** | Online Retail II (UCI), Olist, Superstore | See §5.1 — the deciding factor is that a generator gives me a **ground-truth oracle** for an automated eval suite. No public set has the supplier↔competing-brand structure market share requires. |
| D8 | Chart contract | **Constrained internal `ChartSpec` JSON, Pydantic-validated, rendered with Recharts** | Vega-Lite spec from the model; model-generated plotting code | Vega-Lite is more expressive but far harder to validate and lets the model produce charts that look nothing like the dashboard. Generated code means arbitrary execution. A closed spec = every chart is consistent and every spec is verifiable. |
| D9 | Grounding | **Values never pass through the model** (§9) | "Just prompt it not to hallucinate"; post-hoc checking only | The strongest guarantee is structural, not behavioural. The model picks the query and the presentation; the numbers travel Postgres → MCP → API → chart on a path the model never touches. |
| D10 | Dashboard data path | The standard dashboard **also goes through MCP** (server-side, no LLM) | A separate direct-SQL path for the dashboard | Makes MCP the app's actual data API rather than an LLM side-car, and guarantees the chat and the dashboard can never disagree about a number. Also honours the case's "you don't reach the data directly". |
| D11 | Auth | JWT (HS256 in MVP) + Postgres **RLS** | App-layer filtering only | Two independent layers. A bug in tool code still can't leak another supplier's rows. |
| D12 | Streaming | **SSE** from FastAPI | WebSocket; plain request/response | One-directional, trivially proxied, and streaming *tool calls* ("hämtar försäljning för Stockholm…") is a trust feature, not just a latency feature. WebSocket buys nothing here. |

---

## 4. Architecture

```
┌───────────────────────────────────────────────────────────────────────────┐
│  React 19 + Vite + TS      Recharts · TanStack Query · shadcn/ui          │
│  Dashboard (cards)  ·  Chat panel (SSE)  ·  Mina vyer                     │
└───────────────┬───────────────────────────────────────────────────────────┘
                │ HTTPS + JWT (Bearer)   /api/*   ·   SSE for /api/chat
┌───────────────▼───────────────────────────────────────────────────────────┐
│  FastAPI                                                                  │
│   ├ auth: JWT → TenantContext{supplier_id, role}   ← never model-supplied │
│   ├ /api/dashboard   deterministic, no LLM                                │
│   ├ /api/chat        agent turn (SSE)                                     │
│   ├ /api/result/{query_id}   full result set (paged) ── chart data source │
│   └ /api/cards, /api/export, /api/share                                   │
│                                                                           │
│   Agent pipeline:                                                         │
│     1. PLAN+EXECUTE  Anthropic Tool Runner  ⇄  Claude Opus 5              │
│     2. VALIDATE      numeric + schema + scope validator                   │
│     3. RENDER        AnswerCard{narrative, ChartSpec, query_id, sources}  │
└───────────────┬───────────────────────────────────────────────────────────┘
                │ MCP (streamable HTTP, internal only)
                │ TenantContext injected here   NOT part of any tool schema
┌───────────────▼───────────────────────────────────────────────────────────┐
│  MCP Server (Python, FastMCP)          "the semantic layer"               │
│   get_capabilities()        what exists, what units, what's allowed       │
│   resolve_entities()        free text → canonical IDs (trgm + pgvector)   │
│   query_sales()             measures × dimensions × filters → rows        │
│   query_market_share()      own vs category, k-anonymised, never named    │
└───────────────┬───────────────────────────────────────────────────────────┘
                │ asyncpg, role `app_readonly`, SET LOCAL app.supplier_id
┌───────────────▼───────────────────────────────────────────────────────────┐
│  PostgreSQL 16 + pgvector + pg_trgm                                       │
│   star schema (facts + dims) · materialised rollups · RLS policies        │
│   product/category embeddings for entity resolution                       │
└───────────────────────────────────────────────────────────────────────────┘
```

**Note the two consumers of the MCP server.** The deterministic dashboard and the LLM agent
call the *same four tools*. That is the answer to "är samspelet genomtänkt": MCP isn't a
wrapper we added for the LLM's benefit, it's the only way anything reads data.

---

## 5. Data

### 5.1 Dataset: build, don't borrow

I evaluated three well-known public retail sets against what this case needs:

| Dataset | Orders | Geography | Product hierarchy | **Brand / supplier** | Verdict |
|---|---|---|---|---|---|
| [Online Retail II (UCI)](https://archive.ics.uci.edu/dataset/502/online+retail+ii) | ~1M lines | Country only | no (free-text descriptions) | none | No brand ⇒ no market share, which is half the case |
| [Olist (Brazilian e-com)](https://www.kaggle.com/datasets/terencicp/e-commerce-dataset-by-olist-as-an-sqlite-database) | 100k orders | good (state/zip) | categories | ~ sellers ≈ suppliers, but no competing brands per category | Closest structurally; Brazilian geography kills the "Stockholm" demo |
| [Superstore](https://www.kaggle.com/datasets/nayakganesh007/superstore-sales-dataset) | 5k orders | US | cat/subcat | none | Too small, fictional anyway, no brand |

**Decision: generate a synthetic Swedish retail dataset** with a seeded, deterministic
generator (`scripts/generate_data.py`, `--seed 42`). Three reasons, in priority order:

1. **It gives me a ground-truth oracle.** Because I define the demand curves, seasonality,
   regional multipliers and campaign effects, I know the correct answer to every question
   *without asking the system*. That turns "does the LLM hallucinate?" from an opinion into
   an automated test suite (§13.2). No borrowed dataset can do this.
2. **Market share requires structure no public set has**: several competing brands per
   category, each owned by a different supplier, with overlapping product ranges. Without
   that, "hur går det för vårt märke jämfört med konkurrenterna?" is unanswerable.
3. **The demo has to feel real to a Swedish audience.** "Vilka produkter säljer bäst i
   Stockholm?" is one of *their own example questions*. Brazilian states don't land.

Honest counter-argument, which I'll state in the video rather than hide: synthetic data can
be too clean, and a model that works on clean data can fall over on real data. Mitigation  
the generator deliberately injects realistic mess: ~1.5 % returns, ~0.8 % NULL customer ids
(cash purchases), a discontinued product with a truncated series, one store that opened
mid-period, price changes over time, and a category where one brand has only 3 competitors
so the k-anonymity suppression path (§11.3) actually fires in the demo.

Shape: ~8 suppliers, ~14 brands, 6 categories / ~22 subcategories, ~400 products, ~60 stores
across all 21 Swedish län + an online channel, 24 months of history, ~800k order lines.
Big enough to be non-trivial, small enough to `COPY` in seconds.

### 5.2 Schema (star)

```sql
dim_supplier   (supplier_id, name, org_nr, country)
dim_brand      (brand_id, supplier_id → dim_supplier, name)
dim_category   (category_id, parent_id → dim_category, name, level)   -- hierarchy
dim_product    (product_id, brand_id, category_id, name, ean,
                list_price_sek, launch_date, discontinued_date)
dim_store      (store_id, name, channel['fysisk'|'online'], city,
                municipality, region /* län */, lat, lon, opened_date)
dim_customer   (customer_id, pseudonym_id, segment, region,
                age_bucket, loyalty_tier)                 -- no direct identifiers
dim_date       (date_id, date, iso_year, iso_week, month, quarter, year,
                weekday, is_holiday, campaign_id)

fact_sales_line(sale_line_id, order_id, date_id, store_id, customer_id,
                product_id, quantity, gross_amount_sek, discount_amount_sek,
                net_amount_sek, is_return)
```

Grain: **one row per order line**. Everything else is derivable. Money in `SEK`, excl. VAT,
stated in the column name and re-stated in every tool response's `meta.unit` — the case
explicitly asks about "en enhet som är meningsfull för kunden" (§9.3).

### 5.3 Raw vs precomputed — and why that's a privacy decision

Their question: *"vad lägger MCP-servern bakom sig (rådata vs förberäknat)?"*

The fact table is the source of truth. The MCP server serves from **materialised rollups**
where one exists and falls back to the fact table otherwise, transparently — the tool
response reports which in `meta.source`.

```sql
mv_sales_daily      (date, product_id, region, channel)     → qty, net, gross, discount
mv_category_daily   (date, category_id, region, channel)    → total_qty, total_net, n_brands
mv_brand_monthly    (month, brand_id, category_id, region)  → net, category_net, share_pct, rank
```

Rollups exist for two distinct reasons and I want both on the record:

- **Latency.** The standard dashboard is 6 tiles; hitting the fact table for each on every
  load is wasteful when the answer changes once a day.
- **It is the privacy boundary.** `mv_category_daily` and `mv_brand_monthly` are the *only*
  objects `query_market_share` may read. Competitor data is therefore not "filtered out" by
  application logic — it was never in the object the tool can reach. A rollup that aggregates
  away identity is a structurally stronger guarantee than a `WHERE` clause.

Refresh: `REFRESH MATERIALIZED VIEW CONCURRENTLY` after seed and via an authenticated
`POST /admin/refresh`. In production this belongs in the ingest pipeline (§14).

### 5.4 pgvector — used for something real

pgvector is in the job ad; I refuse to add it as decoration. Its actual job here is
**entity resolution**, which is a genuine failure mode: a user types *"hörlurar"*,
*"sthlm"*, *"vårt bästa märke"*, *"trådlösa lurar"* — none of which are column values.

`resolve_entities()` runs a hybrid retrieval over `dim_product`, `dim_category`,
`dim_store`, `dim_brand`:

- lexical: `pg_trgm` similarity on names/synonyms (catches typos, "Göteborg"/"Goteborg")
- semantic: pgvector cosine over embeddings of `name + category path + synonyms`
- fused with Reciprocal Rank Fusion, returns top-k **candidates with scores**, never a
  single silent guess

Embeddings from a local `intfloat/multilingual-e5-small` (handles Swedish, no API cost,
no data leaves the box). If it returns nothing above threshold, the tool returns
`{"matches": [], "hint": "..."}` and the agent must ask a clarifying question rather than
invent an entity — this is one of the two main hallucination entry points closed.

---

## 6. The MCP server — the heart of the design

### 6.1 Why a semantic layer and not text-to-SQL

This is the single decision I expect to be interrogated hardest, so:

| | Text-to-SQL | One tool per question | **Semantic-layer query tool** |
|---|---|---|---|
| Handles unseen questions | yes | no | **yes** |
| Cannot produce an invalid join / fan-out double count | no | yes | **yes** |
| Tenant scope enforceable server-side | string injection | yes | **yes** |
| Units/currency attachable to the result | no | yes | **yes** |
| Unit-testable in isolation | no | yes | **yes** |
| Bounded blast radius | no | yes | **yes** |

They said they will ask their own questions live. That eliminates column 2. Everything else
eliminates column 1. The semantic layer is the only cell that is both open-ended and safe.

### 6.2 Tool surface (deliberately small — 4 tools)

A small, orthogonal tool set measurably outperforms a large one. All schemas use
`strict: true` with enum-constrained fields and `additionalProperties: false`.

**1. `get_capabilities()`** — the model's map of the world. Returns available measures,
dimensions, filter fields with their allowed enum values, the date range actually covered
by the data, currency/units, granularity floor, and what this supplier may see about
others. Cached in the system prompt prefix (§6.5). *This is what makes "I can't answer
that" possible instead of a guess.*

**2. `resolve_entities(text, kinds[], limit)`** → `[{kind, id, label, score, path}]`
Free text → canonical IDs (§5.4). The agent must call this before filtering by any name.

**3. `query_sales(...)`** — the workhorse.

```jsonc
{
  "measures":    ["net_sales_sek", "units", "avg_price_sek", "discount_rate"],  // enum
  "dimensions":  ["month", "product", "category", "region", "store", "channel"],// enum
  "filters":     { "product_ids": [...], "category_ids": [...],
                   "region": ["Stockholms län"], "channel": ["fysisk"] },
  "time_range":  { "from": "2026-01-01", "to": "2026-06-30" },   // or "last_12_months"
  "compare_to":  "previous_period" | "same_period_last_year" | null,
  "order_by":    { "measure": "net_sales_sek", "dir": "desc" },
  "limit":       50
}
```

Response:

```jsonc
{
  "query_id": "q_01J...",           // full result set held server-side
  "columns":  [{"key":"month","type":"date"},
               {"key":"net_sales_sek","type":"number","unit":"SEK","label":"Nettoförsäljning"}],
  "rows":     [...],                 // capped preview for the model
  "row_count": 1243,
  "meta": { "source":"mv_sales_daily", "scope":"supplier:8f2a",
            "currency":"SEK", "vat":"exkl. moms",
            "coverage":{"from":"2024-07-01","to":"2026-06-30"},
            "truncated": true, "executed_at":"2026-07-27T14:32:11Z" }
}
```

Note `compare_to` — period-over-period is the single most common analyst follow-up
("och jämfört med förra året?"), and folding it into the tool means the model doesn't
have to orchestrate two calls and subtract, which is exactly where arithmetic errors
would creep in. **Never let the model do arithmetic it can ask the database to do.**

**4. `query_market_share(...)`** — separate tool precisely *because* it reads beyond the
supplier's own rows. Returns `{own_net, category_net, share_pct, rank, n_brands, suppressed}`
from the aggregate rollups only. Competitor brands are never named, never itemised.
Separating it makes the privileged read auditable in one place instead of being a flag
buried in `query_sales`.

**Considered and deferred:** a guarded read-only SQL escape hatch over an RLS-protected
view layer (statement timeout, forced `LIMIT`, parsed allowlist, same numeric validation).
It genuinely covers the long tail. It is **not in the MVP** because it weakens the one
guarantee I most want to be able to state without caveats — that a returned number is
always the output of a tested aggregation. I'd rather the system say *"det kan jag inte
svara på med den data jag har — men jag kan visa X"* than risk a plausible wrong number.
That trade is itself the answer to their question 5.

### 6.3 Tenant injection — the important bit

`supplier_id` **does not appear in any tool's input schema.** The model literally cannot
express "show me supplier 7's data". The FastAPI layer holds a request-scoped
`TenantContext` from the verified JWT and attaches it to the MCP call as out-of-band
metadata; the MCP server sets `SET LOCAL app.supplier_id` on the connection, and Postgres
RLS does the rest.

Three independent layers, any one of which is sufficient:
1. The parameter doesn't exist in the schema the model sees.
2. The MCP server derives scope from the connection context, not the arguments.
3. RLS policies on `fact_sales_line` and the rollups.

### 6.4 Agent loop

```python
# Provider behind one interface   swapping to real Claude touches base_url and model only.
client = AsyncAnthropic(api_key=settings.llm_api_key, base_url=settings.llm_base_url)

response = await client.messages.create(
    model=settings.llm_model,                 # deepseek-v4-pro
    max_tokens=8000,
    tools=[to_anthropic_tool(t) for t in (await mcp_session.list_tools()).tools],
    system=SYSTEM,
    messages=history + [{"role": "user", "content": question}],
)
# … then a bounded `while response.stop_reason == "tool_use"` loop, capped at
# MAX_TOOL_CALLS, dispatching each tool_use block to the MCP session.
```

MCP's tool descriptor is `{name, description, inputSchema}` and Anthropic's is
`{name, description, input_schema}`, so `to_anthropic_tool` is a rename, not an adapter
layer. That near-identity is what survives the provider change intact.

Model: **`deepseek-v4-pro`** (the endpoint maps `claude-opus-*` onto it; `claude-sonnet-*`
and `claude-haiku-*` map to `deepseek-v4-flash`). Tool use in thinking mode is supported
from DeepSeek-V3.2 onward.

Consequences of the provider, stated rather than buried:

- **Prompt caching does not apply.** The endpoint ignores `cache_control`, so the ~90 %
  saving on the stable prefix (system prompt + tool definitions + capability catalogue,
  ≈ 3–4k tokens) is unavailable. Against real Claude the same code gets it back by adding
  the field — the prefix is already structured as a stable block for exactly that reason.
- **Model routing** — `deepseek-v4-flash` for a cheap first-pass intent classifier, `-pro`
  for the real turn — remains available and is documented as a next step, not MVP.
- **Strict schemas.** DeepSeek's OpenAI-compatible route offers `strict: true` (requiring
  every property required and `additionalProperties: false`); the tool schemas in §6.2 are
  already written that way, so nothing has to change if we move to that route.

One behavioural note that matters for a demo: I will not disable thinking. A thinking-off
route can emit a tool call as plain prose that silently never runs — which on stage looks
exactly like a confident hallucinated number, the one failure this whole design exists to
prevent.

### 6.5 System prompt contract

Short, explicit, and the enforcement lives in code rather than in hope:

1. You may not state a number that did not come from a tool result.
2. Resolve every entity with `resolve_entities` before filtering by name.
3. Prefer one `query_sales` call with `compare_to` over two calls plus arithmetic.
4. If `get_capabilities` doesn't cover it, return `status: "cannot_answer"` with a
   suggestion — never approximate.
5. Answer in Swedish. Money in SEK excl. VAT, formatted sv-SE. State the period.
6. Final output must validate against the `AnswerCard` schema.

---

## 7. Frontend

React 19 + Vite + TypeScript · Tailwind + shadcn/ui · Recharts · TanStack Query ·
Zustand for chat state · SSE consumed via `fetch` + `ReadableStream` (not `EventSource`,
which can't send an `Authorization` header).

**Recharts over ECharts/Visx**: the chart vocabulary here is small and closed (line, bar,
stacked bar, area, pie, KPI, table) and Recharts composes cleanly with a validated spec.
ECharts is more powerful and heavier than this needs; Visx is more work for the same result.

Presentation rules that answer *"visas i en enhet som är meningsfull"*:

- SEK, `sv-SE` formatting — space thousands separator, comma decimal
- Automatic magnitude: `< 100 tkr` → kr, `< 10 Mkr` → tkr, else Mkr — unit always on the axis
- Percentages one decimal; deltas always carry the comparison period as a label
- ISO weeks, Swedish month names
- Every card states period + scope + "exkl. moms"
- Empty and suppressed states are designed, not accidental (§11.3)

---

## 8. Chart-on-demand contract

The model emits a **spec**, never values:

```jsonc
{
  "chart": { "type": "bar", "x": "product", "y": ["net_sales_sek"],
             "series": null, "sort": "desc", "limit": 10,
             "title": "Topp 10 produkter i Stockholms län",
             "subtitle": "jan–jun 2026 · nettoförsäljning, exkl. moms" },
  "query_id": "q_01J...",
  "narrative": "...",
  "insights": ["..."],
  "caveats": ["..."]
}
```

Backend validates that every referenced column exists in `query_id`'s result set and that
the type is compatible (you cannot put a text column on a numeric axis). The frontend then
fetches the **full** result set from `/api/result/{query_id}` and renders. Consequences:

- The chart's values were never in the model's output. If the model hallucinated in prose,
  the chart still shows the truth — and the validator (§9.2) catches the prose.
- Large result sets never enter the context window (only a capped preview does), so a
  1 200-row answer costs the same tokens as a 10-row one.

**Deterministic-first chart selection:** the backend proposes a chart type from the result
shape (one time dimension → line; one categorical + one measure → bar; part-of-whole →
stacked bar). The model may override with a reason. This keeps charts consistent even
when the model is careless, which matters more for "produktkänsla" than model freedom does.

---

## 9. Grounding — the core claim

> **The numbers you see never passed through the language model.**

### 9.1 Structural (primary)
Postgres → MCP → FastAPI → chart. The model chooses *the query* and *the presentation*;
the values travel a path it doesn't touch. This is a property of the architecture, not of
prompt quality, which is why I lead with it.

### 9.2 Validation (secondary — for prose)
The narrative *is* generated text, so after the tool loop and before responding:
- extract every numeric literal from the narrative
- assert each is present in the result set for `query_id`, or is a whitelisted derivation
  of it (sum / mean / delta / share) within a rounding tolerance
- on failure: one bounded regeneration with the offending value quoted back; on second
  failure, drop to a chart-only card with the prose suppressed and a visible notice

Failing loudly and visibly beats failing plausibly.

### 9.3 Provenance (visible)
Every card carries a source chip: tool name · applied filters · scope · row count ·
data source (rollup vs fact) · timestamp. Expanding it shows the exact tool call arguments.
The user — and the grader — can see the chain for any number on screen. That is the
demonstrable answer to *"kan vi lita på att svaren kommer från datan?"*.

### 9.4 The "can't answer" path
Three distinct failure modes, three distinct behaviours:

| Situation | Behaviour |
|---|---|
| Entity not resolvable ("visa Nikes siffror" when they aren't your brand) | Clarifying question with the nearest legitimate candidates |
| Metric doesn't exist (margin/COGS not exposed to suppliers) | `cannot_answer` + what *is* available from `get_capabilities` |
| Outside data coverage (asks about 2019; predicts the future) | State the actual coverage; offer the nearest answerable question |

The capability catalogue is what makes this graceful instead of a shrug — the model can
say *what it doesn't have*, not merely that it failed.

---

## 10. Save, export, share

- **Save**: pins the card to "Mina vyer". Persists the *spec plus the tool arguments*, not
  a screenshot — so a saved card can be re-run live against fresh data.
- **Export**: CSV from `/api/result/{query_id}`; PNG via `html-to-image` on the card node.
  PDF deferred (print stylesheet if time allows).
- **Share**: signed, expiring, read-only link. **Snapshot by default** — a frozen copy with
  its data and timestamp. Because a live link re-executes under *someone's* tenant scope,
  and getting that wrong is a data leak. "Live" is an explicit opt-in that re-runs strictly
  under the original supplier's scope.

---

## 11. Users, roles, isolation

### 11.1 Roles
| Role | Scope |
|---|---|
| `supplier_viewer` | Dashboard + chat, own supplier only |
| `supplier_admin` | + manage org's saved views and users |
| `retail_analyst` | The retailer's own staff — cross-supplier |
| `system_admin` | Ops |

### 11.2 Isolation (three layers, §6.3)
Schema omission → connection-scoped context → Postgres RLS. Plus an audit table logging
every turn: user, supplier scope, question, tools called, arguments, row counts, latency,
tokens, cost. Useful for debugging, billing, and GDPR accountability alike.

### 11.3 What a supplier may see about others — explicit policy
| | |
|---|---|
| Own brands | Full detail: product × store × day |
| Category / market totals | Aggregate only, k-anonymised |
| Own rank | "#2 av 7 varumärken i Hörlurar" |
| Named competitor figures | **Never** — not filtered, not reachable |
| Customer-level rows | **Never** — the tool's grain floor forbids it |

**k-anonymity:** market aggregates are suppressed unless the category contains ≥ 5 brands
and ≥ 100 transactions in the slice. Otherwise "din andel" would be arithmetic subtraction
away from a named competitor's revenue. The generator deliberately includes one thin
category so this suppression fires during the demo — I want to *show* the guard, not
assert it.

### 11.4 Other security measures
Argon2 password hashing; short-lived JWT + refresh; strict Pydantic validation at every
boundary; per-tenant rate limits and a per-turn tool-call cap; MCP server not exposed to
the internet (`ingress: internal` on Cloud Run); DB role is read-only for query paths;
statement timeouts; secrets in Secret Manager, never in images; CORS allowlist; security
headers. Prompt injection is treated as a *data* risk: since the model can neither express
a cross-tenant query nor emit values, an injected instruction has no privileged path to
abuse — and the adversarial eval set (§13.3) proves it rather than assuming it.

---

## 12. Repository layout

```
solvigo-insights/
├─ docker-compose.yml
├─ README.md                      # architecture + choices (a required deliverable)
├─ .github/workflows/ci.yml
├─ db/
│  ├─ migrations/                 # Alembic
│  └─ sql/{schema,rollups,rls,indexes}.sql
├─ mcp_server/
│  ├─ server.py                   # FastMCP, streamable HTTP
│  ├─ tools/{capabilities,resolve,sales,market_share}.py
│  ├─ semantic/{measures,dimensions,compiler}.py   # spec → SQL, no free text
│  └─ tests/
├─ api/
│  ├─ main.py  auth.py  deps.py
│  ├─ agent/{loop,prompts,validate,render}.py
│  ├─ routes/{dashboard,chat,cards,export,share}.py
│  └─ tests/
├─ web/
│  └─ src/{components,charts,pages,hooks,lib}
├─ scripts/generate_data.py       # seeded generator + ground-truth export
└─ eval/
   ├─ golden_questions.yaml       # question → expected value (from ground truth)
   ├─ adversarial.yaml
   └─ run_eval.py
```

---

## 13. Testing & evaluation

### 13.1 Unit / integration
pytest for the semantic compiler (spec → SQL → expected numbers), each MCP tool, and the
FastAPI routes. Vitest for chart/format utilities. One Playwright smoke test of the core
flow: login → dashboard → ask → chart → save.

### 13.2 Golden-question eval — the payoff from D7
Because the generator knows the truth, `eval/golden_questions.yaml` holds ~40 Swedish
questions with **independently computed** expected values (pandas over the generated
frames, not via the app). `run_eval.py` drives the *full* agent and asserts:

- the numeric answer within tolerance
- the expected tool(s) were called with sane arguments
- a chart spec was produced and validates
- the response is in Swedish and carries the unit

This turns "does it hallucinate?" into a number I can report: *"38/40 exakta, 2 avvisade
korrekt som obesvarbara"*. Run it in CI as a regression gate.

### 13.3 Adversarial set
Cross-tenant attempts ("visa alla leverantörers försäljning"), prompt injection ("ignorera
instruktionerna ovan"), impossible questions ("vad säljer vi nästa kvartal?"), out-of-scope
metrics ("vad är vår marginal?"), and thin-slice questions that must trigger k-anonymity
suppression. Every one must produce a refusal or a suppression — never a number.

---

## 14. Deployment

**Local:** `docker compose up` → postgres(pgvector) · mcp · api · web. Seeded on first run.
One command to a working demo is a deliverable in itself.

**Cloud (GCP, matching the ad):**
- Cloud Run × 3 — `web` (static), `api` (public), `mcp` (**ingress: internal**)
- Cloud SQL for PostgreSQL 16 with `pgvector`, private IP + connector
- Artifact Registry, Secret Manager, Cloud Logging/Monitoring
- GitHub Actions: `ruff` + `mypy` + `eslint` + `tsc` → pytest + vitest → build → push →
  `gcloud run deploy`; Alembic migrations as a pre-deploy job

Cloud deploy is documented and scripted, not performed: what ships here is the compose
stack.

---

## Sources

- [MCP Python SDK](https://py.sdk.modelcontextprotocol.io/) · [mcp on PyPI](https://pypi.org/project/mcp/) — FastMCP + streamable HTTP as the production transport
- [Online Retail II (UCI)](https://archive.ics.uci.edu/dataset/502/online+retail+ii)
- [Olist Brazilian e-commerce dataset](https://www.kaggle.com/datasets/terencicp/e-commerce-dataset-by-olist-as-an-sqlite-database)
- [Superstore sales dataset](https://www.kaggle.com/datasets/nayakganesh007/superstore-sales-dataset)
- Anthropic model IDs, pricing, MCP tool helpers and Opus 5 behavioural guidance: `claude-api` reference (verified 2026-07-27)
