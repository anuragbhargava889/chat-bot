# Company ChatBot

A Python web chatbot powered by **LangGraph ReAct agent** that intelligently routes queries across multiple data sources — MySQL or PostgreSQL databases, a ChromaDB vector store, and a PDF knowledge library — through a single natural-language interface.

Multi-database support is fully **configuration-driven**: switch between MySQL and PostgreSQL by changing one environment variable, with no code changes required.

---

## Features

| Feature | Description |
|---|---|
| **Dynamic SQL** | LLM writes arbitrary SELECT queries including JOINs, aggregations, rankings, and date filters |
| **Multi-Database** | MySQL and PostgreSQL supported; swap with `DB_TYPE` in `.env` |
| **Config-Driven Tables** | Table names, relationships, and JOIN hints live in JSON config files — not hardcoded |
| **Auto JOIN Detection** | LLM is briefed on pre-configured relationships; generates INNER / LEFT / RIGHT JOINs automatically |
| **PDF Q&A** | Semantic search over uploaded PDFs via ChromaDB + sentence-transformers |
| **Attendance** | Employee check-in/check-out write; structured attendance history read |
| **Chart Generation** | LLM fetches data then calls `generate_chart` to render Chart.js bar / line / pie / doughnut |
| **Response Accuracy** | Every bot message shows a confidence % based on query success, data completeness, and tool outcomes |
| **Multi-LLM** | Supports Ollama, OpenAI, Anthropic, and Groq via a single `.env` setting |

---

## Architecture

### File structure

```
chat-bot/
├── app.py                    # Flask server — auth, routes, SSE streaming
├── chatbot.py                # LangGraph ReAct agent, tools, confidence tracker
├── database.py               # Adapter-agnostic DB operations (attendance, auth)
├── pdf_handler.py            # PDF loading, chunking, ChromaDB vector search
├── config.py                 # Env + JSON config loader; LLM factory
│
├── config/                   # ← Configuration files (edit without touching code)
│   ├── database.json         #   Connection pool settings
│   ├── tables.json           #   Logical → actual table name mappings
│   └── relationships.json    #   JOIN relationship definitions
│
├── db/                       # ← Database adapter layer
│   ├── adapter.py            #   Abstract base (execute / execute_write / sanitize)
│   ├── mysql_adapter.py      #   MySQL  (mysql+mysqlconnector)
│   ├── postgresql_adapter.py #   PostgreSQL (postgresql+psycopg2)
│   └── factory.py            #   Singleton factory — reads DB_TYPE from .env
│
├── schema.sql                # MySQL schema + seed data
├── requirements.txt
├── .env.example
├── pdfs/                     # Drop PDF files here
├── chroma_db/                # ChromaDB vector store (auto-created, gitignored)
├── templates/
│   ├── base.html
│   ├── login.html
│   └── index.html            # Main chat UI
└── static/
    ├── css/style.css
    └── js/chat.js
```

### Request flow

```
Browser
  │  POST /api/chat  (NDJSON stream)
  ▼
app.py  ──────────────────────────────────────────────────────
  │  stream_message(message, user)
  ▼
chatbot.py  (LangGraph ReAct agent)
  │
  │  builds system prompt dynamically from:
  │    config/tables.json        ← actual table names
  │    config/relationships.json ← JOIN hints for LLM
  │    DB dialect                ← MySQL vs PostgreSQL date functions
  │
  ├─ tool: sql_query      → LangChain SQLDatabase → MySQL / PostgreSQL
  ├─ tool: sql_schema     → table column info
  ├─ tool: search_pdf_library → ChromaDB (pdfs/)
  ├─ tool: mark_attendance    → database.py → adapter → DB (write)
  ├─ tool: get_attendance_report → database.py → adapter → DB (read)
  └─ tool: generate_chart → Chart.js JSON payload
  │
  │  _ConfidenceTracker tallies tool outcomes throughout
  ▼
NDJSON events:  {"status":"…"} | {"token":"…"} | {"done":true,"confidence":87}
  ▼
chat.js renders tokens live, then appends "● Response Accuracy: 87%" footer
```

### Database adapter layer

