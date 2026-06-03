"""Database operations — auth only.

Login is handled via config/users.json (static file).
get_employee_by_username() also falls back to a MongoDB employees collection
if one is configured in databases.json, so SQL is never required.
"""
from __future__ import annotations

import hashlib
import logging

from config import get_table_config, get_local_users, get_databases_config

logger = logging.getLogger(__name__)


def _t() -> dict:
    return get_table_config()


def _is_mongo_primary() -> bool:
    dbs = get_databases_config()
    return bool(dbs) and dbs[0]["type"].lower() == "mongodb"


def _get_mongo():
    from db.factory import get_primary_mongo
    return get_primary_mongo()


# ── Auth ───────────────────────────────────────────────────────────────────────

def get_employee_by_username(username: str) -> dict | None:
    """Look up a user for login.

    Priority:
      1. config/users.json  (always checked first — static, no DB needed)
      2. MongoDB employees collection  (if configured and user not in users.json)
    """
    # 1. Static users.json
    for u in get_local_users():
        if u.get("username") == username:
            user = dict(u)
            plain = user.pop("password", "")
            user["password"] = hashlib.sha256(plain.encode()).hexdigest()
            user.setdefault("employee_id", 0)
            return user

    # 2. MongoDB fallback
    if _is_mongo_primary():
        t = _t()
        coll_name = t.get("employees")
        if coll_name:
            client, db_name = _get_mongo()
            if client is not None:
                doc = client[db_name][coll_name].find_one({"username": username})
                if doc:
                    doc.pop("_id", None)
                    return doc

    return None
