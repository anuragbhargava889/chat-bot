# Company ChatBot

A Python web chatbot powered by **LangGraph ReAct agent** that intelligently routes natural-language questions across **multiple databases** (MySQL, PostgreSQL, MongoDB), a ChromaDB vector store, and a PDF knowledge library.

All database connections, table mappings, column hints, and JOIN relationships are **fully config-driven** — no code changes needed to add or remove a database.

---

## Features

| Feature | Description |
|---|---|
| **Multi-DB agent routing** | LLM picks the right database automatically based on tool descriptions — one tool per DB |
| **MySQL + PostgreSQL + MongoDB** | SQL databases use SELECT queries; MongoDB uses aggregation pipelines |
| **Config-driven** | Table names, column hints, and relationships live in per-DB JSON files — never hardcoded |
| **Auto schema sync** | Columns discovered from INFORMATION_SCHEMA (SQL) or document sampling (Mongo); FK relationships merged at startup |
| **Hybrid relationships** | FK-discovered JOINs merged with manual entries; custom `join_type` always preserved |
| **PDF Q&A** | Semantic search over uploaded PDFs via ChromaDB + sentence-transformers |
| **Chart generation** | LLM fetches data then calls `generate_chart` to render Chart.js bar/line/pie/doughnut |
| **Response confidence** | Every reply shows a confidence % based on query success and data completeness |
| **Multi-LLM** | Ollama, OpenAI, Anthropic, Groq — swap with one `.env` setting |

---

## Architecture

### File structure

```
chat-bot/
├── app.py                      # Flask server — auth, routes, SSE streaming
├── chatbot.py                  # LangGraph ReAct agent, multi-DB tools, confidence tracker
├── database.py                 # Auth + attendance DB operations
├── pdf_handler.py              # PDF loading, chunking, ChromaDB vector search
├── config.py                   # Env + JSON config loader; LLM factory; schema sync
│
├── config/                     # ← Configuration files (edit without touching code)
│   ├── databases.json          #   Master DB list — name, type, env_prefix, description
│   ├── database.json           #   SQL connection pool settings
│   ├── users.json              #   Local user store (auth fallback when no employees table)
│   └── dbs/                    #   Per-database config (one folder per entry in databases.json)
│       └── <db_name>/
│           ├── tables.json         #  MANUAL   — logical → actual table names  (SQL)
│           ├── collections.json    #  MANUAL   — logical → actual collection names  (MongoDB)
│           ├── table_columns.json  #  AUTO     — column hints (overwritten on sync)
│           ├── collection_columns.json # AUTO  — field hints  (overwritten on sync)
│           └── relationships.json  #  HYBRID   — FK-auto + manual JOIN entries
│
├── db/                         # ← Database adapter layer
│   ├── adapter.py              #   Abstract base (execute / execute_write / sanitize)
│   ├── mysql_adapter.py        #   MySQL  (mysql+mysqlconnector)
│   ├── postgresql_adapter.py   #   PostgreSQL (postgresql+psycopg2)
│   ├── factory.py              #   get_adapter(), build_adapter_for(), build_mongo_client()
│   ├── schema_inspector.py     #   Column + FK discovery for SQL and MongoDB
│   └── query_builder.py        #   Programmatic query builder (used by database.py)
│
├── requirements.txt
├── .env.example
├── pdfs/                       # Drop PDF files here
├── chroma_db/                  # ChromaDB vector store (auto-created, gitignored)
├── templates/
│   ├── base.html
│   ├── login.html
│   └── index.html              # Main chat UI
└── static/
    ├── css/style.css
    └── js/chat.js
```

### Request flow

```
Browser
  │  POST /api/chat  (NDJSON stream)
  ▼
app.py
  │  stream_message(message, user)
  ▼
chatbot.py  (LangGraph ReAct agent)
  │
  │  system prompt built from config/databases.json:
  │    [main_db]  MySQL  — tables + JOIN hints + tool: query_main_db / schema_main_db
  │    [hr_db]    PgSQL  — tables + JOIN hints + tool: query_hr_db   / schema_hr_db
  │    [logs_db]  Mongo  — collections + fields + tool: query_logs_db (pipeline)
  │
  ├─ tool: query_<name>      → SQL SELECT (MySQL/PgSQL)  |  aggregation pipeline (Mongo)
  ├─ tool: schema_<name>     → column info (SQL only)
  ├─ tool: search_pdf_library → ChromaDB semantic search
  ├─ tool: generate_chart    → Chart.js JSON payload
  ├─ tool: mark_attendance   → DB write  (when attendance table configured)
  └─ tool: get_attendance_report → DB read (when attendance table configured)
  │
  │  _ConfidenceTracker tallies outcomes throughout
  ▼
NDJSON:  {"status":"…"} | {"token":"…"} | {"done":true,"confidence":87}
  ▼
chat.js renders tokens live; "● Response Accuracy: 87%" footer appended
```

### How the agent decides which database to query

The LLM reads each tool's **name and description**:

```
query_sales_db   — "Sales — orders, products, customers, revenue"     → picks for revenue questions
query_hr_db      — "HR — employees, payroll, attendance"              → picks for HR questions
query_logs_db    — "App logs, user activity events, error reports"    → picks for log questions
```

For cross-database questions (e.g. "compare sales revenue with employee count by region") it calls multiple tools in sequence.

No routing code required — the LLM's tool-selection is the router.

### Config ownership

| File | Who writes it | Editable by user? |
|---|---|---|
| `databases.json` | User | Yes — add/remove databases |
| `dbs/<name>/tables.json` | User | Yes — add/remove tables |
| `dbs/<name>/collections.json` | User | Yes — add/remove collections |
| `dbs/<name>/table_columns.json` | **Auto sync** | No — overwritten on every sync |
| `dbs/<name>/collection_columns.json` | **Auto sync** | No — overwritten on every sync |
| `dbs/<name>/relationships.json` | **Hybrid** | Yes — manual JOIN entries are preserved |

### Schema auto-sync

At startup (and via the **Sync Schema** admin button), the app:

1. Reads each SQL DB's `tables.json` → queries `INFORMATION_SCHEMA.COLUMNS` → writes `table_columns.json`
2. Queries `INFORMATION_SCHEMA` FK constraints → hybrid-merges into `relationships.json`:
   - FK-discovered entry already in file → **file wins** (preserves custom `join_type`)
   - FK-discovered entry not in file → **auto entry added**
   - Manual entry (no FK backing) → **always kept**
3. For MongoDB: samples 20 documents per collection → infers field names → writes `collection_columns.json`

---

## Prerequisites

| Tool | Minimum | Notes |
|---|---|---|
| Python | 3.10 | |
| MySQL **or** PostgreSQL **or** MongoDB | 8.0 / 14 / 6.0 | At least one required |
| Ollama | latest | Required for `LLM_PROVIDER=ollama` only |

---

## Quick Start

### 1. Clone and install

```bash
git clone <repo-url>
cd chat-bot
python -m venv venv
source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

> `sentence-transformers` downloads `all-MiniLM-L6-v2` (~80 MB) on first run.

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — minimum for a single MySQL database:

```env
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=your_db
SECRET_KEY=replace-with-a-long-random-string
```

### 3. Declare databases in `config/databases.json`

The default file ships with one MySQL entry using the `DB` prefix (matching the env vars above):

```json
{
  "databases": [
    {
      "name": "main_db",
      "type": "mysql",
      "env_prefix": "DB",
      "description": "Main stock database — stock movement and user stock"
    }
  ]
}
```

Add more entries for additional databases — each entry gets its own credentials block in `.env`.

### 4. Add table names

Create `config/dbs/main_db/tables.json`:

```json
{ "stock_movement": "tstock_movement", "user_stock": "tuser_stock" }
```

For MongoDB, create `config/dbs/<name>/collections.json`:

```json
{ "logs": "app_logs", "events": "user_events" }
```

### 5. Choose an LLM provider

```bash
# Ollama (local, default)
ollama pull llama3.1
pip install -r requirements-ollama.txt

# Groq (cloud, fast — recommended for testing)
pip install -r requirements-groq.txt
# In .env: LLM_PROVIDER=groq  LLM_MODEL=llama-3.1-8b-instant  LLM_API_KEY=...

# OpenAI
pip install -r requirements-openai.txt
# In .env: LLM_PROVIDER=openai  LLM_MODEL=gpt-4o-mini  LLM_API_KEY=sk-...

# Anthropic
pip install -r requirements-anthropic.txt
# In .env: LLM_PROVIDER=anthropic  LLM_MODEL=claude-sonnet-4-6  LLM_API_KEY=sk-ant-...
```

### 6. Run

```bash
python app.py
# Open http://localhost:5000 — log in with admin / admin123
```

Schema sync runs automatically at startup — `table_columns.json` and `relationships.json` are written/updated for each configured database.

---

## Adding a New Database

1. **Add an entry** to `config/databases.json`:

```json
{
  "name": "hr_db",
  "type": "postgresql",
  "env_prefix": "HR_DB",
  "description": "HR — employees, payroll, attendance, departments"
}
```

2. **Add table names** to `config/dbs/hr_db/tables.json`:

```json
{ "employees": "emp", "attendance": "att", "departments": "dept" }
```

3. **Add credentials** to `.env`:

```env
HR_DB_HOST=localhost
HR_DB_PORT=5432
HR_DB_USER=postgres
HR_DB_PASSWORD=secret
HR_DB_NAME=hr
```

4. **Restart** (or click **Sync Schema**) — columns and FK relationships are discovered automatically.

No code changes required.

---

## Adding a MongoDB Database

1. **Add an entry** to `config/databases.json`:

```json
{
  "name": "logs_db",
  "type": "mongodb",
  "env_prefix": "MONGO",
  "description": "App logs, user activity events, error reports"
}
```

2. **Add collection names** to `config/dbs/logs_db/collections.json`:

```json
{ "logs": "app_logs", "events": "user_events", "errors": "error_reports" }
```

3. **Add credentials** to `.env`:

```env
MONGO_URI=mongodb://localhost:27017    # full URI (use for Atlas / replica sets)
MONGO_NAME=app_logs
```

4. **Restart** — field names are sampled from documents automatically.

The agent will now write aggregation pipelines to query this database.

---

## Adding a Manual JOIN Relationship

Append to `config/dbs/<db_name>/relationships.json` — it survives every future auto-sync:

```json
{
  "relationships": [
    {
      "left_table":  "tstock_movement",
      "right_table": "tuser_stock",
      "left_key":    "imei",
      "right_key":   "imei1",
      "join_type":   "LEFT"
    }
  ]
}
```

Supported `join_type` values: `INNER`, `LEFT`, `RIGHT`.

---

## API Reference

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/chat` | session | Send a chat message (NDJSON stream) |
| `GET`  | `/api/pdfs` | session | List loaded PDF filenames |
| `POST` | `/api/reload-pdfs` | admin | Re-scan `pdfs/` and rebuild ChromaDB index |
| `POST` | `/api/sync-schema` | admin | Re-discover columns + FK relationships for all databases |