```
db/factory.py  reads DB_TYPE from .env
  │
  ├─ DB_TYPE=mysql        → MySQLAdapter       (mysql+mysqlconnector URI)
  └─ DB_TYPE=postgresql   → PostgreSQLAdapter  (postgresql+psycopg2 URI)
       ↓ both extend DatabaseAdapter
         .execute(query, params)       → list[dict]  (sanitised)
         .execute_write(query, params) → None
         .dialect_name                 → 'mysql' | 'postgresql'
         .date_functions               → dialect date hints injected into LLM prompt
```

All queries use `SQLAlchemy text()` with `:named` parameters — compatible with every supported dialect. Table names are injected from `config/tables.json` (trusted source), never from user input.

### Confidence scoring

`_ConfidenceTracker` starts each turn at **85 %** and adjusts based on evidence:

| Event | Δ Score |
|---|---|
| SQL returns rows | +5 |
| SQL returns empty result | −20 |
| SQL error | −35 |
| PDF chunks found (avg relevance r) | +(r−0.5)×12 |
| PDF not found | −15 |
| Attendance / write tool fails | −10 |

Score is clamped to **[10, 98]**. Colour coding in the UI: green ≥ 80 %, amber 55–79 %, red < 55 %.

---

## Prerequisites

| Tool | Minimum version | Notes |
|---|---|---|
| Python | 3.10 | |
| MySQL **or** PostgreSQL | 8.0 / 14 | Only one needed |
| Ollama | latest | Required for `LLM_PROVIDER=ollama` |

---

## Quick Start

### 1. Clone & enter directory

```bash
git clone <repo-url>
cd chat-bot
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate       # Linux / macOS
# venv\Scripts\activate        # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> `sentence-transformers` downloads `all-MiniLM-L6-v2` (~80 MB) on first run.  
> `psycopg2-binary` is included for PostgreSQL; it is unused if you stay on MySQL.

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` — minimum required fields:

**MySQL:**
```env
DB_TYPE=mysql
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=chatbot_db
DB_PORT=3306
SECRET_KEY=replace-with-a-long-random-string
```

**PostgreSQL:**
```env
DB_TYPE=postgresql
DB_HOST=localhost
DB_USER=postgres
DB_PASSWORD=your_password
DB_NAME=chatbot_db
DB_PORT=5432
DB_SCHEMA=public          # optional
SECRET_KEY=replace-with-a-long-random-string
```

### 5. Set up the database

**MySQL:**
```bash
mysql -u root -p < schema.sql
```

**PostgreSQL:**  
The `schema.sql` file uses MySQL syntax. For PostgreSQL, create the database manually and adapt the DDL (replace `AUTO_INCREMENT` with `SERIAL`, `ENUM` with `VARCHAR`, etc.) or use a migration tool such as pgloader.

### 6. Choose an LLM provider

