"""
Chatbot core — manual tool-calling loop via get_llm() + bind_tools.

Two entry points:
  process_message() → dict          (kept for compatibility)
  stream_message()  → NDJSON events (used by the SSE endpoint)

Tools:
  query_product_sales   → MySQL sales table
  list_products         → MySQL products table
  get_attendance_report → MySQL attendance table (read)
  mark_attendance       → MySQL attendance table (write)
  search_pdf_library    → ChromaDB vector store (PDFs)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool

from config import get_llm
from database import (
    get_all_products,
    get_attendance_report as db_get_attendance,
    get_product_sales,
    mark_attendance as db_mark_attendance,
)
from pdf_handler import query_pdfs

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = """You are a professional company assistant chatbot connected to multiple databases and document repositories.

Data sources you can query via tools:
• Sales database      — monthly product revenue, units sold, transactions
• Products database   — full product catalogue with categories and prices
• Attendance database — employee check-in / check-out records (read & write)
• PDF library         — company documents, policies, manuals (semantic search)

Behaviour rules:
1. Always use the appropriate tool to fetch real data before answering a data question.
2. For sales or attendance questions, present the key numbers clearly.
3. For PDF answers, cite the source document name.
4. For attendance actions (check-in / check-out) confirm the action and timestamp.
5. If a question could involve multiple databases, call all relevant tools.
6. Be concise and professional; avoid unnecessary preamble."""


# ── Shared helpers ────────────────────────────────────────────────────────────

def _extract_text(content) -> str:
    """Pull plain text from a str, list-of-blocks, or any content value."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in content
        )
    return str(content) if content else ""


