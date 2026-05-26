"""Chatbot core — LangGraph ReAct agent + LangChain SQLDatabase.

Entry points:
  stream_message()  → NDJSON events (SSE endpoint)
  process_message() → dict (synchronous, kept for compatibility)

Tools:
  sql_query             — Dynamic SELECT on all configured tables
  sql_schema            — Table schema / column introspection
  search_pdf_library    — ChromaDB semantic search over PDFs
  mark_attendance       — Controlled attendance write
  get_attendance_report — Structured attendance read
  generate_chart        — Chart.js chart payload generator
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool, tool
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, field_validator

from config import get_db_uri, get_llm, get_table_config, get_column_hints, get_relationship_config, get_dialect_hints, DB_TYPE, CURRENCY_SYMBOL
from database import (
    get_attendance_report as db_get_attendance,
    mark_attendance as db_mark_attendance,
)
from pdf_handler import query_pdfs

logger = logging.getLogger(__name__)


# ── Confidence tracker ─────────────────────────────────────────────────────────

class _ConfidenceTracker:
    """Accumulates evidence during a single agent turn to produce a confidence %."""

    def __init__(self):
        self._score: float = 85.0

    def record_sql(self, result: str) -> None:
        r = result.strip()
        if r.startswith("Query error:") or r.startswith("Error:"):
            self._score -= 35
            logger.debug("Confidence: SQL error → %.0f", self._score)
        elif not r or r in ("[]", "None", ""):
            self._score -= 20
            logger.debug("Confidence: SQL empty → %.0f", self._score)
        else:
            self._score = min(98, self._score + 5)
            logger.debug("Confidence: SQL data → %.0f", self._score)

    def record_pdf(self, result_json: str) -> None:
        try:
            res = json.loads(result_json)
            if res.get("found") and res.get("chunks"):
                chunks = res["chunks"]
                avg_rel = sum(c.get("relevance", 0.5) for c in chunks) / len(chunks)
                bonus = (avg_rel - 0.5) * 12
                self._score = min(98, self._score + bonus)
                logger.debug("Confidence: PDF found (rel=%.2f) → %.0f", avg_rel, self._score)
            else:
                self._score -= 15
                logger.debug("Confidence: PDF not found → %.0f", self._score)
        except Exception:
            pass

    def record_tool_success(self, success: bool) -> None:
        if not success:
            self._score -= 10
            logger.debug("Confidence: tool fail → %.0f", self._score)

    def get(self) -> int:
        return round(max(10, min(98, self._score)))


# ── System prompt (built dynamically from config) ──────────────────────────────

def _build_system(user_ctx: str) -> str:
    tables   = get_table_config()     # {logical_key: actual_table_name}
    col_hints = get_column_hints()    # {logical_key: "col1, col2, ..."}  (optional)
    rels     = get_relationship_config().get("relationships", [])

    # Build table descriptions purely from config — no hardcoded names or columns
    tbl_parts = []
    for logical_key, actual_table in tables.items():
        cols = col_hints.get(logical_key)
        tbl_parts.append(f"{actual_table}({cols})" if cols else actual_table)
    tables_str = ", ".join(tbl_parts)

    # Relationship hints for JOIN queries
    rel_lines = [
        f"  - {r['left_table']} {r['join_type']} JOIN {r['right_table']}"
        f" ON {r['left_table']}.{r['left_key']} = {r['right_table']}.{r['right_key']}"
        for r in rels
    ]
    rel_str = "\n".join(rel_lines) if rel_lines else "  (use sql_schema to discover FK columns)"

    date_hint = get_dialect_hints()

    attendance_rule = (
        "\n5b. For check-in/out use mark_attendance. "
        "Use get_attendance_report only for unfiltered history. "
        "For filtered attendance queries use sql_query."
        if ("attendance" in tables and "employees" in tables) else ""
    )

    return f"""You are a company assistant with access to a {DB_TYPE.upper()} database and PDF library.

Tables: {tables_str}

Pre-configured JOIN relationships (use these as a guide — add others as needed):
{rel_str}

Rules:
1. Use sql_query for all data questions. SELECT / WITH only — never INSERT/UPDATE/DELETE/DROP.
   Always include a LIMIT clause in every SELECT query (e.g. LIMIT 50 for lists, LIMIT 200 for reports).