**Ollama (default — runs locally):**
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1
pip install -r requirements-ollama.txt
```

**Groq (cloud, fast, recommended for testing):**
```bash
pip install -r requirements-groq.txt
# In .env:
LLM_PROVIDER=groq
LLM_MODEL=llama-3.1-8b-instant
LLM_API_KEY=your_groq_key
```

**OpenAI:**
```bash
pip install -r requirements-openai.txt
# In .env:
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
```

**Anthropic:**
```bash
pip install -r requirements-anthropic.txt
# In .env:
LLM_PROVIDER=anthropic
LLM_MODEL=claude-sonnet-4-6
LLM_API_KEY=sk-ant-...
```

### 7. Add PDF files (optional)

```bash
cp ~/my-documents/*.pdf pdfs/
```

PDFs are indexed automatically on startup. Use the **Reload PDFs** button in the UI (admin only) after adding new files.

### 8. Run the application

```bash
python app.py
```

Open **http://localhost:5000** — log in with `admin / admin123` or `john.doe / password123`.

---

## Configuration Files

### `config/tables.json` — table name mappings

Maps logical names used in code to actual database table names. Rename or alias tables here without touching any Python.

```json
{
  "employees":      "employees",
  "products":       "products",
  "sales":          "sales",
  "attendance":     "attendance",
  "stock_movement": "tstock_movement",
  "user_stock":     "tuser_stock"
}
```

The chatbot's system prompt and `SQLDatabase.include_tables` are both built from this file at startup.

### `config/relationships.json` — JOIN definitions

Tells the LLM which tables are related and how to join them. The agent uses these as starting-point hints when a query spans multiple tables.

```json
{
  "relationships": [
    {
      "left_table":  "sales",
      "right_table": "products",
      "left_key":    "product_id",
      "right_key":   "product_id",
      "join_type":   "INNER"
    },
    {
      "left_table":  "attendance",
      "right_table": "employees",
      "left_key":    "employee_id",
      "right_key":   "employee_id",
      "join_type":   "INNER"
    }
  ]
}
```

Supported `join_type` values: `INNER`, `LEFT`, `RIGHT`.

#### Auto-generation (hybrid)

`relationships.json` is **automatically updated on every startup** via `config.sync_relationships()`, which is called from `app.py`. It uses a hybrid strategy:

| Source | How it works |
|---|---|
| **FK-discovered** | Queries `INFORMATION_SCHEMA` (MySQL) or `information_schema` (PostgreSQL) for declared foreign key constraints. Each FK becomes an `INNER` JOIN entry. |
| **Manual / logical** | Any entry already in `relationships.json` that has no matching FK constraint is kept unchanged. Use this for joins on shared columns that lack a formal FK (e.g. `tstock_movement.imei → tuser_stock.imei1`). |
| **Conflict resolution** | If a FK-discovered relationship already exists in the file, the **file version wins** — preserving any custom `join_type` you have set. |

If the database is unreachable at startup, auto-sync is skipped with a warning log and the existing file is used unchanged.

**To add a logical relationship** (no FK in the schema), just append it to `relationships.json` manually — it will survive future auto-syncs:

```json
{
  "left_table":  "tstock_movement",
  "right_table": "tuser_stock",
  "left_key":    "imei",
  "right_key":   "imei1",
  "join_type":   "LEFT"
}
```

### `config/database.json` — connection pool settings

```json
{
  "pool_size":    5,
  "max_overflow": 10,
  "pool_recycle": 1800,
  "pool_timeout": 30
}
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DB_TYPE` | `mysql` | Database engine: `mysql` \| `postgresql` |
| `DB_HOST` | `localhost` | Database host |
| `DB_USER` | `root` | Database username |
| `DB_PASSWORD` | _(empty)_ | Database password |
| `DB_NAME` | `chatbot_db` | Database / catalog name |
| `DB_PORT` | `3306` | Port (`5432` for PostgreSQL) |
| `DB_SCHEMA` | _(none)_ | PostgreSQL schema (sets `search_path`) |
| `LLM_PROVIDER` | `ollama` | `ollama` \| `openai` \| `anthropic` \| `groq` |
| `LLM_MODEL` | `llama3.1` | Provider-specific model name |
| `LLM_API_KEY` | _(empty)_ | Required for cloud providers |
| `LLM_BASE_URL` | _(empty)_ | Ollama URL or custom OpenAI-compatible endpoint |
| `PDF_DIR` | `./pdfs` | Directory scanned for PDF files |
| `CHROMA_DIR` | `./chroma_db` | ChromaDB persistence directory |
| `SECRET_KEY` | _(insecure)_ | Flask session secret — **change in production** |

---

## Seed Accounts

| Username | Password | Role | Department |
|---|---|---|---|
| `admin` | `admin123` | admin | Management |
| `john.doe` | `password123` | employee | Sales |
| `jane.smith` | `password123` | employee | HR |
| `bob.johnson` | `password123` | employee | Sales |
| `alice.brown` | `password123` | employee | Marketing |
| `charlie.davis` | `password123` | employee | Engineering |
| `diana.wilson` | `password123` | employee | Finance |

---

## Usage Examples

**Dynamic SQL with JOINs**
```
You:  Show top 5 products by revenue this month
Bot:  [table] — LLM writes: SELECT p.name, SUM(s.amount) … JOIN … GROUP BY … ORDER BY … LIMIT 5

You:  Show a bar chart of sales by category
Bot:  [Chart.js bar chart rendered inline]
```

**PDF Q&A**
```
You:  What is the return policy?
Bot:  According to policy.pdf: Returns accepted within 30 days…
      Response Accuracy: 91%
```

**Attendance**
```
You:  Check in
Bot:  Check-in marked at 09:02:14.   ● Response Accuracy: 88%

You:  Show all attendance    (admin only)
Bot:  [table: Name | Dept | Date | Check-in | Check-out | Status]
```

---

## API Reference

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/chat` | session | Send a chat message (NDJSON stream) |
| `GET`  | `/api/pdfs` | session | List loaded PDF filenames |
| `POST` | `/api/reload-pdfs` | admin | Re-scan `pdfs/` and rebuild ChromaDB index |
| `POST` | `/login` | — | Authenticate |
| `GET`  | `/logout` | — | Clear session |

### `/api/chat` NDJSON event types

```jsonc
{"status": "Running Sql Query…"}          // tool running indicator
{"token": "Here are the top…"}            // streamed text token
{"done": true, "confidence": 87}          // text response complete
{"done": true, "data": {…}, "confidence": 92}  // structured response
```

Structured `data` types: `chart`, `attendance_table`, `attendance`, `error`.

---

## QueryBuilder

`db/query_builder.py` provides a chainable, dialect-aware programmatic query builder for use in application code (not for the LLM — the agent writes raw SQL). It produces `SQLAlchemy text()`-compatible parameterized queries that work on both MySQL and PostgreSQL.

### Chaining API

| Method | Purpose |
|---|---|
| `.select(*cols)` | Add columns or expressions |
| `.count/sum/avg/min/max(col, alias=)` | Add aggregate functions |
| `.join(table, on=, join_type=)` | Generic JOIN |
| `.inner_join(table, on=)` | INNER JOIN shorthand |
| `.left_join(table, on=)` | LEFT JOIN shorthand |
| `.right_join(table, on=)` | RIGHT JOIN shorthand |
| `.where(condition, **params)` | Add WHERE condition (AND-chained) |
| `.group_by(*cols)` | GROUP BY columns |
| `.having(condition, **params)` | HAVING condition (AND-chained) |
| `.order_by(col, desc=False)` | ORDER BY — pass `desc=True` or include `DESC` in the string |
| `.limit(n)` | LIMIT |
| `.offset(n)` | OFFSET |
| `.paginate(page, page_size)` | Sets LIMIT + OFFSET for a 1-based page number |
| `.build()` | Returns `(sql_string, params_dict)` |
| `.execute()` | Builds and runs via the active adapter; returns `list[dict]` |

### Dialect-aware date helpers (static methods)

| Method | MySQL output | PostgreSQL output |
|---|---|---|
| `QueryBuilder.month_of('col')` | `MONTH(col)` | `EXTRACT(MONTH FROM col)` |
| `QueryBuilder.year_of('col')` | `YEAR(col)` | `EXTRACT(YEAR FROM col)` |
| `QueryBuilder.current_date()` | `CURDATE()` | `CURRENT_DATE` |
| `QueryBuilder.current_timestamp()` | `NOW()` | `NOW()` |
| `QueryBuilder.date_sub_days(7)` | `DATE_SUB(CURDATE(), INTERVAL 7 DAY)` | `(CURRENT_DATE - INTERVAL '7 days')` |
| `QueryBuilder.date_trunc_month('col')` | `DATE_FORMAT(col, '%Y-%m-01')` | `DATE_TRUNC('month', col)` |

### Examples

**Simple SELECT with filter, sort, limit**
```python
from db.query_builder import QueryBuilder

sql, params = (
    QueryBuilder("products")
    .select("name", "category", "price")
    .where("category = :cat", cat="Electronics")
    .order_by("price", desc=True)
    .limit(10)
    .build()
)
```

**JOIN + aggregation + HAVING**
```python
results = (
    QueryBuilder("sales s")
    .select("p.name")
    .sum("s.amount", alias="revenue")
    .count("*",      alias="transactions")
    .inner_join("products p", on="s.product_id = p.product_id")
    .where(f"{QueryBuilder.month_of('s.sale_date')} = :m", m=5)
    .group_by("p.product_id", "p.name")
    .having("SUM(s.amount) > :min", min=500)
    .order_by("revenue", desc=True)
    .limit(5)
    .execute()
)
```

**Pagination**
```python
page_2 = (
    QueryBuilder("employees")
    .select("name", "department", "role")
    .order_by("name")
    .paginate(page=2, page_size=20)
    .execute()
)
```

**LEFT JOIN with multiple WHERE conditions**
```python
sql, params = (
    QueryBuilder("tstock_movement sm")
    .select("sm.imei", "sm.status", "us.model_name")
    .left_join("tuser_stock us", on="sm.imei = us.imei1")
    .where("sm.status = :status", status="sold")
    .where("sm.movement_type = :mtype", mtype="outbound")
    .order_by("sm.moved_date", desc=True)
    .limit(20)
    .build()
)
```

---

## Adding a New Database Engine

1. **Create an adapter** in `db/`:

```python
# db/mssql_adapter.py
from urllib.parse import quote_plus
from .adapter import DatabaseAdapter

class MSSQLAdapter(DatabaseAdapter):
    def __init__(self, host, port, user, password, database, **_):
        ...

    def get_uri(self) -> str:
        return f"mssql+pymssql://{quote_plus(self.user)}:{quote_plus(self.password)}@{self.host}:{self.port}/{self.database}"

    @property
    def dialect_name(self) -> str:
        return "mssql"

    @property
    def date_functions(self) -> dict:
        return {
            "current_date":      "CAST(GETDATE() AS DATE)",
            "current_timestamp": "GETDATE()",
            "month_extract":     "MONTH({col})",
            "year_extract":      "YEAR({col})",
            "date_sub_days":     "DATEADD(day, -{n}, CAST(GETDATE() AS DATE))",
            "date_trunc_month":  "DATEFROMPARTS(YEAR({col}), MONTH({col}), 1)",
        }
```

2. **Register it** in `db/factory.py`:

```python
elif db_type == "mssql":
    port = int(os.getenv("DB_PORT", 1433))
    from .mssql_adapter import MSSQLAdapter
    _adapter = MSSQLAdapter(host=host, port=port, user=user, password=password, database=database)
```

3. **Install the driver**: add `pymssql` to `requirements.txt`.

4. **Set `.env`**: `DB_TYPE=mssql` — no other code changes needed.

---

## Adding Tables or Renaming Existing Ones

1. Edit `config/tables.json` — add or rename any entry:

```json
{
  "invoices": "tbl_invoices_2024"
}
```

2. Optionally add JOIN relationships to `config/relationships.json`.

3. Restart the application — the LLM system prompt and `SQLDatabase` table list both update automatically.

---

## User Roles

| Role | Capabilities |
|---|---|
| `employee` | Chat, any SQL query, PDF Q&A, own check-in/check-out, own attendance history |
| `admin` | All employee capabilities + view all employees' attendance + reload PDF library |

---

## Production Checklist

- Set `debug=False` in `app.py` or run with `gunicorn app:app -w 4`
- Use a strong random `SECRET_KEY`
- Create a dedicated DB user with `SELECT` only (plus `INSERT/UPDATE` on the attendance table)
- Place the app behind nginx / Caddy with HTTPS
- Back up or persist `chroma_db/` — delete it to force a full PDF re-index
- For PostgreSQL: tune `pool_size` and `pool_recycle` in `config/database.json` to match your server's `max_connections`
- Set `LOG_LEVEL=WARNING` via `logging.basicConfig` in production to reduce log volume

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 3 |
| Agent framework | LangGraph (`create_react_agent`) |
| LLM integrations | ChatOllama, ChatOpenAI, ChatAnthropic, ChatGroq |
| DB abstraction | SQLAlchemy 2 + custom adapter pattern |
| MySQL driver | mysql-connector-python |
| PostgreSQL driver | psycopg2-binary |
| Vector store | ChromaDB (local persistent) |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` |
| PDF parsing | PyPDF2 |
| Frontend | Vanilla JS + CSS, Chart.js 4.4 |
| Auth | Flask sessions + SHA-256 password hashing |