### `/api/chat` NDJSON events

```jsonc
{"status": "Running Query Main Db…"}       // tool running indicator
{"token": "Here are the top results…"}     // streamed text token
{"done": true, "confidence": 87}           // text response complete
{"done": true, "data": {…}, "confidence": 92}  // structured response
```

Structured `data` types: `chart`, `attendance_table`, `attendance`, `error`.

---

## Environment Variables

Each database entry in `databases.json` uses its own `env_prefix`. The variable name is `<PREFIX>_<FIELD>`.

### SQL databases (MySQL / PostgreSQL)

| Variable | Default | Description |
|---|---|---|
| `<P>_HOST` | `localhost` | Database host |
| `<P>_PORT` | `3306` / `5432` | Port |
| `<P>_USER` | `root` | Username |
| `<P>_PASSWORD` | _(empty)_ | Password |
| `<P>_NAME` | _(empty)_ | Database name |
| `<P>_SCHEMA` | _(none)_ | PostgreSQL schema (sets `search_path`) |

### MongoDB

| Variable | Description |
|---|---|
| `<P>_URI` | Full MongoDB URI (wins if set — use for Atlas) |
| `<P>_HOST` | Host (used if URI not set) |
| `<P>_PORT` | Port (default `27017`) |
| `<P>_USER` | Username (leave blank if no auth) |
| `<P>_PASSWORD` | Password |
| `<P>_NAME` | Database name |

### Application

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` \| `openai` \| `anthropic` \| `groq` |
| `LLM_MODEL` | `llama3.1` | Provider-specific model name |
| `LLM_API_KEY` | _(empty)_ | Required for cloud providers |
| `LLM_BASE_URL` | _(empty)_ | Ollama URL or custom OpenAI-compatible endpoint |
| `PDF_DIR` | `./pdfs` | Directory scanned for PDFs |
| `CHROMA_DIR` | `./chroma_db` | ChromaDB persistence directory |
| `CURRENCY_SYMBOL` | `$` | Symbol used before monetary values |
| `SECRET_KEY` | _(insecure)_ | Flask session secret — **change in production** |

---

## Confidence Scoring

`_ConfidenceTracker` starts each turn at **85%** and adjusts based on evidence:

| Event | Δ Score |
|---|---|
| Query returns rows | +5 |
| Query returns empty | −20 |
| Query error | −35 |
| PDF chunks found (avg relevance r) | +(r−0.5)×12 |
| PDF not found | −15 |
| Tool fails | −10 |

Score is clamped to **[10, 98]**. UI colours: green ≥ 80%, amber 55–79%, red < 55%.

---

## Production Checklist

- Set `debug=False` or run with `gunicorn app:app -w 4`
- Use a strong random `SECRET_KEY`
- Create a dedicated DB user with `SELECT` only (plus `INSERT/UPDATE` on the attendance table if used)
- Place behind nginx/Caddy with HTTPS
- Back up `chroma_db/` — delete to force a full PDF re-index
- Tune `pool_size` and `pool_recycle` in `config/database.json` for high-traffic deployments

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 3 |
| Agent framework | LangGraph (`create_react_agent`) |
| LLM integrations | ChatOllama, ChatOpenAI, ChatAnthropic, ChatGroq |
| SQL abstraction | SQLAlchemy 2 + custom adapter pattern |
| MySQL driver | mysql-connector-python |
| PostgreSQL driver | psycopg2-binary |
| MongoDB driver | pymongo |
| Vector store | ChromaDB (local persistent) |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` |
| PDF parsing | PyPDF2 |
| Frontend | Vanilla JS + CSS, Chart.js 4.4 |
| Auth | Flask sessions + SHA-256 password hashing |