2. {date_hint}
3. Rankings: ORDER BY … LIMIT N. Summaries: GROUP BY + aggregate functions.
4. Multi-table data: write explicit JOIN queries using the relationships above.
5. For PDF questions use search_pdf_library and cite the source.{attendance_rule}
6. For charts: call sql_query first, then generate_chart with the results.
7. Always use {CURRENCY_SYMBOL} as the currency symbol for all monetary values. Never use $.
8. Column value discovery: when a query uses a WHERE filter on a text column whose values you
   don't know, FIRST run one discovery query:
     SELECT DISTINCT <column> FROM <table> LIMIT 30
   Use the returned values to build the real query. Do this at most ONCE per column.
9. Empty results: if a query returns no rows, respond immediately with a clear
   "No data found for [topic]" message. Do NOT retry with alternative column names,
   alternative spellings, or reformulated queries.
10. Be concise.

{user_ctx}"""


# ── Fallback suggestions ───────────────────────────────────────────────────────

_SUGGESTIONS = [
    "Show available tables and their structure",
    "Show total stock summary",
    "Show top 10 items by price as a bar chart",
    "Show stock movement trend as a line chart",
    "What stock items are available?",
    "Show stock distribution by category as a pie chart",
]


# ── SQLDatabase singleton ──────────────────────────────────────────────────────

_sql_db: SQLDatabase | None = None


def _get_db() -> SQLDatabase:
    global _sql_db
    if _sql_db is None:
        tables = get_table_config()
        _sql_db = SQLDatabase.from_uri(
            get_db_uri(),
            include_tables=list(tables.values()),
            sample_rows_in_table_info=0,
        )
        logger.info("SQLDatabase initialised with tables: %s", list(tables.values()))
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


_SPECIAL_TOKENS = re.compile(r"<\|[a-zA-Z0-9_]+\|>")

# Hard-cap on sql_query result size — backstop after LIMIT is already enforced.
_SQL_MAX_CHARS = 20_000


def _enforce_limit(query: str, default: int = 200) -> str:
    """Append a default LIMIT if the query has none, preventing unbounded fetches."""
    if "LIMIT" not in query.upper():
        return query.rstrip("; \n") + f" LIMIT {default}"
    return query

def _clean(text: str) -> str:
    return _SPECIAL_TOKENS.sub("", text)


def _friendly_error(exc: Exception) -> str:
    s = str(exc)
    if "GraphRecursionError" in type(exc).__name__ or "Recursion limit" in s:
        return (
            "No data found. The query could not be completed — "
            "the requested information may not exist in the database, "
            "or the column values did not match. "
            "Try a more specific question or check the table schema."
        )
    if "AnthropicContextOverflowError" in type(exc).__name__ or "prompt is too long" in s:
        return (
            "The query returned too much data for the AI to process. "
            "Try a more specific query — for example, add a date range filter or reduce the columns selected."
        )
    if "rate_limit_exceeded" in s or "429" in s:
        wait = re.search(r"try again in ([\w.]+)", s)
        wait_msg = f" Please try again in {wait.group(1)}." if wait else " Please try again shortly."
        return f"Rate limit reached for the AI model.{wait_msg}"
    if "failed_generation" in s or "Failed to call a function" in s:
        return (
            "The model failed to generate a valid tool call. "
            "Try rephrasing or ask for simpler data."
        )
    if "insufficient_quota" in s or "credit" in s.lower():
        return "API credits exhausted. Please top up your account or switch providers in .env."
    if "timeout" in s.lower() or "timed out" in s.lower():
        return "The request timed out — please try again."
    return f"Error: {exc}"


# ── Type coercions (Llama sends strings for bool/int/list params) ──────────────

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

    @tool
    def sql_query(query: str) -> str:
        """Execute a SQL SELECT query on the business database.

        Use for any data question: sales, rankings, stock, inventory, employees.
        Call sql_schema first when unsure about column names.
        Use ORDER BY … LIMIT for top-N queries; GROUP BY + aggregates for summaries.
        Write explicit JOIN queries using the relationships listed in the system prompt.

        IMPORTANT: if the result is empty, do NOT call this tool again with a different
        query — report "No data found" to the user immediately.

        Args:
            query: A valid SQL SELECT or WITH statement.
        """
        stripped = query.strip()
        upper = stripped.upper()
        if not (upper.startswith("SELECT") or upper.startswith("WITH")):
            return "Error: Only SELECT and WITH queries are permitted."
        bounded = _enforce_limit(stripped)
        if bounded != stripped:
            logger.info("sql_query: no LIMIT found — appended LIMIT 200")
        logger.info("sql_query: %s", bounded[:200])
        try:
            result = db.run(bounded)
            if len(result) > _SQL_MAX_CHARS:
                logger.warning("sql_query result still large (%d chars) — truncating", len(result))
                result = (
                    result[:_SQL_MAX_CHARS]
                    + f"\n\n[Result truncated at {_SQL_MAX_CHARS} chars. "
                    "Narrow the query (fewer columns, tighter date range) to see complete results.]"
                )
            return result
        except Exception as exc:
            logger.warning("sql_query failed: %s", exc)
            return f"Query error: {exc}"

    @tool
    def sql_schema(table_names: str = "") -> str:
        """Get column definitions for one or more database tables.

        Call this before writing queries on unfamiliar tables.

        Args:
            table_names: Comma-separated table names, e.g. 'sales,products'.
                         Leave empty to get schema for all available tables.
        """
        if table_names.strip():
            tables = [t.strip() for t in table_names.split(",")]
            return db.get_table_info(tables)
        return db.get_table_info()

    @tool
    def search_pdf_library(question: str, top_k: str = "3") -> str:
        """Semantic search over company PDF documents.

        Use for questions about policies, procedures, warranties, product specs,
        HR rules, or any knowledge stored in uploaded documents.

        Args:
            question: Natural-language question to search for.
            top_k:    Number of document chunks to retrieve (default '3').
        """
        chunks = query_pdfs(question, top_k=_to_int(top_k, default=3))
        if not chunks:
            return json.dumps({"found": False, "message": "No relevant content found."})
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

        Use when the user says they are checking in/arriving or checking out/leaving.
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
        """Retrieve full attendance history for structured table display.

        Use ONLY for plain unfiltered requests like "show my attendance" or
        "show all attendance". This tool returns all records with no date or
        status filtering.

        For ANY filtered query — absent today, late this week, present in a
        date range, by department, by name — use sql_query instead, which
        supports precise WHERE conditions.

        Args:
            all_employees: 'true' for all employees (admin only); 'false' for own records.
        """
        want_all = _to_bool(all_employees)
        if not user:
            return json.dumps({"success": False, "message": "Login required."})
        if want_all and user.get("role") != "admin":
            return json.dumps({"success": False, "message": "Admin access required."})
        records = db_get_attendance(employee_id=None if want_all else user["employee_id"])
        return json.dumps({"success": True, "records": records})

    # ── generate_chart ─────────────────────────────────────────────────────────

    class _ChartInput(BaseModel):
        chart_type:    str
        title:         str
        labels:        str
        dataset_label: str
        data:          str

        @field_validator("labels", "data", mode="before")
        @classmethod
        def _coerce_to_json_str(cls, v):
            if isinstance(v, (list, tuple)):
                return json.dumps(v)
            return v

    def _generate_chart(chart_type, title, labels, dataset_label, data) -> str:
        try:
            label_list = _parse_list(labels, str)
            data_list  = _parse_list(data, float)
        except (ValueError, TypeError) as exc:
            return f"Error parsing chart data: {exc}"
        return json.dumps({
            "type":          "chart",
            "chart_type":    chart_type,
            "title":         title,
            "labels":        label_list,
            "dataset_label": dataset_label,
            "data":          data_list,
        })

    generate_chart = StructuredTool.from_function(
        func=_generate_chart,
        name="generate_chart",
        args_schema=_ChartInput,
        description=(
            "Render a visual chart from query results. "
            "Call AFTER sql_query when the user asks for a chart/graph/visualization.\n\n"
            "chart_type: 'bar' | 'line' | 'pie' | 'doughnut'\n"
            "labels: JSON array of category/time strings, e.g. '[\"Jan\",\"Feb\"]'\n"
            "data:   JSON array of matching numbers,       e.g. '[1200.5, 980.0]'"
        ),
    )

    configured = get_table_config()
    tool_list  = [sql_query, sql_schema, search_pdf_library, generate_chart]
    if "attendance" in configured and "employees" in configured:
        tool_list += [mark_attendance, get_attendance_report]
    return tool_list


# ── Streaming entry point ──────────────────────────────────────────────────────

def stream_message(message: str, user: dict | None = None):
    """
    Generator yielding newline-delimited JSON events.

    Event shapes:
        {"status": "..."}                        — tool-running indicator
        {"token": "..."}                         — streaming text token
        {"done": true, "confidence": N}          — text complete
        {"done": true, "data": {...}, "confidence": N} — structured response
    """
    user_ctx = (
        f"Current user: {user['name']} | role: {user['role']} | "
        f"department: {user.get('department', 'N/A')}."
        if user else "User is not authenticated."
    )

    tracker = _ConfidenceTracker()

    try:
        db    = _get_db()
        tools = _make_tools(user, db)
        agent = create_react_agent(get_llm(), tools)

        tool_status_shown: set[str] = set()
        attendance_action: dict | None = None
        attendance_table:  list | None = None
        chart_data:        dict | None = None

        token_buffer:      list[str] = []
        current_step:      int  = -1
        step_is_tool_call: bool = False

        for chunk, metadata in agent.stream(
            {"messages": [
                SystemMessage(content=_build_system(user_ctx)),
                HumanMessage(content=message),
            ]},
            {"recursion_limit": 10},
            stream_mode="messages",
        ):
            node = metadata.get("langgraph_node", "")
            step = metadata.get("langgraph_step", 0)

            if node == "agent" and isinstance(chunk, AIMessageChunk):
                if step != current_step:
                    if current_step >= 0 and not step_is_tool_call:
                        for tok in token_buffer:
                            yield json.dumps({"token": tok}) + "\n"
                    token_buffer      = []
                    step_is_tool_call = False
                    current_step      = step

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
                # ── confidence tracking ────────────────────────────────────
                if chunk.name == "sql_query":
                    tracker.record_sql(chunk.content)

                elif chunk.name == "search_pdf_library":
                    tracker.record_pdf(chunk.content)

                elif chunk.name == "mark_attendance":
                    try:
                        attendance_action = json.loads(chunk.content)
                        tracker.record_tool_success(attendance_action.get("success", False))
                    except Exception:
                        pass

                elif chunk.name == "get_attendance_report":
                    try:
                        res = json.loads(chunk.content)
                        tracker.record_tool_success(res.get("success", False))
                        if res.get("success"):
                            attendance_table = res["records"]
                    except Exception:
                        pass

                elif chunk.name == "generate_chart":
                    try:
                        chart_data = json.loads(chunk.content)
                    except Exception:
                        pass

        # Flush last agent step if it was a plain text reply
        if not step_is_tool_call and token_buffer:
            for tok in token_buffer:
                yield json.dumps({"token": tok}) + "\n"

        confidence = tracker.get()
        logger.info("Response confidence: %d%%", confidence)

        # Emit final structured payload (priority: chart > attendance > text)
        if chart_data:
            yield json.dumps({"done": True, "data": chart_data, "confidence": confidence}) + "\n"
        elif attendance_action:
            yield json.dumps({
                "done": True,
                "data": {
                    "type":    "attendance",
                    "status":  "success" if attendance_action.get("success") else "error",
                    "message": attendance_action.get("message", ""),
                },
                "confidence": confidence,
            }) + "\n"
        elif attendance_table is not None:
            yield json.dumps({
                "done": True,
                "data": {"type": "attendance_table", "data": attendance_table},
                "confidence": confidence,
            }) + "\n"
        else:
            yield json.dumps({"done": True, "confidence": confidence}) + "\n"

    except Exception as exc:
        import traceback
        traceback.print_exc()
        msg = _friendly_error(exc)
        s   = str(exc)
        is_failed = "failed_generation" in s or "Failed to call a function" in s
        payload: dict = {"type": "error", "message": msg}
        if is_failed:
            payload["suggestions"] = _SUGGESTIONS
        yield json.dumps({"done": True, "data": payload, "confidence": 0}) + "\n"


# ── Synchronous wrapper (kept for compatibility) ───────────────────────────────

def process_message(message: str, user: dict | None = None) -> dict:
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
