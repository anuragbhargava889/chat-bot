# Company ChatBot

A Python web chatbot powered by a **LangGraph ReAct agent** that answers natural-language questions by querying one or more databases (MySQL, PostgreSQL, MongoDB), a ChromaDB vector store, and a PDF knowledge library.

All database connections, collection/table mappings, column hints, and JOIN relationships are **fully config-driven** — no code changes needed to add or remove a database.

---

## Features

| Feature | Description |
|---|---|
| **Multi-DB agent routing** | LLM picks the right database automatically based on tool descriptions — one tool per DB |
| **MySQL · PostgreSQL · MongoDB** | SQL DBs use SELECT queries; MongoDB uses aggregation pipelines |
| **Config-driven** | Table/collection names, column hints, and relationships live in per-DB JSON files |
| **Auto schema sync** | Columns discovered from INFORMATION_SCHEMA (SQL) or document sampling (MongoDB); written at startup |
| **Manual field descriptions** | `column_descriptions.json` per DB lets you annotate any field with a human-readable description shown to the LLM |
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
├── app.py                      # Flask server — auth, routes, NDJSON streaming
├── chatbot.py                  # LangGraph ReAct agent, auto-generated per-DB tools, confidence tracker
├── database.py                 # Auth only — users.json + MongoDB employees fallback
├── pdf_handler.py              # PDF loading, chunking, ChromaDB vector search
├── config.py                   # Env + JSON config loader; LLM factory; schema sync
│
├── config/                     # ← Configuration files (edit without touching code)
│   ├── databases.json          #   Master DB list — name, type, env_prefix, description
│   ├── database.json           #   SQL connection pool settings
│   ├── users.json              #   Local user accounts (always checked first on login)
│   └── dbs/                    #   Per-database config (one folder per entry in databases.json)
│       └── <db_name>/
│           ├── tables.json             #  MANUAL   — logical → actual table names  (SQL)
│           ├── collections.json        #  MANUAL   — logical → actual collection names  (MongoDB)
│           ├── table_columns.json      #  AUTO     — column hints (overwritten on sync)
│           ├── collection_columns.json #  AUTO     — field hints  (overwritten on sync)
│           ├── column_descriptions.json #  MANUAL  — human-readable field descriptions overlaid on auto-synced columns
│           └── relationships.json      #  HYBRID   — FK-auto + manual JOIN entries  (SQL only)
│
├── db/                         # ← Database adapter layer
│   ├── adapter.py              #   Abstract base
│   ├── mysql_adapter.py        #   MySQL  (mysql+mysqlconnector)
│   ├── postgresql_adapter.py   #   PostgreSQL (psycopg2)
│   ├── factory.py              #   get_adapter(), build_adapter_for(), build_mongo_client()
│   ├── schema_inspector.py     #   Column + FK discovery for SQL and MongoDB
│   └── query_builder.py        #   Programmatic query builder
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
chatbot.py  (LangGraph ReAct agent — create_react_agent)
  │
  │  system prompt built from databases.json + per-DB column hints + descriptions:
  │    [main_db]  MongoDB — collections + field hints + tool: query_main_db
  │    [sales_db] MySQL   — tables + JOIN hints + tool: query_sales_db / schema_sales_db
  │
  ├─ tool: query_<name>       → aggregation pipeline (MongoDB) | SELECT query (SQL)
  ├─ tool: schema_<name>      → column info (SQL only)
  ├─ tool: search_pdf_library → ChromaDB semantic search
  └─ tool: generate_chart     → Chart.js JSON payload
  │
  │  _ConfidenceTracker tallies outcomes throughout
  ▼
NDJSON:  {"status":"…"} | {"token":"…"} | {"done":true,"confidence":87}
  ▼
