"""
Chatbot core — uses the Anthropic SDK tool runner so the SDK manages the
agentic loop automatically.  Each data source is a @beta_tool function;
the SDK calls Claude, executes whichever tools it requests, feeds results
back, and repeats until Claude is done.

  query_product_sales   → MySQL sales table
  list_products         → MySQL products table
  get_attendance_report → MySQL attendance table (read)
  mark_attendance       → MySQL attendance table (write)
  search_pdf_library    → ChromaDB vector store (PDFs)
"""

import json
from datetime import datetime
from typing import Literal, Optional

import anthropic
from anthropic import beta_tool

from config import ANTHROPIC_API_KEY, LLM_SMART
from database import (
    get_all_products,
    get_attendance_report as db_get_attendance,
    get_product_sales,
    mark_attendance as db_mark_attendance,
)
from pdf_handler import query_pdfs

# ── Anthropic client ──────────────────────────────────────────────────────────

_client: anthropic.Anthropic | None = None


def _anthropic() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return _client


# ── System prompt (cached on the first request) ───────────────────────────────

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
    Process one chat message through the Claude tool-use agent loop.

    The Anthropic SDK tool runner calls Claude, executes requested tools,
    feeds results back, and repeats automatically.  Tool closures write
    structured results into _results; after the loop we map them to the
    response type the frontend understands:

        type == "text"             → plain text bubble
        type == "sales_table"      → rendered HTML table
        type == "attendance_table" → rendered HTML table
        type == "attendance"       → check-in / check-out confirmation badge
        type == "error"            → red error message
    """
    client = _anthropic()
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
    # without exposing those as tool parameters to Claude.

    @beta_tool
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

    @beta_tool
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

    @beta_tool
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

    @beta_tool
    def mark_attendance(action: Literal["checkin", "checkout"]) -> str:
        """Record an employee's check-in or check-out in the Attendance database.

        Use when the user says they are checking in, arriving, checking out, or leaving.

        Args:
            action: 'checkin' when arriving; 'checkout' when leaving.
        """
        if not user:
            return json.dumps({"success": False, "message": "You must be logged in to mark attendance."})
        result = db_mark_attendance(user["employee_id"], action)
        outcome = {"success": result["status"] == "success", "message": result["message"]}
        _results["attendance_action"] = outcome
        return json.dumps(outcome)

    @beta_tool
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

    # ── Run the agent via the SDK tool runner ─────────────────────────────────

    user_ctx = (
        f"Current user: {user['name']} | role: {user['role']} | "
        f"department: {user.get('department', 'N/A')}."
        if user
        else "User is not authenticated."
    )

    try:
        runner = client.beta.messages.tool_runner(
            model=LLM_SMART,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": f"{_SYSTEM}\n\n{user_ctx}",
                    # Cache the system prompt so repeated requests within the
                    # same session skip re-tokenising it.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[
                query_product_sales,
                list_products,
                search_pdf_library,
                mark_attendance,
                get_attendance_report,
            ],
            messages=[{"role": "user", "content": message}],
        )

        final_message = None
        for msg in runner:
            final_message = msg

    except Exception:
        return {"type": "error", "message": "I encountered an issue processing your request. Please try again."}

    if final_message is None:
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

    final_text = next(
        (b.text for b in final_message.content if b.type == "text"), ""
    )
    return {"type": "text", "message": final_text}
