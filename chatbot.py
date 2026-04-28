import re
from datetime import datetime
from database import get_product_sales, mark_attendance, get_attendance_report, get_all_products
from pdf_handler import answer_from_pdfs

# ── intent keyword sets ──────────────────────────────────────────────────────

_GREET = {"hello", "hi", "hey", "howdy", "greetings", "good morning", "good afternoon", "good evening"}
_HELP  = {"help", "what can you do", "commands", "features", "options"}

_CHECKIN  = {"check in", "checkin", "check-in", "mark attendance", "i am in", "i'm in"}
_CHECKOUT = {"check out", "checkout", "check-out", "i am out", "i'm out", "leaving"}

_SALES_WORDS = {"sales", "sell", "sold", "revenue", "sale", "earning", "earnings"}

_ADMIN_ATTENDANCE = {
    "show attendance", "all attendance", "employee attendance",
    "attendance report", "staff attendance", "view attendance",
}


def detect_intent(message: str) -> str:
    msg = message.lower().strip()

    if any(msg.startswith(g) or g in msg for g in _GREET):
        return "greet"
    if any(h in msg for h in _HELP):
        return "help"
    if any(a in msg for a in _ADMIN_ATTENDANCE):
        return "view_attendance"
    if any(c in msg for c in _CHECKIN):
        return "checkin"
    if any(c in msg for c in _CHECKOUT):
        return "checkout"
    if any(s in msg for s in _SALES_WORDS):
        return "product_sales"
    return "pdf_query"


def _extract_product_name(message: str) -> str | None:
    msg = message.lower()
    patterns = [
        r"(?:sales?|sell|sold|revenue|earning)\s+(?:for|of)\s+([a-z0-9 ]+?)(?:\s+(?:this|last|in|for)\s+month)?$",
        r"([a-z0-9 ]+?)\s+(?:sales?|sold|revenue)",
    ]
    stop = {"the", "a", "an", "for", "of", "in", "this", "month", "year", "last", "show", "me", "what", "are"}
    for pattern in patterns:
        m = re.search(pattern, msg, re.IGNORECASE)
        if m:
            words = [w for w in m.group(1).strip().split() if w not in stop]
            if words:
                return " ".join(words)
    return None


def process_message(message: str, user: dict | None = None) -> dict:
    intent = detect_intent(message)

    # ── greet ────────────────────────────────────────────────────────────────
    if intent == "greet":
        name = user["name"] if user else "there"
        return {
            "type": "text",
            "message": (
                f"Hello, {name}! I can help you with:\n"
                "- **Product sales** – *\"Show sales for Laptop\"*\n"
                "- **PDF documents** – ask any question\n"
                "- **Attendance** – *\"Check in\"* / *\"Check out\"*\n"
                + ("- **Admin** – *\"Show all attendance\"*\n" if user and user.get("role") == "admin" else "")
                + "\nType **help** for more details."
            ),
        }

    # ── help ─────────────────────────────────────────────────────────────────
    if intent == "help":
        lines = [
            "**Available commands:**",
            "",
            "**Product Sales**",
            "- *Show sales for [product name]*",
            "- *What are the sales for Laptop this month?*",
            "",
            "**PDF Library**",
            "- Ask any question – I'll search the PDF documents",
            "",
            "**Attendance**",
            "- *Check in* – mark your arrival",
            "- *Check out* – mark your departure",
        ]
        if user and user.get("role") == "admin":
            lines += ["", "**Admin**", "- *Show all attendance*", "- *Employee attendance report*"]
        return {"type": "text", "message": "\n".join(lines)}

    # ── check-in ─────────────────────────────────────────────────────────────
    if intent == "checkin":
        if not user:
            return {"type": "error", "message": "Please log in to mark attendance."}
        result = mark_attendance(user["employee_id"], "checkin")
        return {"type": "attendance", "message": result["message"], "status": result["status"]}

    # ── check-out ────────────────────────────────────────────────────────────
    if intent == "checkout":
        if not user:
            return {"type": "error", "message": "Please log in to mark attendance."}
        result = mark_attendance(user["employee_id"], "checkout")
        return {"type": "attendance", "message": result["message"], "status": result["status"]}

    # ── view attendance ──────────────────────────────────────────────────────
    if intent == "view_attendance":
        if not user:
            return {"type": "error", "message": "Please log in to view attendance."}
        if user.get("role") == "admin":
            records = get_attendance_report()
        else:
            records = get_attendance_report(employee_id=user["employee_id"])
        if not records:
            return {"type": "text", "message": "No attendance records found."}
        return {"type": "attendance_table", "data": records}

    # ── product sales ────────────────────────────────────────────────────────
    if intent == "product_sales":
        product_name = _extract_product_name(message)
        if not product_name:
            products = get_all_products()
            names = ", ".join(p["name"] for p in products[:15])
            return {
                "type": "text",
                "message": f"Which product would you like sales data for?\n\nAvailable products: **{names}**",
            }
        now = datetime.now()
        results = get_product_sales(product_name, now.month, now.year)
        if not results:
            return {
                "type": "text",
                "message": (
                    f"No sales found for **{product_name}** in {now.strftime('%B %Y')}.\n"
                    "Try a different product name or check the spelling."
                ),
            }
        return {
            "type": "sales_table",
            "data": results,
            "month": now.strftime("%B %Y"),
            "product": product_name,
        }

    # ── pdf query (default) ──────────────────────────────────────────────────
    answer = answer_from_pdfs(message)
    return {"type": "text", "message": answer}
