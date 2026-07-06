import hashlib
import logging
import uuid

from flask import Flask, Response, jsonify, redirect, render_template, request, session, stream_with_context, url_for

from chatbot import clear_history, invalidate_sql_db_cache, stream_message
from config import SECRET_KEY, CURRENCY_SYMBOL
from database import get_employee_by_username
from pdf_handler import get_pdf_list, load_pdfs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Auto-sync all DB schemas (columns + FK relationships) at startup.
# Falls back silently if any DB is not yet reachable.
try:
    from config import sync_all_db_schemas
    sync_all_db_schemas()
except Exception as _sync_exc:
    logger.warning("Schema auto-sync skipped: %s", _sync_exc)

app.secret_key = SECRET_KEY


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _current_user() -> dict | None:
    return session.get("user")


def _require_login():
    if not _current_user():
        return redirect(url_for("login"))
    return None


def _require_admin():
    user = _current_user()
    if not user or user.get("role") != "admin":
        return jsonify({"error": "Admin access required."}), 403
    return None


# ── Pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    redir = _require_login()
    if redir:
        return redir
    return render_template("index.html", user=_current_user(), currency=CURRENCY_SYMBOL)


@app.route("/login", methods=["GET", "POST"])
def login():
    if _current_user():
        return redirect(url_for("index"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        employee = get_employee_by_username(username)
        if employee and employee["password"] == _hash(password):
            session["user"] = {
                "employee_id": employee["employee_id"],
                "name":        employee["name"],
                "role":        employee["role"],
                "username":    employee["username"],
                "department":  employee.get("department", ""),
            }
            return redirect(url_for("index"))
        error = "Invalid username or password."

    return render_template("login.html", error=error, currency=CURRENCY_SYMBOL)


@app.route("/logout")
def logout():
    thread_id = session.get("chat_thread_id")
    if thread_id:
        clear_history(thread_id)
    session.clear()
    return redirect(url_for("login"))


# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def chat():
    redir = _require_login()
    if redir:
        return jsonify({"error": "Not authenticated."}), 401

    data    = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message."}), 400

    user = _current_user()

    if "chat_thread_id" not in session:
        session["chat_thread_id"] = str(uuid.uuid4())
    thread_id = session["chat_thread_id"]

    def generate():
        yield from stream_message(message, user, thread_id)

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.route("/api/clear-chat", methods=["POST"])
def clear_chat():
    redir = _require_login()
    if redir:
        return jsonify({"error": "Not authenticated."}), 401
    thread_id = session.get("chat_thread_id")
    if thread_id:
        clear_history(thread_id)
    # Issue a new thread ID so the next message starts a fresh conversation.
    session["chat_thread_id"] = str(uuid.uuid4())
    return jsonify({"message": "Chat history cleared."})


@app.route("/api/pdfs")
def list_pdfs():
    redir = _require_login()
    if redir:
        return jsonify({"error": "Not authenticated."}), 401
    return jsonify({"pdfs": get_pdf_list()})


@app.route("/api/reload-pdfs", methods=["POST"])
def reload_pdfs():
    err = _require_admin()
    if err:
        return err
    load_pdfs()
    return jsonify({"message": "PDF library reloaded successfully."})


@app.route("/api/sync-schema", methods=["POST"])
def sync_schema():
    """Re-discover columns and FK relationships for all configured databases.

    Also invalidates the SQLDatabase cache so the agent picks up any new tables
    added to tables.json since the last sync.
    Admin only.
    """
    err = _require_admin()
    if err:
        return err

    from config import get_databases_config, sync_all_db_schemas

    try:
        sync_all_db_schemas()
        invalidate_sql_db_cache()
        db_names = [c["name"] for c in get_databases_config()]
        return jsonify({
            "message": f"Schema synced for: {', '.join(db_names)}.",
        })
    except Exception as exc:
        logger.error("Schema sync failed: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
