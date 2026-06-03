"""Central configuration — reads .env and JSON config files."""
from __future__ import annotations

import json
import logging
import os

from dotenv import load_dotenv

load_dotenv()

_log = logging.getLogger(__name__)

# ── Database ───────────────────────────────────────────────────────────────────
# DB_TYPE is kept only as a fallback for installations without databases.json.
# New setups declare type inside databases.json — DB_TYPE is not needed there.
DB_TYPE: str = os.getenv("DB_TYPE", "").lower()

_CONFIG_DIR = os.path.join(os.path.dirname(__file__), "config")


def _load_json(filename: str):
    with open(os.path.join(_CONFIG_DIR, filename)) as fh:
        return json.load(fh)


def _save_json(filename: str, data) -> None:
    with open(os.path.join(_CONFIG_DIR, filename), "w") as fh:
        json.dump(data, fh, indent=2)


# Pool settings read once at import so the adapter can use them.
try:
    _DB_POOL_CONFIG: dict = _load_json("database.json")
except FileNotFoundError:
    _DB_POOL_CONFIG = {}


# ── Multi-DB config ────────────────────────────────────────────────────────────

def get_databases_config() -> list[dict]:
    """Return list of database entries from config/databases.json.

    Falls back to a single-entry list built from legacy DB_* env vars when the
    file does not exist, so old single-DB setups keep working unchanged.
    """
    try:
        return _load_json("databases.json").get("databases", [])
    except FileNotFoundError:
        # Legacy fallback: single DB from DB_TYPE + DB_* env vars.
        db_type = os.getenv("DB_TYPE", "mysql").lower() or "mysql"
        return [{
            "name":        "main_db",
            "type":        db_type,
            "env_prefix":  "DB",
            "description": "Main database",
        }]


def _db_dir(db_name: str) -> str:
    return os.path.join(_CONFIG_DIR, "dbs", db_name)


def _load_db_json(db_name: str, filename: str):
    with open(os.path.join(_db_dir(db_name), filename)) as fh:
        return json.load(fh)


def _save_db_json(db_name: str, filename: str, data) -> None:
    db_path = _db_dir(db_name)
    os.makedirs(db_path, exist_ok=True)
    with open(os.path.join(db_path, filename), "w") as fh:
        json.dump(data, fh, indent=2)


def get_db_tables(db_name: str) -> dict:
    """Return logical→actual table/collection mapping for a database.

    Tries tables.json first (SQL), then collections.json (MongoDB).
    """
    for fname in ("tables.json", "collections.json"):
        try:
            return _load_db_json(db_name, fname)
        except FileNotFoundError:
            continue
    return {}


def get_db_columns(db_name: str) -> dict:
    """Return optional column/field hints for a database (auto-generated)."""
    for fname in ("table_columns.json", "collection_columns.json"):
        try:
            return _load_db_json(db_name, fname)
        except FileNotFoundError:
            continue
    return {}


def get_db_relationships(db_name: str) -> list:
    """Return relationship/JOIN list for a SQL database."""
    try:
        data = _load_db_json(db_name, "relationships.json")
        return data.get("relationships", []) if isinstance(data, dict) else []
    except FileNotFoundError:
        return []


# ── Schema sync ────────────────────────────────────────────────────────────────

def sync_db_schema(db_cfg: dict) -> dict:
    """Sync table_columns and relationships for one database.

    SQL  → discovers columns from INFORMATION_SCHEMA; discovers FK relationships
           and hybrid-merges with any manual entries in relationships.json.
    Mongo→ samples documents to infer field names; no FK discovery.

    Returns a summary dict with counts.
    """
    from db.schema_inspector import (
        discover_columns_sql,
        discover_columns_mongo,
        discover_fk_for_adapter,
    )

    db_name = db_cfg["name"]
    db_type = db_cfg["type"].lower()
    tables  = get_db_tables(db_name)

    if db_type in ("mysql", "postgresql", "postgres", "pg"):
        from db.factory import build_adapter_for
        adapter = build_adapter_for(db_cfg)

        # ── column hints (fully auto) ──────────────────────────────────────
        raw_cols = discover_columns_sql(adapter, list(tables.values()))
        logical_cols = {
            logical: raw_cols[actual]
            for logical, actual in tables.items()
            if actual in raw_cols
        }
        _save_db_json(db_name, "table_columns.json", logical_cols)
        _log.info("Synced columns for %s: %d table(s)", db_name, len(logical_cols))

        # ── relationships (hybrid merge) ──────────────────────────────────
        existing = get_db_relationships(db_name)
        existing_idx = {
            (r["left_table"], r["left_key"], r["right_table"], r["right_key"]): r
            for r in existing
        }
        discovered = discover_fk_for_adapter(adapter)
        merged: list[dict] = []
        seen:   set[tuple] = set()
        for rel in discovered:
            key = (rel["left_table"], rel["left_key"], rel["right_table"], rel["right_key"])
            merged.append(existing_idx.get(key, rel))
            seen.add(key)
        for rel in existing:
            key = (rel["left_table"], rel["left_key"], rel["right_table"], rel["right_key"])
            if key not in seen:
                merged.append(rel)
                seen.add(key)
        _save_db_json(db_name, "relationships.json", {"relationships": merged})
        _log.info("Synced relationships for %s: %d total", db_name, len(merged))
        return {"tables": len(tables), "relationships": len(merged)}

    if db_type == "mongodb":
        from db.factory import build_mongo_client
        client   = build_mongo_client(db_cfg)
        mdb_name = os.getenv(f"{db_cfg['env_prefix']}_NAME", "")
        col_hints = discover_columns_mongo(client, mdb_name, tables)
        _save_db_json(db_name, "collection_columns.json", col_hints)
        _log.info("Synced fields for %s: %d collection(s)", db_name, len(col_hints))
        return {"collections": len(tables)}

    _log.warning("sync_db_schema: unknown type %r for %s", db_type, db_name)
    return {}


