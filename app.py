import hashlib

from flask import Flask, Response, jsonify, redirect, render_template, request, session, stream_with_context, url_for

from chatbot import stream_message
from config import SECRET_KEY
from database import get_employee_by_username
from pdf_handler import get_pdf_list, load_pdfs

app = Flask(__name__)
app.secret_key = SECRET_KEY


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


# ── auth helpers ─────────────────────────────────────────────────────────────

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


# ── pages ─────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    redir = _require_login()
    if redir:
        return redir
    return render_template("index.html", user=_current_user())


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
                "name": employee["name"],
                "role": employee["role"],
                "username": employee["username"],
                "department": employee.get("department", ""),
            }
            return redirect(url_for("index"))
        error = "Invalid username or password."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── API ───────────────────────────────────────────────────────────────────────

@app.route("/api/chat", methods=["POST"])
def chat():
    redir = _require_login()
    if redir:
        return jsonify({"error": "Not authenticated."}), 401

    data = request.get_json(silent=True) or {}
    message = data.get("message", "").strip()
    if not message:
        return jsonify({"error": "Empty message."}), 400

    user = _current_user()

    def generate():
        yield from stream_message(message, user)

    return Response(
        stream_with_context(generate()),
        mimetype="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


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


# ── run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
