# Company ChatBot

A Python web chatbot powered by **open-source LLMs via Ollama** that intelligently routes queries across multiple data sources — MySQL databases, a ChromaDB vector store, and a PDF knowledge library — through a single natural-language chat interface.

---

## Features

| Feature | Description |
|---|---|
| **Product Sales** | Ask about monthly sales for any product; the LLM queries MySQL and returns a formatted table |
| **PDF Q&A** | Ask any question; the LLM searches all PDFs via semantic vector similarity (ChromaDB + sentence-transformers) |
| **Attendance – Employee** | Type *"Check in"* or *"Check out"* to record daily attendance |
| **Attendance – Admin** | Admins can ask to see all employees' attendance history |
| **Smart Routing** | The LLM autonomously decides which database(s) to query based on the message; no keyword rules needed |
| **Open Source** | Runs entirely locally — Ollama for the LLM, ChromaDB for vector search, MySQL for structured data |

---

## Architecture

```
chat-bot/
├── app.py               # Flask web server & API routes
├── chatbot.py           # LangChain tool-calling agent (multi-DB routing)
├── database.py          # MySQL connection pool + all queries
├── pdf_handler.py       # PDF loading, chunking, ChromaDB vector search
├── config.py            # Env-based configuration
├── schema.sql           # DB schema + comprehensive seed data
├── requirements.txt
├── .env.example
├── pdfs/                # Drop PDF files here
├── chroma_db/           # ChromaDB vector store (auto-created, gitignored)
├── templates/
│   ├── base.html
│   ├── login.html
│   └── index.html       # Main chat UI
└── static/
    ├── css/style.css
    └── js/chat.js
```

### Component Diagram

```
Browser (chat UI)
      │  HTTP POST /api/chat
      ▼
┌─────────────┐
│   app.py    │  Flask – auth, routing, session
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────┐
│                  chatbot.py                     │
│                                                 │
│  LangChain AgentExecutor                        │
│  + ChatOllama (llama3.1 via Ollama)             │
│                                                 │
│  LLM reads the user message and calls one or   │
│  more tools to fetch data, then composes a     │
│  natural-language response.                    │
└────┬──────────────┬──────────────┬──────────────┘
     │              │              │
     ▼              ▼              ▼
┌──────────┐  ┌──────────┐  ┌─────────────────┐
│database  │  │database  │  │  pdf_handler.py  │
│.py       │  │.py       │  │                  │
│(sales /  │  │(attend-  │  │  ChromaDB +      │
│products) │  │ance)     │  │  sentence-trans- │
└────┬─────┘  └────┬─────┘  │  formers embed-  │
     │              │        │  dings           │
     ▼              ▼        └────────┬─────────┘
  MySQL DB                            │
┌──────────┐ ┌──────────┐             ▼
│ products │ │  sales   │       chroma_db/
│ employees│ │attendance│   (persisted vectors)
└──────────┘ └──────────┘
```

### Multi-Database Routing via LangChain Tool Use

The LLM is given five tools, one per data source. It reads the user's intent and selects the right tool(s) automatically — no keyword rules, no regex, no hardcoded routing.

```
User message
    │
    ▼
ChatOllama (llama3.1)
    │
    ├─ sales / revenue / earnings?     → tool: query_product_sales  → MySQL sales
    ├─ which products exist?           → tool: list_products         → MySQL products
    ├─ company policy / manual / spec? → tool: search_pdf_library    → ChromaDB (PDFs)
    ├─ check in / arriving?            → tool: mark_attendance       → MySQL attendance (write)
    └─ show attendance / history?      → tool: get_attendance_report → MySQL attendance (read)

The LLM may call multiple tools in a single response when a question
spans several data sources (e.g. "compare Laptop Pro sales with our
return policy").
```

### PDF Semantic Search Pipeline

1. On startup, `pdf_handler.load_pdfs()` reads every `.pdf` in `pdfs/`
2. Each PDF is split into ~600-character sentence-aware chunks
3. Chunks are embedded using `all-MiniLM-L6-v2` (sentence-transformers, ~80 MB, downloads once)
4. Embeddings are stored in a local **ChromaDB** persistent collection
5. On a query, the question is embedded and the top-K most similar chunks are retrieved via cosine similarity
6. The LLM receives the chunks and cites the source filename in its response

ChromaDB persists embeddings to `chroma_db/` — after the first run, restarts are instant.

### Database Schema

```sql
employees   (employee_id, username, password, name, email, department, role)
products    (product_id, name, category, price, description)
sales       (sale_id, product_id, quantity, amount, sale_date, customer_name)
attendance  (attendance_id, employee_id, date, check_in, check_out, status)
```

---

## Prerequisites

| Tool | Minimum version | Notes |
|---|---|---|
| Python | 3.11 | |
| MySQL | 8.0 | |
| pip | 23 | |
| Ollama | latest | Install from https://ollama.com |

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
# Linux / macOS
source venv/bin/activate
# Windows
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `sentence-transformers` will download the `all-MiniLM-L6-v2` model (~80 MB) on first run.

### 4. Install Ollama and pull a model

```bash
# Install Ollama — https://ollama.com/download
# Linux one-liner:
curl -fsSL https://ollama.com/install.sh | sh

# Pull the default model (requires ~4 GB disk space)
ollama pull llama3.1

# Optional: use a smaller/faster model
# ollama pull qwen2.5:7b
```

> **Model requirements:** The model must support native tool calling. Confirmed working: `llama3.1`, `qwen2.5`, `mistral-nemo`. Set `LLM_MODEL` in `.env` to switch models.

### 5. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```env
# MySQL
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=chatbot_db

