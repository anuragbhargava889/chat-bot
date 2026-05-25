"""MySQL adapter — uses mysql+mysqlconnector SQLAlchemy driver."""
from __future__ import annotations

from urllib.parse import quote_plus

from .adapter import DatabaseAdapter


class MySQLAdapter(DatabaseAdapter):
    def __init__(self, host: str, port: int, user: str, password: str, database: str, **_):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

    def get_uri(self) -> str:
        return (
            f"mysql+mysqlconnector://{quote_plus(self.user)}:{quote_plus(self.password)}"
            f"@{self.host}:{self.port}/{self.database}"
        )

    @property
    def dialect_name(self) -> str:
        return "mysql"

    @property
    def date_functions(self) -> dict:
        return {
            "current_date":      "CURDATE()",
            "current_timestamp": "NOW()",
            "month_extract":     "MONTH({col})",
            "year_extract":      "YEAR({col})",
            "date_sub_days":     "DATE_SUB(CURDATE(), INTERVAL {n} DAY)",
            "date_trunc_month":  "DATE_FORMAT({col}, '%Y-%m-01')",
        }
