"""
Chatbot core — uses Claude's tool use so the model itself decides which
database or knowledge source to query.  Each data source is a tool:

  query_product_sales   → MySQL sales table
  list_products         → MySQL products table
  get_attendance_report → MySQL attendance table
  mark_attendance       → MySQL attendance table (write)
  search_pdf_library    → ChromaDB vector store (PDFs)

Claude reads the user's natural language message, picks the right tool(s),
fetches data, and composes a response.  Adding a new database is as simple
as defining another tool + its executor below.
"""

import json
from datetime import datetime

import anthropic

from config import ANTHROPIC_API_KEY, LLM_FAST, LLM_SMART
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


# ── Tool definitions (what Claude sees) ──────────────────────────────────────
#
# Each entry describes one data source.  Claude reads the "description" field
# to decide WHEN to call the tool; the "input_schema" field tells it WHAT
# parameters to pass.

TOOLS: list[dict] = [
    {
        "name": "query_product_sales",
        "description": (
            "Query the Sales database for monthly revenue, units sold, and "
            "transaction count for a product.  Use this whenever the user asks "
            "about sales figures, revenue, earnings, or how much was sold."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "product_name": {
                    "type": "string",
                    "description": "Product name or partial name to search for.",
                },
                "month": {
                    "type": "integer",
                    "description": "Month number 1-12.  Omit to use the current month.",
                },
                "year": {
                    "type": "integer",
                    "description": "Four-digit year.  Omit to use the current year.",
                },
            },
            "required": ["product_name"],
        },
    },
    {
        "name": "list_products",
        "description": (
            "Fetch the full product catalogue from the Products database.  Use "
            "this when the user asks which products exist, or when a product name "
            "is ambiguous and you need options to clarify."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "search_pdf_library",
        "description": (
            "Semantic search over the company PDF document library.  Use this "
            "for questions about company policies, procedures, warranties, "
            "product specifications, HR rules, or any other general knowledge "
            "that may exist in the uploaded documents."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The question to search for in the PDF library.",
                },
                "top_k": {
                    "type": "integer",
                    "description": "Number of document chunks to retrieve (default 3).",
                },
            },
            "required": ["question"],
        },
    },
    {
        "name": "mark_attendance",
        "description": (
            "Record an employee's check-in or check-out in the Attendance "
            "database.  Use this when the user says they are checking in, "
            "arriving, checking out, or leaving."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["checkin", "checkout"],
                    "description": "'checkin' when arriving; 'checkout' when leaving.",
                }
            },
            "required": ["action"],
        },
    },
    {
        "name": "get_attendance_report",
        "description": (
            "Retrieve attendance records from the Attendance database.  "
            "Employees can view their own history.  Admins can view all "
            "employees.  Use this when the user asks to see attendance data."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "all_employees": {
                    "type": "boolean",
                    "description": (
                        "True to retrieve attendance for every employee "
                        "(admin only).  False (default) to retrieve only the "
                        "current user's records."
                    ),
                }
            },
            "required": [],
        },
    },
]


# ── Tool executors ────────────────────────────────────────────────────────────
#
# Add a new executor here whenever you add a new tool above.