chat.js renders tokens live; "● Response Accuracy: 87%" footer appended
```

### How the agent decides which database to query

The LLM reads each tool's name and description:

```
query_main_db   — "Main stock database — stock movement and user stock"  → stock questions
query_sales_db  — "Sales — orders, products, revenue"                   → sales questions
```

For cross-database questions it calls multiple tools in sequence. No routing code required.

### Config file ownership

| File | Who writes it | Notes |
|---|---|---|
| `databases.json` | Manual | Add/remove databases here |
| `dbs/<name>/tables.json` | Manual | SQL table mapping |
| `dbs/<name>/collections.json` | Manual | MongoDB collection mapping |
| `dbs/<name>/column_descriptions.json` | Manual | Field descriptions shown to the LLM — survives sync |
| `dbs/<name>/table_columns.json` | **Auto sync** | Overwritten on every sync — do not hand-edit |
| `dbs/<name>/collection_columns.json` | **Auto sync** | Overwritten on every sync — do not hand-edit |
| `dbs/<name>/relationships.json` | **Hybrid** | Manual JOIN entries always preserved across sync |

### Schema auto-sync

At startup and via the **Sync Schema** admin button, the app:

1. **SQL** — queries `INFORMATION_SCHEMA.COLUMNS` → writes `table_columns.json`; discovers FK constraints → hybrid-merges into `relationships.json`
2. **MongoDB** — samples 20 documents per collection → infers field names → writes `collection_columns.json`
3. Manual `column_descriptions.json` entries are overlaid on the auto-synced columns before the system prompt is built — they are never overwritten

---

## Prerequisites

| Tool | Notes |
|---|---|
| Python 3.10+ | |
| MongoDB 4.2+ **or** MySQL 8+ **or** PostgreSQL 14+ | At least one required |
| Ollama | Required only for `LLM_PROVIDER=ollama` |

---

## Quick Start

### 1. Clone and install

```bash
git clone <repo-url>
cd chat-bot
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

> `sentence-transformers` downloads `all-MiniLM-L6-v2` (~80 MB) on first run.

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` for a MongoDB setup:

```env
MONGO_URI=mongodb://user:password@localhost:27017/?authSource=admin
MONGO_NAME=your_database

LLM_PROVIDER=anthropic
LLM_MODEL=claude-haiku-4-5-20251001
LLM_API_KEY=sk-ant-...

SECRET_KEY=replace-with-a-long-random-string
CURRENCY_SYMBOL=₹
```

### 3. Declare your database in `config/databases.json`

```json
{
  "databases": [
    {
      "name": "main_db",
      "type": "mongodb",
      "env_prefix": "MONGO",
      "description": "Main stock database — stock movement and user stock"
    }
  ]
}
```

### 4. Add collection names

Create `config/dbs/main_db/collections.json`:

```json
{
  "stock_movement": "tstock_movement",
  "user_stock":     "tuser_stock"
}
```

### 5. (Optional) Add field descriptions

Create `config/dbs/main_db/column_descriptions.json` to give the LLM context about ambiguous fields:

```json
{
  "stock_movement": {
    "moved_date":  "date stock was moved — string YYYY-MM-DD",
    "movement_type": "IN = stock received, OUT = stock dispatched"
  }
}
```

### 6. Add login accounts

Edit `config/users.json`:

```json
[
  { "username": "admin",    "password": "admin123",    "name": "Admin",    "role": "admin" },
  { "username": "john.doe", "password": "password123", "name": "John Doe", "role": "employee" }
]
```

### 7. Run

```bash
python app.py
# Open http://localhost:5000
```

Schema sync runs automatically at startup.

---

## Choosing an LLM Provider

```bash
# Anthropic (recommended — best tool-calling accuracy)
# In .env: LLM_PROVIDER=anthropic  LLM_MODEL=claude-haiku-4-5-20251001  LLM_API_KEY=sk-ant-...

# Groq (free tier, fast — good fallback)
# In .env: LLM_PROVIDER=groq  LLM_MODEL=llama-3.1-8b-instant  LLM_API_KEY=gsk_...

# OpenAI
# In .env: LLM_PROVIDER=openai  LLM_MODEL=gpt-4o-mini  LLM_API_KEY=sk-...

