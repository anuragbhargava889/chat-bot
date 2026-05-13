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
import re
from datetime import datetime

from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool, tool
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, field_validator

from config import get_db_uri, get_llm
from database import (
    get_attendance_report as db_get_attendance,
    mark_attendance as db_mark_attendance,
)
from pdf_handler import query_pdfs


# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM = """You are a company assistant with access to a MySQL database and PDF library.

Tables: products(name,category,price), sales(product_id,quantity,amount,sale_date),
tstock_movement(from_role,to_role,status,movement_type,item_price,sales_price,imei,material_code,dbr_code,moved_date),
tuser_stock(model_no,model_name,item_main_category,series,imei1,imei2,each_line_item_price,invoice_no,dbr_name,status,quantity,stock_date),
attendance(employee_id,date,check_in,check_out,status), employees(username,name,email,department,role).

Rules:
1. Use sql_query for all data questions. SELECT only — never INSERT/UPDATE/DELETE/DROP.
2. For rankings: ORDER BY … LIMIT N. For dates: MONTH(), YEAR(), DATE_SUB(), CURDATE().
3. For PDF questions use search_pdf_library and cite the source.
4. For check-in/out use mark_attendance. For attendance history use get_attendance_report.
5. For charts: call sql_query first, then generate_chart with the results.
6. Be concise."""


# ── Fallback suggestions shown when the model fails to parse a query ──────────

_SUGGESTIONS = [
    "Show top 5 selling products",
    "What is the average monthly sales?",
    "Show a bar chart of sales by category",
    "Show my attendance history",
    "What stock items are available?",
    "Show monthly sales trend as a line chart",
]


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
            sample_rows_in_table_info=0,  # 0 = columns only, no sample rows → saves ~1000 tokens/call
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


# Llama 3 special tokens that occasionally bleed into streamed output
_SPECIAL_TOKENS = re.compile(r"<\|[a-zA-Z0-9_]+\|>")

def _clean(text: str) -> str:
    return _SPECIAL_TOKENS.sub("", text)


def _friendly_error(exc: Exception) -> str:
    """Return a user-facing message for common API errors."""
    s = str(exc)
    if "rate_limit_exceeded" in s or "429" in s:
        # Extract wait time if present, e.g. "Please try again in 17m11s"
        import re as _re
        wait = _re.search(r"try again in ([\w.]+)", s)
        wait_msg = f" Please try again in {wait.group(1)}." if wait else " Please try again shortly."
        return f"Rate limit reached for the AI model.{wait_msg}"
    if "failed_generation" in s or "Failed to call a function" in s:
        return (
            "The model failed to generate a valid tool call for this query. "
            "Try rephrasing your question or ask for simpler data."
        )
    if "insufficient_quota" in s or "credit" in s.lower():
        return "API credits exhausted. Please top up your account or switch providers in .env."
    if "timeout" in s.lower() or "timed out" in s.lower():
        return "The request timed out. The model may be overloaded — please try again."
    return f"Error: {exc}"


# ── Type coercions ─────────────────────────────────────────────────────────────
# Different LLMs send tool args as different types (Llama sends strings for
# booleans and integers). Use str type hints everywhere and coerce at call time.

def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1", "yes")

def _to_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return default

def _parse_list(v, cast=str) -> list:
    if isinstance(v, (list, tuple)):
        return [cast(x) for x in v]
    try:
        return [cast(x) for x in json.loads(v)]
    except (json.JSONDecodeError, TypeError, ValueError):
        parts = [x.strip().strip("\"'") for x in str(v).strip("[]").split(",")]
        return [cast(x) for x in parts if x]


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
    def search_pdf_library(question: str, top_k: str = "3") -> str:
        """Semantic search over company PDF documents.

        Use for questions about policies, procedures, warranties, product specifications,
        HR rules, or any knowledge stored in uploaded documents.

        Args:
            question: Natural-language question to search for.
            top_k: Number of document chunks to retrieve (default '3').
        """
        chunks = query_pdfs(question, top_k=_to_int(top_k, default=3))
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
    def get_attendance_report(all_employees: str = "false") -> str:
        """Retrieve attendance records for structured display.

        Employees see their own history. Admins can view all employees.
        Use this (not sql_query) for attendance history requests.

        Args:
            all_employees: Pass 'true' to get all employees' records (admin only),
                           or 'false' (default) for the current user's records only.
        """
        want_all = _to_bool(all_employees)
        if not user:
            return json.dumps({"success": False, "message": "Login required to view attendance."})
        if want_all and user.get("role") != "admin":
            return json.dumps({"success": False, "message": "Admin access required to view all attendance."})
        records = db_get_attendance(employee_id=None if want_all else user["employee_id"])
        return json.dumps({"success": True, "records": records})

    # ── generate_chart — custom schema so both arrays and JSON strings are accepted ──

    class _ChartInput(BaseModel):
        chart_type:    str
        title:         str
        labels:        str   # LLM sends JSON array string; validator also accepts native list
        dataset_label: str
        data:          str   # LLM sends JSON array string; validator also accepts native list

        @field_validator("labels", "data", mode="before")
        @classmethod
        def _coerce_to_json_str(cls, v):
            """Accept native list OR JSON string — normalise to JSON string."""
            if isinstance(v, (list, tuple)):
                return json.dumps(v)
            return v

    def _generate_chart(
        chart_type: str,
        title: str,
        labels: str,
        dataset_label: str,
        data: str,
    ) -> str:
        try:
            label_list = _parse_list(labels, str)
            data_list  = _parse_list(data, float)
        except (ValueError, TypeError) as exc:
            return f"Error parsing chart data: {exc}"

        return json.dumps({
            "type": "chart",
            "chart_type": chart_type,
            "title": title,
            "labels": label_list,
            "dataset_label": dataset_label,
            "data": data_list,
        })

    generate_chart = StructuredTool.from_function(
        func=_generate_chart,
        name="generate_chart",
        args_schema=_ChartInput,
        description=(
            "Render a visual chart from query results. "
            "Call this AFTER sql_query when the user asks for a chart, graph, or visualization.\n\n"
            "chart_type choices:\n"
            "  'bar'      — compare values across categories (products, roles, departments)\n"
            "  'line'     — trends over time (monthly sales, daily counts)\n"
            "  'pie'      — proportions of a whole (category revenue share)\n"
            "  'doughnut' — same as pie, visually lighter\n\n"
            "labels: JSON array of category/time label strings, e.g. '[\"Jan\",\"Feb\",\"Mar\"]'\n"
            "data:   JSON array of matching numeric values,    e.g. '[1200.5, 980.0, 1450.0]'"
        ),
    )

    return [sql_query, sql_schema, search_pdf_library, mark_attendance,
            get_attendance_report, generate_chart]


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
        chart_data: dict | None = None

        # Per-step token buffer — Llama 3 leaks tool-call syntax as text content
        # BEFORE setting tool_call_chunks. Buffer each agent step; only flush the
        # buffer when the step completes with no tool calls (i.e. it's a real reply).
        token_buffer: list[str] = []
        current_step: int = -1
        step_is_tool_call: bool = False

        for chunk, metadata in agent.stream(
            {"messages": [
                SystemMessage(content=f"{_SYSTEM}\n\n{user_ctx}"),
                HumanMessage(content=message),
            ]},
            stream_mode="messages",
        ):
            node = metadata.get("langgraph_node", "")
            step = metadata.get("langgraph_step", 0)

            if node == "agent" and isinstance(chunk, AIMessageChunk):
                # New agent round detected — evaluate the previous round
                if step != current_step:
                    if current_step >= 0 and not step_is_tool_call:
                        for tok in token_buffer:
                            yield json.dumps({"token": tok}) + "\n"
                    token_buffer = []
                    step_is_tool_call = False
                    current_step = step

                if chunk.tool_call_chunks:
                    step_is_tool_call = True
                    for tc in chunk.tool_call_chunks:
                        name = tc.get("name", "")
                        if name and name not in tool_status_shown:
                            tool_status_shown.add(name)
                            label = name.replace("_", " ").title()
                            yield json.dumps({"status": f"Running {label}…"}) + "\n"
                elif chunk.content:
                    text = _clean(_extract_text(chunk.content))
                    if text:
                        token_buffer.append(text)

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
                elif chunk.name == "generate_chart":
                    try:
                        chart_data = json.loads(chunk.content)
                    except Exception:
                        pass

        # Flush the last agent step's buffer if it was a plain text response
        if not step_is_tool_call and token_buffer:
            for tok in token_buffer:
                yield json.dumps({"token": tok}) + "\n"

        # Emit final structured response (priority: chart > attendance > text)
        if chart_data:
            yield json.dumps({"done": True, "data": chart_data}) + "\n"
        elif attendance_action:
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
        msg = _friendly_error(exc)
        s = str(exc)
        is_failed = "failed_generation" in s or "Failed to call a function" in s
        payload: dict = {"type": "error", "message": msg}
        if is_failed:
            payload["suggestions"] = _SUGGESTIONS
        yield json.dumps({"done": True, "data": payload}) + "\n"


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
