# Company ChatBot

A Python web chatbot that integrates **MySQL product-sales queries**, a **PDF knowledge library**, and **employee attendance tracking** — all through a single chat interface.

---

## Features

| Feature | Description |
|---|---|
| **Product Sales** | Ask about monthly sales for any product; data is pulled live from MySQL |
| **PDF Q&A** | Ask any question; the bot searches all PDFs in the `pdfs/` directory using TF-IDF similarity |
| **Attendance – Employee** | Type *"Check in"* or *"Check out"* to record daily attendance |
| **Attendance – Admin** | Admins type *"Show all attendance"* to view the full report |

---

## Architecture

```
chat-bot/
├── app.py               # Flask web server & API routes
├── chatbot.py           # Intent detection & response routing
├── database.py          # MySQL connection pool + all queries
├── pdf_handler.py       # PDF loading, chunking, TF-IDF search
├── config.py            # Env-based configuration
├── schema.sql           # DB schema + sample seed data
├── requirements.txt
├── .env.example
├── pdfs/                # Drop PDF files here
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
┌─────────────┐
│ chatbot.py  │  Detects intent from message text
└──────┬──────┘
       │
  ┌────┴────────────────────┐
  │                         │
  ▼                         ▼
┌────────────┐     ┌───────────────┐
│database.py │     │pdf_handler.py │
│ MySQL pool │     │ TF-IDF search │
└────────────┘     └───────────────┘
       │
       ▼
   MySQL DB
  ┌──────────┐ ┌──────────┐ ┌────────────┐
  │ products │ │  sales   │ │ employees  │
  │          │ │          │ │ attendance │
  └──────────┘ └──────────┘ └────────────┘
```

### Intent Routing

```
User message
    │
    ├─ "hello / hi / hey"         → greet response
    ├─ "help"                     → help menu
    ├─ "check in / checkin"       → mark_attendance(checkin)
    ├─ "check out / checkout"     → mark_attendance(checkout)
    ├─ "show attendance / report" → get_attendance_report()
    ├─ "sales / sold / revenue"   → get_product_sales() from MySQL
    └─ (anything else)            → answer_from_pdfs() TF-IDF search
```

### Database Schema

```sql
employees   (employee_id, username, password, name, email, department, role)
products    (product_id, name, category, price, description)
sales       (sale_id, product_id, quantity, amount, sale_date, customer_name)
attendance  (attendance_id, employee_id, date, check_in, check_out, status)
```

### PDF Q&A Pipeline

1. On startup `pdf_handler.load_pdfs()` reads every `.pdf` in `pdfs/`
2. Each PDF is split into ~600-character overlapping chunks
3. On a question, TF-IDF vectors (bigrams, English stop-words removed) are computed for all chunks + the question
4. The chunk with highest cosine similarity is returned with its source filename
5. Falls back to keyword intersection scoring when `scikit-learn` is unavailable

---

## Prerequisites

| Tool | Minimum version |
|---|---|
| Python | 3.11 |
| MySQL | 8.0 |
| pip | 23 |

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

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set your MySQL credentials:

```
DB_HOST=localhost
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=chatbot_db
SECRET_KEY=replace-with-a-long-random-string
```

### 5. Set up the database

```bash
mysql -u root -p < schema.sql
```

This creates the `chatbot_db` database, all tables, and sample data including:
- **Admin account** – `admin / admin123`
- **Employee accounts** – `john.doe / password123`, `jane.smith / password123`
- Sample products and current-month sales

### 6. Add PDF files (optional)

Copy any `.pdf` files into the `pdfs/` directory:

```bash
cp ~/my-documents/*.pdf pdfs/
```

### 7. Run the application

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
```

```
You:  What are the sales for Monitor 4K?
Bot:  [table with this month's figures]
```

### PDF Questions

```
You:  What is the return policy?
Bot:  Source: company-policy.pdf
      Customers may return products within 30 days of purchase...
```

### Attendance

```
You:  Check in
Bot:  Check-in marked at 09:02:14.

You:  Check out
Bot:  Check-out marked at 17:45:33.
```

### Admin – View Attendance

```
You:  Show all attendance
Bot:  [table: Name | Dept | Date | Check-in | Check-out | Status]
```

---

## API Reference

| Method | Endpoint | Auth | Description |
|---|---|---|---|
| `POST` | `/api/chat` | session | Send a chat message |
| `GET`  | `/api/pdfs` | session | List loaded PDF files |
| `POST` | `/api/reload-pdfs` | admin | Re-scan `pdfs/` directory |
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
  "month": "April 2026",
  "product": "laptop pro",
  "data": [{ "name": "Laptop Pro", "total_quantity": 8, "total_amount": "7999.92", "total_transactions": 2 }]
}
```

**Attendance table**
```json
{
  "type": "attendance_table",
  "data": [{ "name": "John Doe", "department": "Sales", "date": "2026-04-28", "check_in": "09:01:00", "check_out": "17:30:00", "status": "present" }]
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
| `PDF_DIR` | `./pdfs` | Path to PDF directory |
| `SECRET_KEY` | _(insecure default)_ | Flask session secret – **change in production** |

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
- For large PDF libraries consider replacing TF-IDF with a vector database (pgvector, Chroma)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Web framework | Flask 3 |
| Database | MySQL 8 + mysql-connector-python |
| PDF parsing | PyPDF2 |
| Semantic search | scikit-learn TF-IDF + cosine similarity |
| Frontend | Vanilla JS + CSS (no framework) |
| Auth | Flask sessions + SHA-256 password hashing |
