"""
Chatbot core — manual tool-calling loop via ChatOllama + bind_tools.

The LLM is given bound tools; we run the loop ourselves:
  1. Call LLM with current messages
  2. If it requests tool calls → execute them, append results, repeat
  3. When no tool calls remain → return the final text

Tools:
  query_product_sales   → MySQL sales table
  list_products         → MySQL products table
  get_attendance_report → MySQL attendance table (read)
  mark_attendance       → MySQL attendance table (write)
  search_pdf_library    → ChromaDB vector store (PDFs)
"""

import json
from datetime import datetime
from typing import Optional

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_ollama import ChatOllama

from config import LLM_MODEL, OLLAMA_HOST
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


# ── Main entry point ──────────────────────────────────────────────────────────

def process_message(message: str, user: dict | None = None) -> dict:
    """
    Process one chat message through a manual tool-calling loop.

    We call ChatOllama with bound tools, check for tool calls in the response,
    execute them, and feed results back until the LLM stops requesting tools.
    Tool closures write structured results into _results; after the loop we map
    them to the response type the frontend understands:

        type == "text"             → plain text bubble
        type == "sales_table"      → rendered HTML table
        type == "attendance_table" → rendered HTML table
        type == "attendance"       → check-in / check-out confirmation badge
        type == "error"            → red error message
    """
    now = datetime.now()

    # Mutable results bag — tool closures write here, we read after the loop
    _results: dict = {
        "sales": None,
        "attendance_table": None,
        "attendance_action": None,
    }

    # ── Tool definitions ──────────────────────────────────────────────────────
    #
    # Defined as closures so they capture `user`, `now`, and `_results`
    # without exposing those as tool parameters to the LLM.

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
        clean = [{**r, "total_amount": float(r["total_amount"])} for r in rows]
        result = {
            "found": True,
            "rows": clean,
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
                {
                    "name": p["name"],
                    "category": p.get("category", ""),
                    "price": float(p["price"]),
                }
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

    # ── Build tool registry and bind to LLM ───────────────────────────────────

    agent_tools = [
        query_product_sales,
        list_products,
        search_pdf_library,
        mark_attendance,
        get_attendance_report,
    ]
    tool_map = {t.name: t for t in agent_tools}

    user_ctx = (
        f"Current user: {user['name']} | role: {user['role']} | "
        f"department: {user.get('department', 'N/A')}."
        if user
        else "User is not authenticated."
    )

    # ── Run the manual tool-calling loop ──────────────────────────────────────

    try:
        llm = ChatOllama(model=LLM_MODEL, base_url=OLLAMA_HOST, temperature=0)
        llm_with_tools = llm.bind_tools(agent_tools)

        messages = [
            SystemMessage(content=f"{_SYSTEM}\n\n{user_ctx}"),
            HumanMessage(content=message),
        ]

        response: AIMessage | None = None
        for _ in range(6):
            response = llm_with_tools.invoke(messages)
            messages.append(response)

            if not response.tool_calls:
                break

            for call in response.tool_calls:
                fn = tool_map.get(call["name"])
                result = fn.invoke(call["args"]) if fn else f"Unknown tool: {call['name']}"
                messages.append(ToolMessage(content=str(result), tool_call_id=call["id"]))

    except Exception as exc:
        import traceback
        traceback.print_exc()
        return {"type": "error", "message": f"Error: {exc}"}

    if response is None:
        return {"type": "error", "message": "I encountered an issue processing your request. Please try again."}

    # ── Map collected results to structured frontend response types ───────────

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

    final_text = response.content if isinstance(response.content, str) else ""
    return {"type": "text", "message": final_text}
