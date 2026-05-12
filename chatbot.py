"""
Chatbot core — LangGraph ReAct agent + LangChain SQLDatabase.

Two entry points:
  process_message() → dict          (kept for compatibility)
  stream_message()  → NDJSON events (used by the SSE endpoint)

Tools:
  sql_query             → Dynamic SELECT on all tables (LangChain SQLDatabase)
  sql_schema            → Table schema / column introspection
  search_pdf_library    → ChromaDB vector store (PDFs)
  mark_attendance       → Attendance write — controlled, structured response
  get_attendance_report → Attendance read  — structured response
"""
from __future__ import annotations

import json
from datetime import datetime

from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import create_react_agent

from config import get_db_uri, get_llm
from database import (
    get_attendance_report as db_get_attendance,
    mark_attendance as db_mark_attendance,
)
from pdf_handler import query_pdfs


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """You are a professional company assistant connected to business databases and a PDF document library.

Available database tables (call sql_schema to inspect columns before complex queries):
• products          — product catalog: name, category, price
• sales             — product sales: product_id, quantity, amount, sale_date, customer_name
• tstock_movement   — stock transfers between supply-chain roles
    movement_type: 1=C&F→Distributor, 2=DB→Retailer, 3=Retailer→Customer(Sale),
                   6=Distributor→DB, 7=Distributor→DSE
    status 'Sold' = sold to end customer; 'acknowledged'/'Acknowledged' = internal transfer
    key columns: from_role, to_role, from_username, to_username, moved_date,
                 item_price, sales_price, imei, material_code, dbr_code, series
• tuser_stock       — stock inventory / invoice records
    key columns: model_no, model_name, material_description, item_main_category (Mobile/Accessories),
                 series, imei1, imei2, each_line_item_price, invoice_no, dbr_code, dbr_name,
                 status, quantity, stock_date, goods_receipt_date
• attendance        — employee attendance: employee_id, date, check_in, check_out, status
• employees         — employee directory: username, name, department, role

Behaviour rules:
1. Use sql_query for ALL data questions — always fetch real data, never guess.
2. ONLY use SELECT (or WITH) queries. Never INSERT, UPDATE, DELETE, or DROP.
3. Use sql_schema to inspect unfamiliar tables before writing complex queries.
4. For rankings: ORDER BY … LIMIT N.  For date ranges: MONTH(), YEAR(), DATE_SUB(), CURDATE().
5. Use column aliases in results for clarity.
6. For PDF questions, use search_pdf_library and cite the source document.
7. For check-in / check-out requests, use mark_attendance.
8. For attendance history, use get_attendance_report.
9. Be concise and professional."""


# ── SQL Database singleton ─────────────────────────────────────────────────────

_sql_db: SQLDatabase | None = None


def _get_db() -> SQLDatabase:
    global _sql_db
    if _sql_db is None:
        _sql_db = SQLDatabase.from_uri(
            get_db_uri(),
            include_tables=[
                "products", "sales", "attendance", "employees",
                "tstock_movement", "tuser_stock",
            ],
            sample_rows_in_table_info=2,
        )
    return _sql_db


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content) if content else ""


# ── Tool factory ───────────────────────────────────────────────────────────────

def _make_tools(user: dict | None, db: SQLDatabase) -> list:
    """Return all agent tools with user context captured in closures."""

    @tool
    def sql_query(query: str) -> str:
        """Execute a SQL SELECT query on the business database.

        Use for any data question: product sales, rankings, stock movements, inventory,
        attendance history, employee data — anything that needs real numbers from the DB.

        Call sql_schema first when unsure about table structure.
        Use ORDER BY … LIMIT for top-N / bottom-N queries.
        Use GROUP BY + aggregate functions for summaries and averages.

        Args:
            query: A valid SQL SELECT or WITH statement.
        """
        stripped = query.strip()
        if not (stripped.upper().startswith("SELECT") or stripped.upper().startswith("WITH")):
            return "Error: Only SELECT and WITH queries are permitted."
        try:
            return db.run(stripped)
        except Exception as exc:
            return f"Query error: {exc}"

    @tool
    def sql_schema(table_names: str = "") -> str:
        """Get column definitions and sample rows for one or more database tables.

        Always call this before writing queries on unfamiliar tables.

        Args:
            table_names: Comma-separated table names, e.g. 'tstock_movement,tuser_stock'.
                         Leave empty to get schema for all available tables.
        """
        if table_names.strip():
            tables = [t.strip() for t in table_names.split(",")]
            return db.get_table_info(tables)
        return db.get_table_info()

    @tool
    def search_pdf_library(question: str, top_k: int = 3) -> str:
        """Semantic search over company PDF documents.

        Use for questions about policies, procedures, warranties, product specifications,
        HR rules, or any knowledge stored in uploaded documents.

        Args:
            question: Natural-language question to search for.
            top_k: Number of document chunks to retrieve (default 3).
        """
        chunks = query_pdfs(question, top_k=top_k)
        if not chunks:
            return json.dumps({"found": False, "message": "No relevant content found in the PDF library."})
        return json.dumps({
            "found": True,
            "chunks": [
                {"source": c["source"], "text": c["text"], "relevance": c["score"]}
                for c in chunks
            ],
        })

    @tool
    def mark_attendance(action: str) -> str:
        """Record the current employee's check-in or check-out.

        Use when the user says they are checking in, arriving, checking out, or leaving.
        Do NOT use sql_query for this — use this tool exclusively.

        Args:
            action: 'checkin' when arriving; 'checkout' when leaving.
        """
        if action not in ("checkin", "checkout"):
            return json.dumps({"success": False, "message": "action must be 'checkin' or 'checkout'."})
        if not user:
            return json.dumps({"success": False, "message": "You must be logged in to mark attendance."})
        result = db_mark_attendance(user["employee_id"], action)
        return json.dumps({"success": result["status"] == "success", "message": result["message"]})

    @tool
    def get_attendance_report(all_employees: bool = False) -> str:
        """Retrieve attendance records for structured display.

        Employees see their own history. Admins can view all employees.
        Use this (not sql_query) for attendance history requests.

        Args:
            all_employees: True to get all employees' records (admin only).
                           False (default) for the current user's records only.
        """
        if not user:
            return json.dumps({"success": False, "message": "Login required to view attendance."})
        if all_employees and user.get("role") != "admin":
            return json.dumps({"success": False, "message": "Admin access required to view all attendance."})
        records = db_get_attendance(employee_id=None if all_employees else user["employee_id"])
        return json.dumps({"success": True, "records": records})

    return [sql_query, sql_schema, search_pdf_library, mark_attendance, get_attendance_report]