# Ollama (local)
ollama pull llama3.1
# In .env: LLM_PROVIDER=ollama  LLM_MODEL=llama3.1  LLM_BASE_URL=http://localhost:11434
```

> **Groq free tier TPD limits:** `llama-3.1-8b-instant` = 500K/day, `llama-3.3-70b-versatile` = 100K/day.

---

## Adding a SQL Database

1. Add entry to `config/databases.json`:

```json
{
  "name": "sales_db",
  "type": "mysql",
  "env_prefix": "SALES_DB",
  "description": "Sales — orders, products, customers, revenue"
}
```

2. Add table names to `config/dbs/sales_db/tables.json`:

```json
{ "orders": "orders", "products": "products", "customers": "customers" }
```

3. Add credentials to `.env`:

```env
SALES_DB_HOST=localhost
SALES_DB_PORT=3306
SALES_DB_USER=root
SALES_DB_PASSWORD=secret
SALES_DB_NAME=sales
```

4. Restart or click **Sync Schema** — columns and FK relationships are auto-discovered.

---

## Adding a Manual JOIN Relationship

Append to `config/dbs/<db_name>/relationships.json` — preserved across every auto-sync:

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
| `POST` | `/api/chat` | session | Send a chat message — returns NDJSON stream |
| `GET`  | `/api/pdfs` | session | List loaded PDF filenames |
| `POST` | `/api/reload-pdfs` | admin | Re-scan `pdfs/` and rebuild ChromaDB index |
| `POST` | `/api/sync-schema` | admin | Re-discover columns + relationships for all databases |

### `/api/chat` NDJSON event stream

```jsonc
{"status": "Running Query Main Db…"}           // tool-running indicator
{"token": "Here are the top results…"}         // streamed text token
{"done": true, "confidence": 87}               // text response complete
{"done": true, "data": {…}, "confidence": 92}  // structured response
```

Structured `data.type` values: `chart`, `attendance_table`, `attendance`, `error`.

---

## Environment Variables

### MongoDB

| Variable | Description |
|---|---|
| `<PREFIX>_URI` | Full MongoDB URI — wins if set (supports Atlas, replica sets, auth) |
| `<PREFIX>_NAME` | Database name |
| `<PREFIX>_HOST` | Host (used only if URI not set; default `localhost`) |
| `<PREFIX>_PORT` | Port (default `27017`) |
| `<PREFIX>_USER` | Username |
| `<PREFIX>_PASSWORD` | Password |

### SQL (MySQL / PostgreSQL)

| Variable | Default | Description |
|---|---|---|
| `<PREFIX>_HOST` | `localhost` | Database host |
| `<PREFIX>_PORT` | `3306` / `5432` | Port |
| `<PREFIX>_USER` | `root` | Username |
| `<PREFIX>_PASSWORD` | _(empty)_ | Password |
| `<PREFIX>_NAME` | _(empty)_ | Database name |
| `<PREFIX>_SCHEMA` | _(none)_ | PostgreSQL schema / `search_path` |

### Application

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama` \| `openai` \| `anthropic` \| `groq` |
| `LLM_MODEL` | `llama3.1` | Provider-specific model name |
| `LLM_API_KEY` | _(empty)_ | Required for cloud providers |
| `LLM_BASE_URL` | _(empty)_ | Ollama URL or custom OpenAI-compatible endpoint |
| `PDF_DIR` | `./pdfs` | Directory scanned for PDFs |
| `CHROMA_DIR` | `./chroma_db` | ChromaDB persistence directory |
| `CURRENCY_SYMBOL` | `$` | Symbol prepended to all monetary values |
| `SECRET_KEY` | _(insecure default)_ | Flask session secret — **change in production** |

---

## Confidence Scoring

`_ConfidenceTracker` starts each turn at **85%** and adjusts:

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
- Set a strong random `SECRET_KEY`
- Create a dedicated DB user with read-only access
- Place behind nginx/Caddy with HTTPS
- Back up `chroma_db/` — deleting it forces a full PDF re-index on next startup

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
