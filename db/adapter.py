"""Abstract database adapter — all concrete adapters extend this class."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


class DatabaseAdapter(ABC):
    """Provider-agnostic interface for database operations.

    Concrete subclasses implement get_uri() and expose dialect-specific
    metadata (date_functions, dialect_name).  All query execution goes
    through execute() / execute_write() which use SQLAlchemy text() with
    named :param placeholders — compatible with every supported dialect.
    """

    _engine = None

    # ── Abstract interface ──────────────────────────────────────────────────

    @abstractmethod
    def get_uri(self) -> str:
        """Return a fully-qualified SQLAlchemy connection URI."""

    @property
    @abstractmethod
    def dialect_name(self) -> str:
        """Short dialect identifier, e.g. 'mysql' or 'postgresql'."""

    @property
    @abstractmethod
    def date_functions(self) -> dict:
        """Dialect-specific date/time function templates used for LLM hints."""

    # ── Engine (lazy singleton) ─────────────────────────────────────────────

    def get_engine(self):
        if self._engine is None:
            try:
                from config import _DB_POOL_CONFIG as _pool
            except ImportError:
                _pool = {}

            self._engine = create_engine(
                self.get_uri(),
                pool_size=_pool.get("pool_size", 5),
                max_overflow=_pool.get("max_overflow", 10),
                pool_recycle=_pool.get("pool_recycle", 1800),
                pool_timeout=_pool.get("pool_timeout", 30),
            )
            logger.info("DB engine created: dialect=%s", self.dialect_name)
        return self._engine

    # ── Query helpers ───────────────────────────────────────────────────────

    def execute(self, query: str, params: dict | None = None) -> list[dict]:
        """Run a SELECT and return a list of sanitized row dicts."""
        logger.debug("SQL execute | %s | params=%s", query.strip(), params)
        try:
            with self.get_engine().connect() as conn:
                result = conn.execute(text(query), params or {})
                rows = [dict(row._mapping) for row in result]
                return self._sanitize(rows)
        except SQLAlchemyError as exc:
            logger.error("Query failed: %s", exc)
            raise

    def execute_write(self, query: str, params: dict | None = None) -> None:
        """Run an INSERT/UPDATE/DELETE inside an auto-committed transaction."""
        logger.debug("SQL write | %s | params=%s", query.strip(), params)
        try:
            with self.get_engine().begin() as conn:
                conn.execute(text(query), params or {})
        except SQLAlchemyError as exc:
            logger.error("Write failed: %s", exc)
            raise

    # ── Serialisation helpers ───────────────────────────────────────────────

    @staticmethod
    def _sanitize(rows: list[dict]) -> list[dict]:
        """Convert non-JSON-serialisable DB types to strings/floats."""
        for row in rows:
            for k, v in row.items():
                if isinstance(v, Decimal):
                    row[k] = float(v)
                elif isinstance(v, (date, datetime)):
                    row[k] = str(v)
        return rows
