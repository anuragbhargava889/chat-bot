"""Central configuration — reads .env and JSON config files."""
from __future__ import annotations

import json
import os

from dotenv import load_dotenv

load_dotenv()

# ── Database ───────────────────────────────────────────────────────────────────
# DB_TYPE controls which adapter is instantiated (mysql | postgresql).
# All credentials live in .env; structural settings live in config/database.json.
DB_TYPE: str = os.getenv("DB_TYPE", "mysql").lower()

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")


def _load_json(filename: str) -> dict:
    with open(os.path.join(_CONFIG_DIR, filename)) as fh:
        return json.load(fh)


# Pool settings are read once at import so the adapter can use them.
try:
    _DB_POOL_CONFIG: dict = _load_json("database.json")
except FileNotFoundError:
    _DB_POOL_CONFIG = {}


def get_table_config() -> dict:
    """Return logical-name → actual-table-name mapping from tables.json."""
    try:
        return _load_json("tables.json")
    except FileNotFoundError:
        # Backward-compatible defaults if the file is missing
        return {
            "employees":      "employees",
            "products":       "products",
            "sales":          "sales",
            "attendance":     "attendance",
            "stock_movement": "tstock_movement",
            "user_stock":     "tuser_stock",
        }


def get_relationship_config() -> dict:
    """Return the relationship/join configuration from relationships.json."""
    try:
        return _load_json("relationships.json")
    except FileNotFoundError:
        return {"relationships": []}


def sync_relationships() -> dict:
    """Merge FK-discovered relationships with manual entries and persist to relationships.json.

    Merge rules:
      - FK relationships discovered from INFORMATION_SCHEMA are always included.
      - If a discovered FK already exists in relationships.json, the file version
        wins (preserves any custom join_type the user has set).
      - Manual entries (not backed by a FK constraint) are preserved unchanged.

    Returns the merged relationship config dict.
    """
    import logging
    _log = logging.getLogger(__name__)

    from db.schema_inspector import discover_fk_relationships

    existing = get_relationship_config().get("relationships", [])
    # Index existing by the four-tuple that uniquely identifies a relationship
    existing_index = {
        (r["left_table"], r["left_key"], r["right_table"], r["right_key"]): r
        for r in existing
    }

    discovered = discover_fk_relationships()
    discovered_keys = {
        (r["left_table"], r["left_key"], r["right_table"], r["right_key"])
        for r in discovered
    }

    merged: list[dict] = []
    seen:   set[tuple] = set()

    # 1. FK-discovered relationships — use the existing entry if present so that
    #    a user-customised join_type (e.g. LEFT instead of INNER) is not overwritten.
    for rel in discovered:
        key = (rel["left_table"], rel["left_key"], rel["right_table"], rel["right_key"])
        merged.append(existing_index.get(key, rel))
        seen.add(key)

    # 2. Manual / logical relationships (no matching FK in the schema) — kept as-is.
    for rel in existing:
        key = (rel["left_table"], rel["left_key"], rel["right_table"], rel["right_key"])
        if key not in seen:
            merged.append(rel)
            seen.add(key)

    n_auto   = len(discovered)
    n_manual = len(merged) - n_auto
    _log.info(
        "Relationships synced: %d FK-auto + %d manual = %d total",
        n_auto, n_manual, len(merged),
    )

    result = {"relationships": merged}
    config_path = os.path.join(_CONFIG_DIR, "relationships.json")
    with open(config_path, "w") as fh:
        json.dump(result, fh, indent=2)

    return result


def get_db_uri() -> str:
    """SQLAlchemy connection URI for the configured database type."""
    from db.factory import get_adapter
    return get_adapter().get_uri()


def get_dialect_hints() -> str:
    """Return SQL date-function syntax hints for the active database dialect."""
    from db.factory import get_adapter
    fns = get_adapter().date_functions
    if DB_TYPE in ("postgresql", "postgres", "pg"):
        return (
            f"Date functions: EXTRACT(MONTH FROM col), EXTRACT(YEAR FROM col), "
            f"CURRENT_DATE, NOW(), DATE_TRUNC('month', col), "
            f"(CURRENT_DATE - INTERVAL '7 days')."
        )
    return (
        "Date functions: MONTH(col), YEAR(col), CURDATE(), NOW(), "
        "DATE_SUB(CURDATE(), INTERVAL N DAY), DATE_FORMAT(col, '%Y-%m')."
    )


# ── Currency ──────────────────────────────────────────────────────────────────
CURRENCY_SYMBOL: str = os.getenv("CURRENCY_SYMBOL", "$")

# ── Paths ──────────────────────────────────────────────────────────────────────
PDF_DIR   = os.getenv("PDF_DIR",   os.path.join(os.path.dirname(__file__), "pdfs"))
CHROMA_DIR = os.getenv("CHROMA_DIR", os.path.join(os.path.dirname(__file__), "chroma_db"))
SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key-in-production")

# ── LLM ───────────────────────────────────────────────────────────────────────
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
LLM_MODEL    = os.getenv("LLM_MODEL",    "llama3.1")
LLM_API_KEY  = os.getenv("LLM_API_KEY",  "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "")


def get_llm():
    """Return a LangChain chat model based on LLM_PROVIDER in .env."""
    provider = LLM_PROVIDER.lower()

    if provider == "ollama":
        base_url = LLM_BASE_URL or os.getenv("OLLAMA_HOST", "http://localhost:11434")
        from langchain_ollama import ChatOllama
        return ChatOllama(model=LLM_MODEL, base_url=base_url, temperature=0)

    if provider == "openai":
        from langchain_openai import ChatOpenAI
        kwargs = dict(model=LLM_MODEL, api_key=LLM_API_KEY, temperature=0)
        if LLM_BASE_URL:
            kwargs["base_url"] = LLM_BASE_URL
        return ChatOpenAI(**kwargs)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=LLM_MODEL, api_key=LLM_API_KEY, temperature=0)

    if provider == "groq":
        from langchain_groq import ChatGroq
        return ChatGroq(model=LLM_MODEL, api_key=LLM_API_KEY, temperature=0)

    raise ValueError(
        f"Unsupported LLM_PROVIDER={provider!r}. "
        "Choose one of: ollama, openai, anthropic, groq"
    )
