"""Factory — returns the configured DatabaseAdapter singleton."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_adapter = None


def get_adapter():
    """Return the active database adapter, creating it on first call."""
    global _adapter
    if _adapter is not None:
        return _adapter

    db_type = os.getenv("DB_TYPE", "mysql").lower()
    host = os.getenv("DB_HOST", "localhost")
    user = os.getenv("DB_USER", "root")
    password = os.getenv("DB_PASSWORD", "")
    database = os.getenv("DB_NAME", "chatbot_db")

    if db_type == "mysql":
        port = int(os.getenv("DB_PORT", 3306))
        from .mysql_adapter import MySQLAdapter
        _adapter = MySQLAdapter(host=host, port=port, user=user, password=password, database=database)
        logger.info("DB adapter: MySQL @ %s:%s/%s", host, port, database)

    elif db_type in ("postgresql", "postgres", "pg"):
        port = int(os.getenv("DB_PORT", 5432))
        schema = os.getenv("DB_SCHEMA") or None
        from .postgresql_adapter import PostgreSQLAdapter
        _adapter = PostgreSQLAdapter(
            host=host, port=port, user=user, password=password,
            database=database, schema=schema,
        )
        logger.info("DB adapter: PostgreSQL @ %s:%s/%s (schema=%s)", host, port, database, schema)

    else:
        raise ValueError(
            f"Unsupported DB_TYPE={db_type!r}. "
            "Set DB_TYPE to 'mysql' or 'postgresql' in .env."
        )

    return _adapter


def reset_adapter() -> None:
    """Discard the cached adapter (forces re-creation on next call)."""
    global _adapter
    _adapter = None