def _run_tool(name: str, inputs: dict, user: dict | None) -> dict:
    """Dispatch a tool call and return a JSON-serialisable result dict."""
    now = datetime.now()

    if name == "query_product_sales":
        month = inputs.get("month", now.month)
        year  = inputs.get("year",  now.year)
        rows  = get_product_sales(inputs["product_name"], month, year)
        if not rows:
            return {
                "found": False,
                "message": (
                    f"No sales data found for '{inputs['product_name']}' "
                    f"in {datetime(year, month, 1).strftime('%B %Y')}."
                ),
            }
        # Convert Decimal → float for JSON serialisation
        clean = [
            {**r, "total_amount": float(r["total_amount"])} for r in rows
        ]
        return {
            "found": True,
            "rows": clean,
            "product": inputs["product_name"],
            "month": month,
            "year": year,
            "period": datetime(year, month, 1).strftime("%B %Y"),
        }

    if name == "list_products":
        products = get_all_products()
        return {
            "products": [
                {
                    "name": p["name"],
                    "category": p.get("category", ""),
                    "price": float(p["price"]),
                }
                for p in products
            ]
        }

    if name == "search_pdf_library":
        top_k  = inputs.get("top_k", 3)
        chunks = query_pdfs(inputs["question"], top_k=top_k)
        if not chunks:
            return {"found": False, "message": "No relevant content found in the PDF library."}
        return {
            "found": True,
            "chunks": [
                {"source": c["source"], "text": c["text"], "relevance": c["score"]}
                for c in chunks
            ],
        }

    if name == "mark_attendance":
        if not user:
            return {"success": False, "message": "You must be logged in to mark attendance."}
        result = db_mark_attendance(user["employee_id"], inputs["action"])
        return {"success": result["status"] == "success", "message": result["message"]}

    if name == "get_attendance_report":
        if not user:
            return {"success": False, "message": "You must be logged in to view attendance."}
        all_emp = inputs.get("all_employees", False)
        if all_emp and user.get("role") != "admin":
            return {"success": False, "message": "Admin access is required to view all employees' attendance."}
        records = db_get_attendance(employee_id=None if all_emp else user["employee_id"])
        return {"success": True, "records": records, "all_employees": all_emp}

    return {"error": f"Unknown tool: {name}"}


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
    Process one chat message through the Claude tool-use loop.

    Claude decides which tool(s) to call, fetches data, and generates a
    natural-language response.  The function maps tool results to the
    structured response types the frontend understands:

        type == "text"             → plain text bubble
        type == "sales_table"      → rendered HTML table
        type == "attendance_table" → rendered HTML table
        type == "attendance"       → check-in / check-out confirmation badge
        type == "error"            → red error message
    """
    client = _anthropic()

    # Inject user context so Claude can tailor its response
    user_ctx = (
        f"Current user: {user['name']} | role: {user['role']} | "
        f"department: {user.get('department', 'N/A')}."
        if user
        else "User is not authenticated."
    )

    messages: list[dict] = [{"role": "user", "content": message}]

    # Track structured results so we can return the right response type
    last_sales_result    : dict | None = None
    last_attendance_table: list | None = None
    last_attendance_action: dict | None = None

    # Agentic tool-use loop (Claude may call multiple tools in sequence)
    for _ in range(6):   # safety cap
        resp = client.messages.create(
            model=LLM_SMART,
            max_tokens=1024,
            system=[
                {
                    "type": "text",
                    "text": f"{_SYSTEM}\n\n{user_ctx}",
                    # Cache the system prompt + user context so repeated
                    # requests within the same session skip re-tokenising it.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        )

        # ── Claude finished (no more tool calls) ─────────────────────────────
        if resp.stop_reason == "end_turn":
            final_text = next(
                (b.text for b in resp.content if b.type == "text"), ""
            )

            # Return the most specific structured type we collected
            if last_attendance_action:
                return {
                    "type": "attendance",
                    "status": "success" if last_attendance_action["success"] else "error",
                    "message": last_attendance_action["message"],
                }
            if last_attendance_table is not None:
                return {"type": "attendance_table", "data": last_attendance_table}
            if last_sales_result is not None:
                return {
                    "type": "sales_table",
                    "data": last_sales_result["rows"],
                    "month": last_sales_result["period"],
                    "product": last_sales_result["product"],
                }

            return {"type": "text", "message": final_text}

        # ── Claude wants to call tools ────────────────────────────────────────
        if resp.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": resp.content})
            tool_results: list[dict] = []

            for block in resp.content:
                if block.type != "tool_use":
                    continue

                result = _run_tool(block.name, block.input, user)

                # Remember results that map to structured frontend types
                if block.name == "query_product_sales" and result.get("found"):
                    last_sales_result = result
                elif block.name == "get_attendance_report" and result.get("success"):
                    last_attendance_table = result.get("records", [])
                elif block.name == "mark_attendance":
                    last_attendance_action = result

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })

            messages.append({"role": "user", "content": tool_results})
            continue

        # Unexpected stop reason — bail out
        break

    return {"type": "error", "message": "I encountered an issue processing your request. Please try again."}
