"""Inspect the live database schema to discover foreign key relationships."""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# MySQL: reads from INFORMATION_SCHEMA in the current database
_MYSQL_FK_QUERY = """
    SELECT
        TABLE_NAME            AS left_table,
        COLUMN_NAME           AS left_key,
        REFERENCED_TABLE_NAME AS right_table,
        REFERENCED_COLUMN_NAME AS right_key
    FROM INFORMATION_SCHEMA.KEY_COLUMN_USAGE
    WHERE REFERENCED_TABLE_NAME IS NOT NULL
      AND TABLE_SCHEMA = DATABASE()
    ORDER BY TABLE_NAME, COLUMN_NAME
"""

# PostgreSQL: joins table_constraints → key_column_usage → constraint_column_usage
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
      AND tc.table_schema NOT IN ('pg_catalog', 'information_schema')
    ORDER BY tc.table_name, kcu.column_name
"""


def discover_fk_relationships() -> list[dict]:
    """Query the live DB for declared FK constraints and return them as relationship dicts.

    Returns an empty list (with a warning log) if the DB is unreachable or the
    query fails, so callers can fall back to the existing relationships.json.
    """
    from db.factory import get_adapter

    adapter = get_adapter()
    query = _PG_FK_QUERY if adapter.dialect_name == "postgresql" else _MYSQL_FK_QUERY

    try:
        rows = adapter.execute(query)
    except Exception as exc:
        logger.warning("FK discovery query failed (%s): %s", adapter.dialect_name, exc)
        return []

    discovered = [
        {
            "left_table":  row["left_table"],
            "right_table": row["right_table"],
            "left_key":    row["left_key"],
            "right_key":   row["right_key"],
            "join_type":   "INNER",  # FK-backed relationships default to INNER JOIN
        }
        for row in rows
    ]
    logger.info("FK discovery: found %d constraint(s) in %s", len(discovered), adapter.dialect_name)
    return discovered
