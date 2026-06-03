"""Factory — returns database adapters and clients.

get_adapter()         Legacy singleton for the primary SQL DB (reads DB_* env vars).
build_adapter_for()   Create a SQL adapter from a databases.json config entry.
build_mongo_client()  Create a pymongo MongoClient from a databases.json config entry.
build_sql_uri_for()   Return a SQLAlchemy URI for a databases.json config entry.
"""
from __future__ import annotations

import logging
import os
from urllib.parse import quote_plus

logger = logging.getLogger(__name__)

# ── Legacy singleton (primary DB) ─────────────────────────────────────────────

_adapter = None


def get_adapter():
    """Return the primary database adapter singleton.

    Type is read from the first SQL entry in config/databases.json.
    Falls back to DB_TYPE env var only when databases.json is absent
    (backward compat for installations that haven't migrated yet).
    """
    global _adapter
    if _adapter is not None:
        return _adapter

    # ── Primary: derive type from databases.json ───────────────────────────
    try:
        from config import get_databases_config
        for cfg in get_databases_config():
            if cfg["type"].lower() != "mongodb":
                _adapter = build_adapter_for(cfg)
                logger.info(
                    "DB adapter (primary): %s @ %s",
                    cfg["type"], cfg["name"],
                )
                return _adapter
    except Exception as exc:
        logger.debug("get_adapter: databases.json lookup failed (%s) — falling back to DB_TYPE", exc)

    # ── Fallback: legacy DB_TYPE env var ───────────────────────────────────
    db_type  = os.getenv("DB_TYPE", "mysql").lower()
    host     = os.getenv("DB_HOST", "localhost")
    user     = os.getenv("DB_USER", "")
    password = os.getenv("DB_PASSWORD", "")
    database = os.getenv("DB_NAME", "")

    if db_type == "mysql":
        port = int(os.getenv("DB_PORT", 3306))
        from .mysql_adapter import MySQLAdapter
        _adapter = MySQLAdapter(host=host, port=port, user=user, password=password, database=database)
        logger.info("DB adapter (legacy): MySQL @ %s:%s/%s", host, port, database)

    elif db_type in ("postgresql", "postgres", "pg"):
        port   = int(os.getenv("DB_PORT", 5432))
        schema = os.getenv("DB_SCHEMA") or None
        from .postgresql_adapter import PostgreSQLAdapter
        _adapter = PostgreSQLAdapter(
            host=host, port=port, user=user, password=password,
            database=database, schema=schema,
        )
        logger.info("DB adapter (legacy): PostgreSQL @ %s:%s/%s", host, port, database)

    else:
        raise RuntimeError(
            "No SQL database configured. "
            "Add a mysql/postgresql entry to config/databases.json, "
            "or set DB_TYPE in .env. "
            "If you are using only MongoDB, call get_primary_mongo() instead."
        )

    return _adapter


def reset_adapter() -> None:
    """Discard the cached primary adapter (forces re-creation on next call)."""
    global _adapter
    _adapter = None


# ── Per-DB builders (multi-DB support) ────────────────────────────────────────

def build_adapter_for(cfg: dict):
    """Create a SQL adapter from a databases.json config entry.

    cfg must have: type, env_prefix
    Reads <PREFIX>_HOST / _PORT / _USER / _PASSWORD / _NAME / _SCHEMA from env.
    """
    db_type = cfg["type"].lower()
    p       = cfg["env_prefix"]

    host     = os.getenv(f"{p}_HOST",     "localhost")
    user     = os.getenv(f"{p}_USER",     "")
    password = os.getenv(f"{p}_PASSWORD", "")
    database = os.getenv(f"{p}_NAME",     "")

    if db_type == "mysql":
        port = int(os.getenv(f"{p}_PORT", 3306))
        from .mysql_adapter import MySQLAdapter
        return MySQLAdapter(host=host, port=port, user=user, password=password, database=database)

    if db_type in ("postgresql", "postgres", "pg"):
        port   = int(os.getenv(f"{p}_PORT", 5432))
        schema = os.getenv(f"{p}_SCHEMA") or None
        from .postgresql_adapter import PostgreSQLAdapter
        return PostgreSQLAdapter(
            host=host, port=port, user=user, password=password,
            database=database, schema=schema,
        )

    raise ValueError(
        f"build_adapter_for: unsupported SQL type {db_type!r} for {cfg.get('name')!r}. "
        "Use 'mysql' or 'postgresql'."
    )


def build_sql_uri_for(cfg: dict) -> str:
    """Return a SQLAlchemy connection URI for a databases.json config entry."""
    return build_adapter_for(cfg).get_uri()


def get_primary_mongo():
    """Return (MongoClient, db_name) for the first MongoDB entry in databases.json.

    Returns (None, None) if no MongoDB database is configured.
    """
    try:
        from config import get_databases_config
        import os
        for cfg in get_databases_config():
            if cfg["type"].lower() == "mongodb":
                client  = build_mongo_client(cfg)
                db_name = os.getenv(f"{cfg['env_prefix']}_NAME", "")
                return client, db_name
    except Exception as exc:
        logger.warning("get_primary_mongo: failed — %s", exc)
    return None, None


def build_mongo_client(cfg: dict):
    """Create a pymongo MongoClient from a databases.json config entry.

    Reads <PREFIX>_URI first; falls back to building from HOST / PORT / USER / PASSWORD.
    """
    try:
        import pymongo
    except ImportError as exc:
        raise ImportError(
            "pymongo is required for MongoDB support. "
            "Install it with: pip install pymongo"
        ) from exc

    p   = cfg["env_prefix"]
    uri = os.getenv(f"{p}_URI", "")

    if not uri:
        host     = os.getenv(f"{p}_HOST",     "localhost")
        port     = os.getenv(f"{p}_PORT",     "27017")
        user     = os.getenv(f"{p}_USER",     "")
        password = os.getenv(f"{p}_PASSWORD", "")
        auth     = f"{quote_plus(user)}:{quote_plus(password)}@" if user else ""
        uri      = f"mongodb://{auth}{host}:{port}"

    logger.info("MongoDB client: %s (%s)", cfg.get("name"), uri.split("@")[-1])
    return pymongo.MongoClient(uri)
