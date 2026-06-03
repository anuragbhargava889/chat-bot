"""Inspect live database schemas to discover columns and foreign-key relationships.

SQL functions work with any DatabaseAdapter (MySQL or PostgreSQL).
MongoDB functions use a pymongo client and sample documents to infer field names.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# ── SQL queries ────────────────────────────────────────────────────────────────

_MYSQL_FK_QUERY = """
    SELECT
        TABLE_NAME             AS left_table,
        COLUMN_NAME            AS left_key,
        REFERENCED_TABLE_NAME  AS right_table,
        REFERENCED_COLUMN_NAME AS right_key
    FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
    WHERE REFERENCED_TABLE_NAME IS NOT NULL
      AND TABLE_SCHEMA = DATABASE()
    ORDER BY TABLE_NAME, COLUMN_NAME
"""

_PG_FK_QUERY = """
    SELECT
        tc.table_name   AS left_table,
        kcu.column_name AS left_key,
        ccu.table_name  AS right_table,
        ccu.column_name AS right_key
    FROM information_schema.table_constraints      tc
    JOIN information_schema.key_column_usage       kcu
         ON  tc.constraint_name = kcu.constraint_name
         AND tc.table_schema    = kcu.table_schema
    JOIN information_schema.constraint_column_usage ccu
         ON  ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema    = tc.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_schema = current_schema()
    ORDER BY tc.table_name, kcu.column_name
"""


# ── SQL column discovery ───────────────────────────────────────────────────────

def discover_columns_sql(adapter, table_names: list[str]) -> dict[str, str]:
    """Return {actual_table_name: "col1, col2, ..."} for the given tables.

    Queries INFORMATION_SCHEMA — works for MySQL and PostgreSQL.
    Returns an empty dict if the query fails or no tables are provided.
    """
    if not table_names:
        return {}

    quoted = ", ".join(f"'{t}'" for t in table_names)

    if adapter.dialect_name == "postgresql":
        query = f"""
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name IN ({quoted})
            ORDER BY table_name, ordinal_position
        """
    else:
        query = f"""
            SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME IN ({quoted})
            ORDER BY TABLE_NAME, ORDINAL_POSITION
        """

    try:
        rows = adapter.execute(query)
    except Exception as exc:
        logger.warning("Column discovery failed (%s): %s", adapter.dialect_name, exc)
        return {}

    result: dict[str, list[str]] = {}
    for row in rows:
        result.setdefault(row["table_name"], []).append(row["column_name"])

    return {tbl: ", ".join(cols) for tbl, cols in result.items()}


# ── SQL FK discovery ───────────────────────────────────────────────────────────

def discover_fk_for_adapter(adapter) -> list[dict]:
    """Discover FK relationships for a specific adapter instance.

    Returns an empty list (with a warning) if the DB is unreachable or the
    query fails, so callers can fall back to the existing relationships.json.
    """
    query = _PG_FK_QUERY if adapter.dialect_name == "postgresql" else _MYSQL_FK_QUERY
    try:
        rows = adapter.execute(query)
    except Exception as exc:
        logger.warning("FK discovery failed (%s): %s", adapter.dialect_name, exc)
        return []

    discovered = [
        {
            "left_table":  row["left_table"],
            "right_table": row["right_table"],
            "left_key":    row["left_key"],
            "right_key":   row["right_key"],
            "join_type":   "INNER",
        }
        for row in rows
    ]
    logger.info("FK discovery: %d constraint(s) in %s", len(discovered), adapter.dialect_name)
    return discovered


# ── MongoDB field discovery ────────────────────────────────────────────────────

def discover_columns_mongo(client, db_name: str, collections: dict) -> dict[str, str]:
    """Sample MongoDB documents to infer field names.

    Args:
        client:      pymongo MongoClient
        db_name:     MongoDB database name (from <PREFIX>_NAME env var)
        collections: logical→actual collection name mapping (from collections.json)

    Returns:
        {logical_key: "field1, field2, ..."} — keys match collections.json logical names.
        Nested fields use dot notation: "address.city".
    """
    result: dict[str, str] = {}
    mongo_db = client[db_name]

    for logical_key, actual_collection in collections.items():
        try:
            docs = list(mongo_db[actual_collection].find({}, {"_id": 0}).limit(20))
            fields: set[str] = set()
            for doc in docs:
                fields.update(_flatten_keys(doc))
            result[logical_key] = ", ".join(sorted(fields))
            logger.info(
                "Mongo field discovery: %s → %d field(s)", actual_collection, len(fields)
            )
        except Exception as exc:
            logger.warning("Mongo field sampling failed for %s: %s", actual_collection, exc)

    return result


def _flatten_keys(doc: dict, prefix: str = "") -> list[str]:
    """Recursively flatten nested dict keys using dot notation."""
    keys: list[str] = []
    for k, v in doc.items():
        full = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            keys.extend(_flatten_keys(v, full))
        else:
            keys.append(full)
    return keys


# ── Legacy wrapper (kept for backward compat) ──────────────────────────────────

def discover_fk_relationships() -> list[dict]:
    """Discover FK relationships using the primary (legacy) adapter.

    Kept for callers that import this function directly.
    New code should use discover_fk_for_adapter(adapter) instead.
    """
    from db.factory import get_adapter
    return discover_fk_for_adapter(get_adapter())
