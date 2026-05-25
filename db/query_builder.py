"""Chainable, dialect-aware SQL query builder for MySQL and PostgreSQL.

Produces parameterized SELECT queries using :named placeholders compatible
with SQLAlchemy text() and every supported database dialect.

Basic usage:
    sql, params = (
        QueryBuilder("products")
        .select("name", "category", "price")
        .where("category = :cat", cat="Electronics")
        .order_by("price", desc=True)
        .limit(10)
        .build()
    )

JOIN + aggregation:
    results = (
        QueryBuilder("sales s")
        .select("p.name")
        .sum("s.amount", alias="revenue")
        .count("*",      alias="transactions")
        .inner_join("products p", on="s.product_id = p.product_id")
        .where(f"{QueryBuilder.month_of('s.sale_date')} = :m", m=5)
        .group_by("p.product_id", "p.name")
        .having("SUM(s.amount) > :min", min=1000)
        .order_by("revenue", desc=True)
        .limit(5)
        .execute()
    )

Pagination:
    results = (
        QueryBuilder("employees")
        .select("name", "department", "role")
        .order_by("name")
        .paginate(page=2, page_size=20)
        .execute()
    )
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_VALID_JOIN_TYPES = {"INNER", "LEFT", "RIGHT", "LEFT OUTER", "RIGHT OUTER"}


class QueryBuilder:
    """Chainable SELECT query builder — dialect-agnostic, safe parameterization."""

    def __init__(self, table: str):
        """
        Args:
            table: Table name with optional alias, e.g. ``'sales s'`` or ``'sales AS s'``.
        """
        self._table      = table
        self._selects:   list[str]       = []
        self._joins:     list[str]       = []
        self._wheres:    list[str]       = []
        self._group_bys: list[str]       = []
        self._havings:   list[str]       = []
        self._order_bys: list[str]       = []
        self._limit_val:  int | None     = None
        self._offset_val: int | None     = None
        self._params:    dict[str, Any]  = {}

    # ── Column selection ───────────────────────────────────────────────────────

    def select(self, *columns: str) -> "QueryBuilder":
        """Add one or more columns / expressions to SELECT.

        Accepts raw expressions such as ``'SUM(amount) AS total'`` or
        ``'DISTINCT category'``.
        """
        self._selects.extend(columns)
        return self

    # ── Aggregation helpers ────────────────────────────────────────────────────

    def count(self, column: str = "*", alias: str | None = None) -> "QueryBuilder":
        """Add ``COUNT(column) [AS alias]`` to SELECT."""
        expr = f"COUNT({column})"
        self._selects.append(f"{expr} AS {alias}" if alias else expr)
        return self

    def sum(self, column: str, alias: str | None = None) -> "QueryBuilder":
        """Add ``SUM(column) [AS alias]`` to SELECT."""
        expr = f"SUM({column})"
        self._selects.append(f"{expr} AS {alias}" if alias else expr)
        return self

    def avg(self, column: str, alias: str | None = None) -> "QueryBuilder":
        """Add ``AVG(column) [AS alias]`` to SELECT."""
        expr = f"AVG({column})"
        self._selects.append(f"{expr} AS {alias}" if alias else expr)
        return self

    def min(self, column: str, alias: str | None = None) -> "QueryBuilder":
        """Add ``MIN(column) [AS alias]`` to SELECT."""
        expr = f"MIN({column})"
        self._selects.append(f"{expr} AS {alias}" if alias else expr)
        return self

    def max(self, column: str, alias: str | None = None) -> "QueryBuilder":
        """Add ``MAX(column) [AS alias]`` to SELECT."""
        expr = f"MAX({column})"
        self._selects.append(f"{expr} AS {alias}" if alias else expr)
        return self

    # ── JOINs ─────────────────────────────────────────────────────────────────

    def join(self, table: str, on: str, join_type: str = "INNER") -> "QueryBuilder":
        """Add a JOIN clause.

        Args:
            table:     Table name with optional alias, e.g. ``'products p'``.
            on:        JOIN condition, e.g. ``'s.product_id = p.product_id'``.
            join_type: ``'INNER'`` | ``'LEFT'`` | ``'RIGHT'`` (default ``'INNER'``).
        """
        jt = join_type.upper().strip()
        if jt not in _VALID_JOIN_TYPES:
            raise ValueError(
                f"Unsupported join_type={jt!r}. Choose INNER, LEFT, or RIGHT."
            )
        self._joins.append(f"{jt} JOIN {table} ON {on}")
        return self

    def inner_join(self, table: str, on: str) -> "QueryBuilder":
        """Shorthand for ``join(..., join_type='INNER')``."""
        return self.join(table, on, "INNER")

    def left_join(self, table: str, on: str) -> "QueryBuilder":
        """Shorthand for ``join(..., join_type='LEFT')``."""
        return self.join(table, on, "LEFT")

    def right_join(self, table: str, on: str) -> "QueryBuilder":
        """Shorthand for ``join(..., join_type='RIGHT')``."""
        return self.join(table, on, "RIGHT")

    # ── Filtering ─────────────────────────────────────────────────────────────

    def where(self, condition: str, **params: Any) -> "QueryBuilder":
        """Add a WHERE condition (multiple calls are combined with AND).

        Args:
            condition: SQL predicate using ``:name`` placeholders,
                       e.g. ``'role = :role AND department = :dept'``.
            **params:  Values for the placeholders, e.g. ``role='admin'``.
        """
        self._wheres.append(condition)
        self._params.update(params)
        return self

    # ── Grouping ──────────────────────────────────────────────────────────────

    def group_by(self, *columns: str) -> "QueryBuilder":
        """Add one or more GROUP BY columns."""
        self._group_bys.extend(columns)
        return self

    def having(self, condition: str, **params: Any) -> "QueryBuilder":
        """Add a HAVING condition (multiple calls combined with AND).

        Args:
            condition: Aggregate predicate, e.g. ``'SUM(amount) > :min'``.
            **params:  Values for the placeholders.
        """
        self._havings.append(condition)
        self._params.update(params)
        return self

    # ── Sorting ───────────────────────────────────────────────────────────────

    def order_by(self, column: str, desc: bool = False) -> "QueryBuilder":
        """Add an ORDER BY expression.

        Args:
            column: Column name or expression. May include ``ASC``/``DESC``
                    directly (e.g. ``'revenue DESC'``), in which case the
                    ``desc`` flag is ignored.
            desc:   If ``True`` and ``column`` has no direction suffix, appends DESC.
        """
        col   = column.strip()
        upper = col.upper()
        if "DESC" in upper or "ASC" in upper:
            self._order_bys.append(col)
        else:
            self._order_bys.append(f"{col} DESC" if desc else col)
        return self

    # ── Pagination ────────────────────────────────────────────────────────────

    def limit(self, n: int) -> "QueryBuilder":
        """Set the maximum number of rows to return."""
        self._limit_val = int(n)
        return self

    def offset(self, n: int) -> "QueryBuilder":
        """Set the number of rows to skip."""
        self._offset_val = int(n)
        return self

    def paginate(self, page: int, page_size: int) -> "QueryBuilder":
        """Convenience: set LIMIT and OFFSET for a 1-based page number.

        Args:
            page:      1-based page index.
            page_size: Number of rows per page.
        """
        if page < 1:
            raise ValueError(f"page must be >= 1, got {page}")
        self._limit_val  = int(page_size)
        self._offset_val = (page - 1) * int(page_size)
        return self

    # ── Dialect-aware date helpers (static) ────────────────────────────────────

    @staticmethod
    def month_of(column: str) -> str:
        """Return a dialect-correct MONTH extraction expression.

        MySQL:      ``MONTH(column)``
        PostgreSQL: ``EXTRACT(MONTH FROM column)``
        """
        from db.factory import get_adapter
        return get_adapter().date_functions["month_extract"].format(col=column)

    @staticmethod
    def year_of(column: str) -> str:
        """Return a dialect-correct YEAR extraction expression."""
        from db.factory import get_adapter
        return get_adapter().date_functions["year_extract"].format(col=column)

    @staticmethod
    def current_date() -> str:
        """Return the dialect-correct current date keyword/function.

        MySQL: ``CURDATE()``  |  PostgreSQL: ``CURRENT_DATE``
        """
        from db.factory import get_adapter
        return get_adapter().date_functions["current_date"]

    @staticmethod
    def current_timestamp() -> str:
        """Return the dialect-correct current timestamp function.

        Both dialects: ``NOW()``
        """
        from db.factory import get_adapter
        return get_adapter().date_functions["current_timestamp"]

    @staticmethod
    def date_sub_days(n: int) -> str:
        """Return a dialect-correct expression for (today − n days).

        MySQL:      ``DATE_SUB(CURDATE(), INTERVAL n DAY)``
        PostgreSQL: ``(CURRENT_DATE - INTERVAL 'n days')``
        """
        from db.factory import get_adapter
        return get_adapter().date_functions["date_sub_days"].format(n=n)

    @staticmethod
    def date_trunc_month(column: str) -> str:
        """Return a dialect-correct month-start truncation expression.

        MySQL:      ``DATE_FORMAT(column, '%Y-%m-01')``
        PostgreSQL: ``DATE_TRUNC('month', column)``
        """
        from db.factory import get_adapter
        return get_adapter().date_functions["date_trunc_month"].format(col=column)

    # ── Build & execute ────────────────────────────────────────────────────────

    def build(self) -> tuple[str, dict]:
        """Compile all clauses into a SQL string and return ``(sql, params)``.

        Returns:
            A tuple of ``(sql_string, params_dict)`` ready to pass to
            ``adapter.execute()`` or ``sqlalchemy.text()``.
        """
        select_clause = ", ".join(self._selects) if self._selects else "*"
        parts: list[str] = [
            f"SELECT {select_clause}",
            f"FROM {self._table}",
        ]

        parts.extend(self._joins)

        if self._wheres:
            parts.append("WHERE " + " AND ".join(f"({c})" for c in self._wheres))

        if self._group_bys:
            parts.append("GROUP BY " + ", ".join(self._group_bys))

        if self._havings:
            parts.append("HAVING " + " AND ".join(f"({c})" for c in self._havings))

        if self._order_bys:
            parts.append("ORDER BY " + ", ".join(self._order_bys))

        if self._limit_val is not None:
            parts.append(f"LIMIT {self._limit_val}")

        if self._offset_val is not None:
            parts.append(f"OFFSET {self._offset_val}")

        sql = "\n".join(parts)
        logger.debug("QueryBuilder SQL: %s | params=%s", sql.replace("\n", " "), self._params)
        return sql, dict(self._params)

    def execute(self) -> list[dict]:
        """Build and immediately execute the query via the active database adapter.

        Returns:
            A list of row dicts with JSON-serializable values.
        """
        from db.factory import get_adapter
        sql, params = self.build()
        return get_adapter().execute(sql, params)
