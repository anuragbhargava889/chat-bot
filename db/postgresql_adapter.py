"""PostgreSQL adapter — uses postgresql+psycopg2 SQLAlchemy driver."""
from __future__ import annotations

from urllib.parse import quote_plus

from .adapter import DatabaseAdapter


class PostgreSQLAdapter(DatabaseAdapter):
    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        database: str,
        schema: str | None = None,
        **_,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database
        self.schema = schema

    def get_uri(self) -> str:
        uri = (
            f"postgresql+psycopg2://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.database}"
        )
        if self.schema:
            uri += f"?options=-csearch_path%3D{self.schema}"
        return uri

    @property
    def dialect_name(self) -> str:
        return "postgresql"

    @property
    def date_functions(self) -> dict:
        return {
            "current_date":      "CURRENT_DATE",
            "current_timestamp": "NOW()",
            "month_extract":     "EXTRACT(MONTH FROM {col})",
            "year_extract":      "EXTRACT(YEAR FROM {col})",
            "date_sub_days":     "(CURRENT_DATE - INTERVAL '{n} days')",
            "date_trunc_month":  "DATE_TRUNC('month', {col})",
        }