# Ollama
OLLAMA_HOST=http://localhost:11434
LLM_MODEL=llama3.1

# Flask
SECRET_KEY=replace-with-a-long-random-string
```

### 6. Set up the database

```bash
mysql -u root -p < schema.sql
```

This creates the `chatbot_db` database, all tables, and comprehensive seed data including:
- **7 employees** — 1 admin + 6 employees across Sales, HR, Marketing, Engineering, Finance
- **12 products** — Electronics and Furniture categories
- **~46 sales records** — spread across current month, previous month, and two months ago
- **~59 attendance records** — 14 days of history for all 6 non-admin employees

Seed accounts:

| Username | Password | Role | Department |
|---|---|---|---|
| `admin` | `admin123` | admin | Management |
| `john.doe` | `password123` | employee | Sales |
| `jane.smith` | `password123` | employee | HR |
| `bob.johnson` | `password123` | employee | Sales |
| `alice.brown` | `password123` | employee | Marketing |
| `charlie.davis` | `password123` | employee | Engineering |
| `diana.wilson` | `password123` | employee | Finance |

### 7. Add PDF files (optional)

Copy any `.pdf` files into the `pdfs/` directory:

```bash
cp ~/my-documents/*.pdf pdfs/
```

PDFs are indexed automatically on startup. Use the **Reload PDFs** button in the UI (admin only) to re-index after adding new files.

### 8. Start Ollama (if not already running)

```bash
ollama serve
```

> Ollama runs as a background service automatically on most installs. Check with `ollama list`.

### 9. Run the application

```bash
python app.py
```

Open your browser at **http://localhost:5000**

---

## Usage Examples

### Product Sales

```
You:  Show sales for Laptop Pro
Bot:  [table: Product | Units Sold | Revenue | Transactions]

You:  What are last month's earnings for Monitor 4K?
Bot:  [table with previous month figures]
```

### PDF Questions

```
You:  What is the return policy?
Bot:  According to company-policy.pdf: Customers may return products
      within 30 days of purchase...
```

### Attendance

```
You:  Check in
Bot:  Check-in recorded at 09:02:14.

You:  Check out
Bot:  Check-out recorded at 17:45:33.
```

### Admin – View All Attendance

```
You:  Show all attendance
Bot:  [table: Name | Dept | Date | Check-in | Check-out | Status]
```

### Multi-source query

```
You:  What does the warranty policy say, and how many warranties
      were sold last month?
Bot:  [calls search_pdf_library AND query_product_sales, then
       combines both answers in a single response]
```

---

## API Reference

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/chat` | session | Send a chat message |
| `GET`  | `/api/pdfs` | session | List loaded PDF files |
| `POST` | `/api/reload-pdfs` | admin | Re-scan `pdfs/` and rebuild ChromaDB index |
| `POST` | `/login` | — | Authenticate |
| `GET`  | `/logout` | — | Clear session |

### `/api/chat` – Request

```json
{ "message": "Show sales for Laptop Pro" }
```

### `/api/chat` – Response types

**Text**
```json
{ "type": "text", "message": "..." }
```

**Sales table**
```json
{
  "type": "sales_table",
  "month": "May 2026",
  "product": "laptop pro",
  "data": [{ "name": "Laptop Pro", "total_quantity": 10, "total_amount": 9999.90, "total_transactions": 3 }]
}
```

**Attendance table**
```json
{
  "type": "attendance_table",
  "data": [{ "name": "John Doe", "department": "Sales", "date": "2026-05-03", "check_in": "09:01:00", "check_out": "17:30:00", "status": "present" }]
}
```

**Attendance action**
```json
{ "type": "attendance", "status": "success", "message": "Check-in marked at 09:01:00." }
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DB_HOST` | `localhost` | MySQL host |
| `DB_USER` | `root` | MySQL username |
| `DB_PASSWORD` | _(empty)_ | MySQL password |
| `DB_NAME` | `chatbot_db` | Database name |
| `DB_PORT` | `3306` | MySQL port |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `LLM_MODEL` | `llama3.1` | Ollama model name (must support tool calling) |
| `PDF_DIR` | `./pdfs` | Path to PDF directory |
| `CHROMA_DIR` | `./chroma_db` | Path where ChromaDB persists embeddings |
| `SECRET_KEY` | _(insecure default)_ | Flask session secret — **change in production** |

---

## User Roles

| Role | Capabilities |
|---|---|
| `employee` | Chat, product sales queries, PDF Q&A, own check-in/check-out, own attendance history |
| `admin` | All employee capabilities + view **all** employees' attendance + reload PDF library |

---

## Production Notes

- Set `debug=False` in `app.py` (or use `gunicorn app:app`)
- Use a strong, random `SECRET_KEY`
- Run MySQL with a dedicated user and restricted privileges
- Place the app behind a reverse proxy (nginx) with HTTPS
- The `chroma_db/` directory is a generated artifact — back it up or rebuild from PDFs
- To force a full re-index of PDFs, delete `chroma_db/` and restart (or use the Reload PDFs API)
- Ollama runs on the same host by default; set `OLLAMA_HOST` to point to a remote Ollama instance

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 3 |
| LLM | Ollama (local) — default model: `llama3.1` |
| Agent framework | LangChain (`create_tool_calling_agent` + `AgentExecutor`) |
| LLM integration | `langchain-ollama` (`ChatOllama`) |
| Database | MySQL 8 + mysql-connector-python |
| Vector store | ChromaDB (local persistent) |
| Embeddings | sentence-transformers `all-MiniLM-L6-v2` |
| PDF parsing | PyPDF2 |
| Frontend | Vanilla JS + CSS (no framework) |
| Auth | Flask sessions + SHA-256 password hashing |
