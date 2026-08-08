# Solvigo Insights

An AI-native sales dashboard for retail suppliers, "BI without a BI department." You log in
and land on a finished dashboard (no setup), then ask follow-up questions in a chat and get
answers with charts, in Swedish or English.

**The numbers never pass through the AI model.** It only picks which question to ask the
database and how to present the answer, the actual values travel Postgres → MCP → API →
chart, on a path the model never touches.

Full design reasoning (why Postgres, why this architecture, every trade-off): see
[`docs/DESIGN.md`](docs/DESIGN.md). This file is just: what it is, and how to run it.

> Shared for evaluation only , see [`LICENSE`](LICENSE). Not licensed for production use.

---

## Before you start

1. Install **[Docker Desktop](https://www.docker.com/products/docker-desktop/)** (this is the
   only thing you need installed Docker runs the database, backend and frontend for you).
2. In this folder, copy the example settings file and open it in any text editor:
   ```bash
   cp .env.example .env
   ```
3. In `.env`, set one line: `LLM_API_KEY=...` (a Claude or DeepSeek API key). Everything else
   already has a working default. **Without this key the app still runs fine**, dashboard,
   login, everything, only the chat is disabled, and it says so instead of breaking.

## Run it

```bash
docker compose up
```

That's it, one command. First run takes a minute or two (it builds the app and generates
sample data automatically). When it's ready:

- **App:** http://localhost:5173
- **API docs:** http://localhost:8000/docs

Log in with a demo account (password is `demo1234` for both):

| Email | Company |
|---|---|
| `ali@solvigo.se` | Nordström Audio AB |
| `sara@solvigo.se` | Lagerkvist Hem AB |

Try asking the chat: *"Which products sell best in Stockholm?"*, then log in as the other
account and ask the same thing. You'll get different, correct answers, because each account
only ever sees its own company's data.

To stop everything: `Ctrl+C`, then `docker compose down`.

## Running it without Docker

Only do this if you can't use Docker. You'll need Python 3.13, Node.js, and a PostgreSQL 16
database with the `pgvector` extension already running yourself.

**Every command below is run from this folder** (`solvigo-insights/`, where this README and
`pyproject.toml` live), open a terminal here first, and keep it open for all the steps.

```bash
uv venv                          # creates a virtual environment in .venv/
```

Then **activate it** you need to do this once per new terminal window, before any `python`,
`pytest` or `uvicorn` command below, or those commands run your system's Python instead of the
project's and fail with confusing "module not found" errors:

- macOS/Linux: `source .venv/bin/activate`
- Windows (PowerShell): `.venv\Scripts\activate`
- Windows (Git Bash): `source .venv/Scripts/activate`

Your prompt should now start with `(.venv)`. Then, still in this same terminal:

```bash
uv pip install -e ".[dev]"                 # installs the Python backend
python scripts/generate_data.py --seed 42  # creates sample data
python scripts/seed.py                     # loads it into your Postgres
python -m mcp_server.server                # starts the data server   → :8081
uvicorn api.main:app --reload              # starts the backend       → :8000
cd web && npm install && npm run dev       # starts the frontend      → :5173
```

`mcp_server.server` and `uvicorn` each block the terminal while running, so give each its own
terminal window (with the virtual environment activated again in each one, see above).

Same `.env` file and rules as above.

---

## How it's built

```
Frontend (React)  →  Backend (FastAPI)  →  MCP server  →  PostgreSQL
                              ↕
                             LLM
```

The frontend never talks to the database directly, every number, on the dashboard or in the
chat, comes from the same MCP server, which is the only thing allowed to read the database. The
AI model sits next to the backend, not in the data path: it chooses *what* to ask for and *how*
to show it, then the backend checks that every number it wrote actually exists in the real
result before showing it to you.

**Key choices, briefly** (full reasoning in [`docs/DESIGN.md`](docs/DESIGN.md)):

| Choice | Why |
|---|---|
| PostgreSQL + pgvector | Real relationships between products/brands/stores, database-level rules that keep one company from ever seeing another's data, and fuzzy text search, no simpler database gives all three. |
| One flexible data tool, not raw SQL | Suppliers ask unpredictable questions live. A fixed tool can't answer the unexpected; letting the AI write raw SQL is unsafe. A typed "ask for this metric, sliced this way" tool is both safe and flexible. |
| Numbers never touch the AI model | The model can only pick a question and a chart type. The actual figures are fetched separately and checked against the real database before display, grounding by construction, not by a well-written prompt. |
| Synthetic, generated data | Needed several competing brands per category (for market-share questions) and a known-correct answer key to test against, no public dataset offers both. |
| DeepSeek, via the Anthropic SDK | Anthropic-compatible endpoint, switching to real Claude later is a one-line config change, not a rewrite. |

---

## Tests

Run from this folder (`solvigo-insights/`), with the virtual environment active (see above,
`.venv\Scripts\activate` on Windows, `source .venv/bin/activate` on macOS/Linux):

```bash
pytest                 # backend + data logic, no database needed
cd web && npm test      # frontend
```