def _make_tools(user, now, _results: dict):
    """
    Factory: returns (agent_tools, tool_map) with closures capturing
    user, now, and _results so those never appear as LLM parameters.
    """

    @tool
    def query_product_sales(
        product_name: str,
        month: Optional[int] = None,
        year: Optional[int] = None,
    ) -> str:
        """Query the Sales database for monthly revenue, units sold, and transaction count.

        Use this whenever the user asks about sales figures, revenue, earnings,
        or how much was sold.

        Args:
            product_name: Product name or partial name to search for.
            month: Month number 1-12. Omit to use the current month.
            year: Four-digit year. Omit to use the current year.
        """
        m = month or now.month
        y = year or now.year
        rows = get_product_sales(product_name, m, y)
        if not rows:
            return json.dumps({
                "found": False,
                "message": (
                    f"No sales data found for '{product_name}' "
                    f"in {datetime(y, m, 1).strftime('%B %Y')}."
                ),
            })
        result = {
            "found": True,
            "rows": rows,
            "product": product_name,
            "month": m,
            "year": y,
            "period": datetime(y, m, 1).strftime("%B %Y"),
        }
        _results["sales"] = result
        return json.dumps(result)

    @tool
    def list_products() -> str:
        """Fetch the full product catalogue from the Products database.

        Use this when the user asks which products exist, or when a product name
        is ambiguous and you need options to clarify.
        """
        products = get_all_products()
        return json.dumps({
            "products": [
                {"name": p["name"], "category": p.get("category", ""), "price": p["price"]}
                for p in products
            ]
        })

    @tool
    def search_pdf_library(question: str, top_k: int = 3) -> str:
        """Semantic search over the company PDF document library.

        Use for questions about company policies, procedures, warranties, product
        specifications, HR rules, or any general knowledge in uploaded documents.

        Args:
            question: The question to search for in the PDF library.
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
        """Record an employee's check-in or check-out in the Attendance database.

        Use when the user says they are checking in, arriving, checking out, or leaving.

        Args:
            action: 'checkin' when arriving; 'checkout' when leaving.
        """
        if action not in ("checkin", "checkout"):
            return json.dumps({"success": False, "message": "action must be 'checkin' or 'checkout'."})
        if not user:
            return json.dumps({"success": False, "message": "You must be logged in to mark attendance."})
        result = db_mark_attendance(user["employee_id"], action)
        outcome = {"success": result["status"] == "success", "message": result["message"]}
        _results["attendance_action"] = outcome
        return json.dumps(outcome)

    @tool
    def get_attendance_report(all_employees: bool = False) -> str:
        """Retrieve attendance records from the Attendance database.

        Employees can view their own history. Admins can view all employees.
        Use when the user asks to see attendance data.

        Args:
            all_employees: True to retrieve every employee's records (admin only).
                           False (default) to retrieve only the current user's records.
        """
        if not user:
            return json.dumps({"success": False, "message": "You must be logged in to view attendance."})
        if all_employees and user.get("role") != "admin":
            return json.dumps({
                "success": False,
                "message": "Admin access is required to view all employees' attendance.",
            })
        records = db_get_attendance(employee_id=None if all_employees else user["employee_id"])
        _results["attendance_table"] = records
        return json.dumps({"success": True, "records": records, "all_employees": all_employees})

    agent_tools = [
        query_product_sales,
        list_products,
        search_pdf_library,
        mark_attendance,
        get_attendance_report,
    ]
    return agent_tools, {t.name: t for t in agent_tools}


def _structured_result(_results: dict, response) -> dict | None:
    """Map tool results to a structured frontend response, or None for text."""
    if _results["attendance_action"]:
        return {
            "type": "attendance",
            "status": "success" if _results["attendance_action"]["success"] else "error",
            "message": _results["attendance_action"]["message"],
        }
    if _results["attendance_table"] is not None:
        return {"type": "attendance_table", "data": _results["attendance_table"]}
    if _results["sales"] is not None:
        return {
            "type": "sales_table",
            "data": _results["sales"]["rows"],
            "month": _results["sales"]["period"],
            "product": _results["sales"]["product"],
        }
    return None


def _run_tool_calls(tool_calls, tool_map, messages):
    """Execute a list of tool calls and append ToolMessages."""
    for call in tool_calls:
        fn = tool_map.get(call["name"])
        result = fn.invoke(call["args"]) if fn else f"Unknown tool: {call['name']}"
        messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))


# ── Streaming entry point (SSE) ───────────────────────────────────────────────

def stream_message(message: str, user: dict | None = None):
    """
    Generator yielding newline-delimited JSON events for SSE.

    Event shapes:
        {"status": "..."}              — shown in typing indicator during tool use
        {"token": "..."}              — text token streamed to a live bubble
        {"done": true}                — text streaming complete (no more tokens)
        {"done": true, "data": {...}} — structured response (table / attendance / error)
    """
    now = datetime.now()
    _results: dict = {"sales": None, "attendance_table": None, "attendance_action": None}
    agent_tools, tool_map = _make_tools(user, now, _results)

    user_ctx = (
        f"Current user: {user['name']} | role: {user['role']} | "
        f"department: {user.get('department', 'N/A')}."
        if user
        else "User is not authenticated."
    )

    try:
        llm = get_llm()
        llm_with_tools = llm.bind_tools(agent_tools)

        messages = [
            SystemMessage(content=f"{_SYSTEM}\n\n{user_ctx}"),
            HumanMessage(content=message),
        ]

        # ── First call: stream so text responses appear token-by-token ────────
        accumulated: AIMessageChunk | None = None
        tool_call_detected = False

        for chunk in llm_with_tools.stream(messages):
            if getattr(chunk, "tool_call_chunks", None):
                tool_call_detected = True

            accumulated = chunk if accumulated is None else accumulated + chunk

            if not tool_call_detected:
                token = _extract_text(chunk.content)
                if token:
                    yield json.dumps({"token": token}) + "\n"

        if accumulated is None:
            yield json.dumps({
                "done": True,
                "data": {"type": "error", "message": "No response received from model."},
            }) + "\n"
            return

        tool_calls = getattr(accumulated, "tool_calls", [])

        # ── No tool calls → streaming is done ────────────────────────────────
        if not tool_call_detected and not tool_calls:
            yield json.dumps({"done": True}) + "\n"
            return

        # ── Tool calls detected → execute, then continue with invoke() ────────
        messages.append(accumulated)

        if not tool_calls:
            yield json.dumps({"done": True}) + "\n"
            return

        for call in tool_calls:
            name = call.get("name", "tool")
            label = name.replace("_", " ")
            yield json.dumps({"status": f"Running {label}…"}) + "\n"
        _run_tool_calls(tool_calls, tool_map, messages)

        response: AIMessage | None = None
        for _ in range(5):
            response = llm_with_tools.invoke(messages)
            messages.append(response)
            if not response.tool_calls:
                break
            for call in response.tool_calls:
                name = call.get("name", "tool")
                yield json.dumps({"status": f"Running {name.replace('_', ' ')}…"}) + "\n"
            _run_tool_calls(response.tool_calls, tool_map, messages)

        # ── Map results to structured or text response ────────────────────────
        structured = _structured_result(_results, response)
        if structured:
            yield json.dumps({"done": True, "data": structured}) + "\n"
            return

        final_text = _extract_text(response.content if response else "")
        if not final_text.strip():
            final_text = "Done — let me know if you need anything else."

        yield json.dumps({"done": True, "data": {"type": "text", "message": final_text}}) + "\n"

    except Exception as exc:
        import traceback
        traceback.print_exc()
        yield json.dumps({
            "done": True,
            "data": {"type": "error", "message": f"Error: {exc}"},
        }) + "\n"


# ── Synchronous entry point (kept for compatibility) ──────────────────────────

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
            # Accumulate tokens (fallback — streaming should be used instead)
            if last.get("type") != "text":
                last = {"type": "text", "message": ""}
            last["message"] = last.get("message", "") + evt["token"]
    return last