def sync_all_db_schemas() -> None:
    """Sync columns and relationships for every database in databases.json."""
    for cfg in get_databases_config():
        try:
            result = sync_db_schema(cfg)
            _log.info("Schema sync OK — %s: %s", cfg["name"], result)
        except Exception as exc:
            _log.warning("Schema sync skipped for %s: %s", cfg["name"], exc)


# ── Legacy single-DB helpers (kept for database.py / schema_inspector compat) ──

def get_table_config() -> dict:
    """Return table mapping for the primary database (first entry in databases.json).

    Reads from config/dbs/<name>/tables.json; falls back to flat config/tables.json
    for installations that have not yet migrated.
    """
    dbs = get_databases_config()
    if dbs:
        tables = get_db_tables(dbs[0]["name"])
        if tables:
            return tables
    # flat-file fallback
    try:
        return _load_json("tables.json")
    except FileNotFoundError:
        raise FileNotFoundError(
            "No table configuration found. "
            "Create config/databases.json + config/dbs/<name>/tables.json "
            "or the legacy config/tables.json."
        )


def get_local_users() -> list[dict]:
    """Return users from config/users.json (fallback auth when no employees table)."""
    try:
        return _load_json("users.json")
    except FileNotFoundError:
        return []


def get_column_hints() -> dict:
    """Return column hints for the primary database."""
    dbs = get_databases_config()
    if dbs:
        return get_db_columns(dbs[0]["name"])
    try:
        return _load_json("table_columns.json")
    except FileNotFoundError:
        return {}


def get_relationship_config() -> dict:
    """Return relationships for the primary database."""
    dbs = get_databases_config()
    if dbs:
        return {"relationships": get_db_relationships(dbs[0]["name"])}
    try:
        return _load_json("relationships.json")
    except FileNotFoundError:
        return {"relationships": []}


def sync_relationships() -> dict:
    """Legacy single-DB relationship sync — delegates to sync_db_schema."""
    dbs = get_databases_config()
    if not dbs:
        return {"relationships": []}
    cfg = dbs[0]
    db_type = cfg["type"].lower()
    if db_type not in ("mysql", "postgresql", "postgres", "pg"):
        return {"relationships": []}
    sync_db_schema(cfg)
    return {"relationships": get_db_relationships(cfg["name"])}


# ── URI / dialect helpers ──────────────────────────────────────────────────────

def get_db_uri() -> str:
    """SQLAlchemy URI for the primary (legacy) database."""
    from db.factory import get_adapter
    return get_adapter().get_uri()


def get_dialect_hints() -> str:
    """SQL date-function syntax hints derived from databases.json (not DB_TYPE env var)."""
    sql_types = {
        cfg["type"].lower()
        for cfg in get_databases_config()
        if cfg["type"].lower() != "mongodb"
    }
    pg = sql_types & {"postgresql", "postgres", "pg"}
    my = sql_types & {"mysql"}
    if pg and my:
        return (
            "MySQL: MONTH(col), YEAR(col), CURDATE(), NOW(), DATE_SUB(CURDATE(), INTERVAL N DAY). "
            "PostgreSQL: EXTRACT(MONTH FROM col), EXTRACT(YEAR FROM col), CURRENT_DATE, NOW(), "
            "DATE_TRUNC('month', col), (CURRENT_DATE - INTERVAL '7 days')."
        )
    if pg:
        return (
            "Date functions: EXTRACT(MONTH FROM col), EXTRACT(YEAR FROM col), "
            "CURRENT_DATE, NOW(), DATE_TRUNC('month', col), "
            "(CURRENT_DATE - INTERVAL '7 days')."
        )
    return (
        "Date functions: MONTH(col), YEAR(col), CURDATE(), NOW(), "
        "DATE_SUB(CURDATE(), INTERVAL N DAY), DATE_FORMAT(col, '%Y-%m')."
    )


# ── Currency / paths ───────────────────────────────────────────────────────────
CURRENCY_SYMBOL: str = os.getenv("CURRENCY_SYMBOL", "$")
PDF_DIR    = os.getenv("PDF_DIR",    os.path.join(os.path.dirname(__file__), "pdfs"))
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