# ── Streaming entry point (SSE) ────────────────────────────────────────────────

def stream_message(message: str, user: dict | None = None):
    """
    Generator yielding newline-delimited JSON events for SSE.

    Event shapes:
        {"status": "..."}              — typing indicator while tools run
        {"token": "..."}               — text token streamed to live bubble
        {"done": true}                 — text streaming complete (no structured data)
        {"done": true, "data": {...}}  — structured response (table / attendance / error)
    """
    user_ctx = (
        f"Current user: {user['name']} | role: {user['role']} | "
        f"department: {user.get('department', 'N/A')}."
        if user else "User is not authenticated."
    )

    try:
        db = _get_db()
        tools = _make_tools(user, db)
        agent = create_react_agent(get_llm(), tools)

        tool_status_shown: set[str] = set()
        attendance_action: dict | None = None
        attendance_table: list | None = None

        for chunk, metadata in agent.stream(
            {"messages": [
                SystemMessage(content=f"{_SYSTEM}\n\n{user_ctx}"),
                HumanMessage(content=message),
            ]},
            stream_mode="messages",
        ):
            node = metadata.get("langgraph_node", "")

            if node == "agent" and isinstance(chunk, AIMessageChunk):
                if chunk.tool_call_chunks:
                    for tc in chunk.tool_call_chunks:
                        name = tc.get("name", "")
                        if name and name not in tool_status_shown:
                            tool_status_shown.add(name)
                            label = name.replace("_", " ").title()
                            yield json.dumps({"status": f"Running {label}…"}) + "\n"
                elif chunk.content:
                    text = _extract_text(chunk.content)
                    if text:
                        yield json.dumps({"token": text}) + "\n"

            elif node == "tools" and isinstance(chunk, ToolMessage):
                if chunk.name == "mark_attendance":
                    try:
                        attendance_action = json.loads(chunk.content)
                    except Exception:
                        pass
                elif chunk.name == "get_attendance_report":
                    try:
                        res = json.loads(chunk.content)
                        if res.get("success"):
                            attendance_table = res["records"]
                    except Exception:
                        pass

        # Emit final structured response if attendance tools were called
        if attendance_action:
            yield json.dumps({
                "done": True,
                "data": {
                    "type": "attendance",
                    "status": "success" if attendance_action.get("success") else "error",
                    "message": attendance_action.get("message", ""),
                },
            }) + "\n"
        elif attendance_table is not None:
            yield json.dumps({
                "done": True,
                "data": {"type": "attendance_table", "data": attendance_table},
            }) + "\n"
        else:
            yield json.dumps({"done": True}) + "\n"

    except Exception as exc:
        import traceback
        traceback.print_exc()
        yield json.dumps({
            "done": True,
            "data": {"type": "error", "message": f"Error: {exc}"},
        }) + "\n"


# ── Synchronous entry point (kept for compatibility) ───────────────────────────

def process_message(message: str, user: dict | None = None) -> dict:
    """Synchronous wrapper — collects stream_message() into a single dict."""
    last: dict = {"type": "error", "message": "No response."}
    for line in stream_message(message, user):
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue
        if evt.get("done"):
            last = evt.get("data") or {"type": "text", "message": "Done."}
        elif evt.get("token"):
            if last.get("type") != "text":
                last = {"type": "text", "message": ""}
            last["message"] = last.get("message", "") + evt["token"]
    return last
