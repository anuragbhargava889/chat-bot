"""Database operations — adapter-agnostic, table names from config/tables.json.

SELECT queries are built with QueryBuilder (db/query_builder.py).
Write operations (INSERT/UPDATE) use adapter.execute_write() with raw SQL and
:named parameters — both MySQL and PostgreSQL compatible.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime

from db.factory import get_adapter
from db.query_builder import QueryBuilder
from config import get_table_config, get_local_users

logger = logging.getLogger(__name__)


def _t() -> dict:
    return get_table_config()


# ── Auth ───────────────────────────────────────────────────────────────────────

def get_employee_by_username(username: str) -> dict | None:
    t = _t()
    employees_table = t.get("employees")

    if not employees_table:
        # No DB employees table — check config/users.json
        for u in get_local_users():
            if u.get("username") == username:
                user = dict(u)
                plain = user.pop("password", "")
                user["password"] = hashlib.sha256(plain.encode()).hexdigest()
                user.setdefault("employee_id", 0)
                return user
        return None

    rows = (
        QueryBuilder(employees_table)
        .select("*")
        .where("username = :username", username=username)
        .limit(1)
        .execute()
    )
    return rows[0] if rows else None


# ── Attendance ─────────────────────────────────────────────────────────────────

def mark_attendance(employee_id: int, action: str) -> dict:
    adapter = get_adapter()
    t   = _t()
    tbl = t.get("attendance")
    if not tbl:
        return {"status": "error", "message": "'attendance' table not configured in tables.json."}
    today = date.today()

    try:
        existing = (
            QueryBuilder(tbl)
            .select("*")
            .where("employee_id = :eid AND date = :dt", eid=employee_id, dt=today)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        logger.error("Attendance lookup failed: %s", exc)
        return {"status": "error", "message": "Database error during attendance lookup."}

    if action == "checkin":
        if existing:
            return {"status": "error", "message": "You have already checked in today."}
        try:
            adapter.execute_write(
                f"INSERT INTO {tbl} (employee_id, date, check_in, status)"
                f" VALUES (:eid, :dt, NOW(), 'present')",
                {"eid": employee_id, "dt": today},
            )
        except Exception as exc:
            logger.error("Check-in write failed: %s", exc)
            return {"status": "error", "message": "Database error during check-in."}
        return {
            "status": "success",
            "message": f"Check-in marked at {datetime.now().strftime('%H:%M:%S')}.",
        }

    if action == "checkout":
        if not existing:
            return {"status": "error", "message": "You haven't checked in today yet."}
        if existing[0].get("check_out"):
            return {"status": "error", "message": "You have already checked out today."}
        try:
            adapter.execute_write(
                f"UPDATE {tbl} SET check_out = NOW()"
                f" WHERE employee_id = :eid AND date = :dt",
                {"eid": employee_id, "dt": today},
            )
        except Exception as exc:
            logger.error("Check-out write failed: %s", exc)
            return {"status": "error", "message": "Database error during check-out."}
        return {
            "status": "success",
            "message": f"Check-out marked at {datetime.now().strftime('%H:%M:%S')}.",
        }

    return {"status": "error", "message": f"Unknown attendance action: {action!r}."}


def get_attendance_report(employee_id: int | None = None) -> list[dict]:
    t    = _t()
    atbl = t.get("attendance")
    etbl = t.get("employees")
    if not atbl or not etbl:
        logger.warning("'attendance' or 'employees' key missing from tables.json — report empty")
        return []

    qb = (
        QueryBuilder(f"{atbl} a")
        .select("e.name", "e.department", "a.date", "a.check_in", "a.check_out", "a.status")
        .inner_join(f"{etbl} e", on="a.employee_id = e.employee_id")
        .order_by("a.date", desc=True)
    )

    if employee_id is not None:
        qb.where("a.employee_id = :eid", eid=employee_id).limit(30)
    else:
        qb.order_by("e.name").limit(200)

    try:
        return qb.execute()
    except Exception as exc:
        logger.error("Attendance report failed: %s", exc)
        return []
