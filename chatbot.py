"""Chatbot core — LangGraph ReAct agent with multi-database support.

Entry points:
  stream_message()  → NDJSON events (SSE endpoint)
  process_message() → dict (synchronous, kept for compatibility)

Tool naming convention (auto-generated per databases.json):
  query_<db_name>   — SELECT queries on a SQL database
  schema_<db_name>  — Column info for a SQL database
  query_<db_name>   — Aggregation pipeline queries on MongoDB
  search_pdf_library
  generate_chart
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from langchain_community.utilities import SQLDatabase
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool, tool
from langgraph.prebuilt import create_react_agent
from pydantic import BaseModel, field_validator

from config import (
    get_databases_config,
    get_db_columns,
    get_db_relationships,
    get_db_tables,
    get_llm,
    CURRENCY_SYMBOL,
)
from pdf_handler import query_pdfs

logger = logging.getLogger(__name__)


# ── Confidence tracker ─────────────────────────────────────────────────────────

class _ConfidenceTracker:
    def __init__(self):
        self._score:         float = 85.0
        self._empty_count:   int   = 0
        self._success_count: int   = 0

    def record_sql(self, result: str) -> None:
        r = result.strip()
        if r.startswith("Query error:") or r.startswith("Error:"):
            self._score -= 35
        elif not r or r in ("[]", "None", ""):
            self._empty_count += 1
            self._score -= 20
        else:
            self._success_count += 1
            self._score = min(98, self._score + 5)

    def record_pdf(self, result_json: str) -> None:
        try:
            res = json.loads(result_json)
            if res.get("found") and res.get("chunks"):
                avg_rel = sum(c.get("relevance", 0.5) for c in res["chunks"]) / len(res["chunks"])
                self._score = min(98, self._score + (avg_rel - 0.5) * 12)
                self._success_count += 1
            else:
                self._score -= 15
        except Exception:
            pass

    def record_tool_success(self, success: bool) -> None:
        if not success:
            self._score -= 10

    def get(self) -> int:
        score = self._score
        # Recover penalty for intermediate empty results when we ultimately got data.
        # Multi-step exploration (discovery query → real query) is normal agent behaviour;
        # penalising it the same as a final "no data" result misrepresents answer quality.
        if self._success_count > 0 and self._empty_count > 0:
            recovery = min(self._empty_count, self._success_count) * 15
            score = min(98, score + recovery)
        return round(max(10, min(98, score)))


# ── System prompt ──────────────────────────────────────────────────────────────

def _build_system(user_ctx: str) -> str:
    dbs = get_databases_config()

    db_sections: list[str] = []
    sql_types: set[str] = set()

    for cfg in dbs:
        db_name = cfg["name"]
        db_type = cfg["type"].lower()
        tables  = get_db_tables(db_name)
        cols    = get_db_columns(db_name)
        rels    = get_db_relationships(db_name)

        tbl_parts = [
            f"{actual}({cols[logical]})" if logical in cols else actual
            for logical, actual in tables.items()
        ]

        if db_type == "mongodb":
            lines = [
                f"  [{db_name}] MongoDB — {cfg['description']}",
                f"    Collections : {', '.join(tbl_parts) or '(none configured)'}",
                f"    Tool        : query_{db_name}  (aggregation pipeline JSON)",
            ]
        else:
            sql_types.add(db_type)
            dialect = "MySQL" if db_type == "mysql" else "PostgreSQL"
            rel_lines = [
                f"      {r['left_table']} {r['join_type']} JOIN {r['right_table']}"
                f" ON {r['left_table']}.{r['left_key']} = {r['right_table']}.{r['right_key']}"
                for r in rels
            ]
            lines = [
                f"  [{db_name}] {dialect} — {cfg['description']}",
                f"    Tables : {', '.join(tbl_parts) or '(none configured)'}",
            ]
            if rel_lines:
                lines.append("    JOINs  :\n" + "\n".join(rel_lines))
            lines.append(f"    Tools  : query_{db_name}, schema_{db_name}")

        db_sections.append("\n".join(lines))

    databases_str = "\n\n".join(db_sections) if db_sections else "  (no databases configured)"

    # Build date-function hint from actual DB types in databases.json, not from DB_TYPE env var.
    pg  = sql_types & {"postgresql", "postgres", "pg"}
    my  = sql_types & {"mysql"}
    if pg and my:
        date_hint = (
            "MySQL date functions: MONTH(col), YEAR(col), CURDATE(), NOW(), DATE_SUB(CURDATE(), INTERVAL N DAY). "
            "PostgreSQL date functions: EXTRACT(MONTH FROM col), EXTRACT(YEAR FROM col), CURRENT_DATE, NOW(), "
            "DATE_TRUNC('month', col), (CURRENT_DATE - INTERVAL '7 days'). "
            "Use the correct syntax for each database's query tool."
        )
    elif pg:
        date_hint = (
            "Date functions (PostgreSQL): EXTRACT(MONTH FROM col), EXTRACT(YEAR FROM col), "
            "CURRENT_DATE, NOW(), DATE_TRUNC('month', col), (CURRENT_DATE - INTERVAL '7 days')."
        )
    elif my:
        date_hint = (
            "Date functions (MySQL): MONTH(col), YEAR(col), CURDATE(), NOW(), "
            "DATE_SUB(CURDATE(), INTERVAL N DAY), DATE_FORMAT(col, '%Y-%m')."
        )
    else:
        date_hint = ""

    today = datetime.now().strftime("%Y-%m-%d")

    return f"""You are a company assistant with access to one or more databases and a PDF library.
Today's date: {today}

Databases:
{databases_str}

Rules:
1. Choose the query tool that matches the database description and the question.
   SQL  : Always include a LIMIT clause. SELECT/WITH only — never INSERT/UPDATE/DELETE/DROP.
   Mongo: Write an aggregation pipeline JSON array. Always include a $limit stage.
          Never use $out or $merge.
2. {date_hint}
3. MongoDB date fields — check the field description to know the storage format:
   - ISODate fields (e.g. daily_primary_vol.bill_date): use {{"$date":"YYYY-MM-DDTHH:MM:SSZ"}}
   - String date fields (e.g. tstock_movement.moved_date, tuser_stock.stock_date): use plain "YYYY-MM-DD" strings
   Date range rules — only add bounds that the question explicitly mentions:
     ISODate "in YYYY"        → {{"$gte":{{"$date":"YYYY-01-01T00:00:00Z"}},"$lt":{{"$date":"(YYYY+1)-01-01T00:00:00Z"}}}}
     ISODate "up to Mon YYYY" → {{"$lte":{{"$date":"YYYY-MM-last_dayT23:59:59Z"}}}}  ← NO lower bound unless stated
     ISODate "last 90 days"   → {{"$gte":{{"$date":"<today-90days>T00:00:00Z"}}}}
     String  "in YYYY"        → {{"$gte":"YYYY-01-01","$lt":"(YYYY+1)-01-01"}}
     String  "up to Mon YYYY" → {{"$lte":"YYYY-MM-last_day"}}                        ← NO lower bound unless stated
     String  "last 90 days"   → {{"$gte":"<today-90days as YYYY-MM-DD>"}}
4. Rankings : ORDER BY … LIMIT N (SQL) | $sort + $limit (Mongo).
   Summaries: GROUP BY + aggregates (SQL) | $group (Mongo).
5. Multi-table: use explicit JOINs for SQL; $lookup for MongoDB.
6. For PDF questions use search_pdf_library and cite the source.
7. For charts: call the query tool first, then generate_chart with the results.
8. Always use {CURRENCY_SYMBOL} for all monetary values.
9. String name matching: product/item names typed by users may differ from stored values
   in case or spacing (e.g. user types "lava fusion" but DB stores "LAVA_FUSION").
   Always use case- and separator-insensitive matching for name filters:
     SQL  : WHERE REPLACE(UPPER(col), '_', ' ') = UPPER('user value')
     Mongo: {{"$expr":{{"$eq":[{{"$toUpper":{{"$replaceAll":{{"input":"$field","find":"_","replacement":" "}}}}}},{{"$toUpper":"user value"}}]}}}}
   Never do a plain equality match like col = 'lava fusion' on name-like columns.
9b. Case-inconsistent grouping: text/categorical columns (e.g. colour, status, category,
   business_unit) often mix case in the raw data itself (e.g. "Black" and "BLACK" are the
   SAME value, stored inconsistently) — grouping on the raw field splits them into duplicate
   buckets. Always normalize case in GROUP BY / $group on text columns:
     SQL  : GROUP BY UPPER(col)   — and SELECT UPPER(col) AS col for the label
     Mongo: {{"$group":{{"_id":{{"$toUpper":"$field"}}, ...}}}}
   Numeric/code/date columns (dbr_code, quantity, dates) do not need this — only free-text
   categorical columns.
10. Column value discovery: when unsure how a value is stored, run one discovery query
   (SELECT DISTINCT col FROM tbl LIMIT 30 for SQL;
   [{{"$group":{{"_id":"$field"}}}},{{"$limit":30}}] for Mongo).
   Do this at most ONCE per column, then use the exact stored value.
11. Empty results: say "No data found for [topic]" and show the exact filter you used.
    Do NOT retry with a different filter, format, or field name. One attempt only.
12. Be concise.
13. Read-only assistant: if the user asks to insert, update, delete, remove, drop, modify,
    or otherwise change/write any data (e.g. "delete this order", "update the distributor
    name", "add a new record"), do NOT call any query tool — not even with SELECT-only
    stages as a workaround. Reply immediately with a short message stating that you are
    read-only and cannot modify data, and that changes must be made directly in the
    database. This applies even if the user insists or rephrases the request.

{user_ctx}"""


# ── Fallback suggestions ───────────────────────────────────────────────────────

_SUGGESTIONS = [
    "Show available tables and their structure",
    "Show total stock summary",
    "Show top 10 items by price as a bar chart",
    "Show stock movement trend as a line chart",
    "What stock items are available?",
]


# ── Attendance feature detection ───────────────────────────────────────────────

# ── SQLDatabase cache ──────────────────────────────────────────────────────────

_sql_dbs: dict[str, SQLDatabase] = {}


def _get_sql_dbs() -> dict[str, SQLDatabase]:
    """Return a {db_name: SQLDatabase} dict, creating instances lazily."""
    from db.factory import build_sql_uri_for

    for cfg in get_databases_config():
        db_type = cfg["type"].lower()
        if db_type not in ("mysql", "postgresql", "postgres", "pg"):
            continue
        name = cfg["name"]
        if name not in _sql_dbs:
            tables = get_db_tables(name)
            try:
                _sql_dbs[name] = SQLDatabase.from_uri(
                    build_sql_uri_for(cfg),
                    include_tables=list(tables.values()),
                    sample_rows_in_table_info=0,
                )
                logger.info("SQLDatabase ready: %s → %s", name, list(tables.values()))
            except Exception as exc:
                logger.warning("SQLDatabase init failed for %s: %s", name, exc)

    return _sql_dbs


def invalidate_sql_db_cache() -> None:
    """Discard cached SQLDatabase objects (call after schema sync)."""
    global _sql_dbs
    _sql_dbs = {}


# ── Result size cap ────────────────────────────────────────────────────────────

_SQL_MAX_CHARS = 20_000


def _enforce_limit(query: str, default: int = 200) -> str:
    """Append LIMIT {default} if the query has no LIMIT clause."""
    if "LIMIT" not in query.upper():
        return query.rstrip("; \n") + f" LIMIT {default}"
    return query


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return str(content) if content else ""


_SPECIAL_TOKENS = re.compile(r"<\|[a-zA-Z0-9_]+\|>")

def _clean(text: str) -> str:
    return _SPECIAL_TOKENS.sub("", text)


def _friendly_error(exc: Exception) -> str:
    s = str(exc)
    if "GraphRecursionError" in type(exc).__name__ or "Recursion limit" in s:
        return (
            "No data found. The query could not be completed — "
            "the requested information may not exist in the database, "
            "or the column values did not match. "
            "Try a more specific question or check the table schema."
        )
    if "AnthropicContextOverflowError" in type(exc).__name__ or "prompt is too long" in s:
        return (
            "The query returned too much data for the AI to process. "
            "Try a more specific query — add a date range filter or reduce the columns selected."
        )
    if "rate_limit_exceeded" in s or "429" in s:
        wait = re.search(r"try again in ([\w.]+)", s)
        wait_msg = f" Please try again in {wait.group(1)}." if wait else " Please try again shortly."
        return f"Rate limit reached for the AI model.{wait_msg}"
    if "failed_generation" in s or "Failed to call a function" in s:
        return "The model failed to generate a valid tool call. Try rephrasing or ask for simpler data."
    if "insufficient_quota" in s or "credit" in s.lower():
        return "API credits exhausted. Please top up your account or switch providers in .env."
    if "timeout" in s.lower() or "timed out" in s.lower():
        return "The request timed out — please try again."
    return f"Error: {exc}"


# ── Type coercions (Llama sends strings for bool/int/list) ─────────────────────

def _to_bool(v) -> bool:
    if isinstance(v, bool):
        return v
    return str(v).lower() in ("true", "1", "yes")

def _to_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except (ValueError, TypeError):
        return default

def _parse_list(v, cast=str) -> list:
    if isinstance(v, (list, tuple)):
        return [cast(x) for x in v]
    try:
        return [cast(x) for x in json.loads(v)]
    except (json.JSONDecodeError, TypeError, ValueError):
        parts = [x.strip().strip("\"'") for x in str(v).strip("[]").split(",")]
        return [cast(x) for x in parts if x]


# ── Pipeline helpers ──────────────────────────────────────────────────────────

def _convert_extended_json(obj):
    """Recursively convert Extended JSON {"$date":"ISO"} to Python datetime.

    json.loads() treats {"$date":"..."} as a plain dict; pymongo then sends it
    as a BSON sub-document instead of a Date, so date comparisons return nothing.
    This converts them to real datetime objects before the pipeline is executed.
    """
    if isinstance(obj, dict):
        if list(obj.keys()) == ["$date"] and isinstance(obj["$date"], str):
            try:
                return datetime.fromisoformat(obj["$date"].replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass
        return {k: _convert_extended_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_convert_extended_json(item) for item in obj]
    return obj


# ── Tool factory ───────────────────────────────────────────────────────────────

def _make_tools(user: dict | None) -> list:
    sql_dbs  = _get_sql_dbs()
    all_tools: list = []

    for cfg in get_databases_config():
        db_name = cfg["name"]
        db_type = cfg["type"].lower()
        desc    = cfg.get("description", db_name)

        # ── SQL database tools ─────────────────────────────────────────────
        if db_type in ("mysql", "postgresql", "postgres", "pg"):
            db = sql_dbs.get(db_name)
            if db is None:
                logger.warning("Skipping tools for %s — SQLDatabase not available", db_name)
                continue

            tables = get_db_tables(db_name)
            tables_str = ", ".join(tables.values())

            # query_{db_name}
            def _make_sql_query(db_=db, name_=db_name, desc_=desc, tables_str_=tables_str):
                @tool(f"query_{name_}", description=(
                    f"Execute a SQL SELECT on {name_} — {desc_}. "
                    f"Tables: {tables_str_}. "
                    "Always include LIMIT. SELECT/WITH only. "
                    "If the result is empty, report 'No data found' immediately. "
                    "Args: query — a valid SQL SELECT or WITH statement."
                ))
                def sql_query(query: str) -> str:
                    stripped = query.strip()
                    if not stripped.upper().startswith(("SELECT", "WITH")):
                        return "Error: This assistant is read-only — only SELECT and WITH queries are permitted. Data cannot be inserted, updated, or deleted."
                    bounded = _enforce_limit(stripped)
                    if bounded != stripped:
                        logger.info("query_%s: appended LIMIT 200", name_)
                    logger.info("query_%s: %s", name_, bounded[:200])
                    try:
                        result = db_.run(bounded)
                        if len(result) > _SQL_MAX_CHARS:
                            logger.warning("query_%s result truncated (%d chars)", name_, len(result))
                            result = (
                                result[:_SQL_MAX_CHARS]
                                + f"\n\n[Result truncated. Add a tighter LIMIT or date filter.]"
                            )
                        return result
                    except Exception as exc:
                        logger.warning("query_%s failed: %s", name_, exc)
                        return f"Query error: {exc}"
                return sql_query

            all_tools.append(_make_sql_query())

            # schema_{db_name}
            def _make_sql_schema(db_=db, name_=db_name):
                @tool(f"schema_{name_}", description=(
                    f"Get column definitions for tables in {name_}. "
                    "Call before writing queries on unfamiliar tables. "
                    "Args: table_names — comma-separated table names, or empty for all tables."
                ))
                def sql_schema(table_names: str = "") -> str:
                    if table_names.strip():
                        tbls = [t.strip() for t in table_names.split(",")]
                        return db_.get_table_info(tbls)
                    return db_.get_table_info()
                return sql_schema

            all_tools.append(_make_sql_schema())

        # ── MongoDB tools ──────────────────────────────────────────────────
        elif db_type == "mongodb":
            import os as _os
            collections = get_db_tables(db_name)
            allowed     = set(collections.values())
            mdb_name    = _os.getenv(f"{cfg['env_prefix']}_NAME", "")

            def _make_mongo_query(cfg_=cfg, name_=db_name, desc_=desc,
                                  allowed_=allowed, mdb_name_=mdb_name,
                                  collections_=collections):
                @tool(f"query_{name_}", description=(
                    f"Query MongoDB {name_} — {desc_} using an aggregation pipeline. "
                    f"Collections: {', '.join(collections_.values()) or '(none configured)'}. "
                    "Args: collection — collection name; "
                    "pipeline — JSON array e.g. [{\"$match\":{\"k\":\"v\"}},{\"$limit\":50}]. "
                    "Always include a $limit stage. No $out or $merge."
                ))
                def mongo_query(collection: str, pipeline: str = "[]") -> str:
                    if collection not in allowed_:
                        return (
                            f"Error: '{collection}' not available. "
                            f"Choose from: {', '.join(allowed_)}"
                        )
                    try:
                        pipe = _convert_extended_json(json.loads(pipeline))
                    except json.JSONDecodeError as e:
                        return f"Error: invalid pipeline JSON — {e}"

                    write_stages = {"$out", "$merge"}
                    if any(write_stages & set(stage) for stage in pipe):
                        return "Error: This assistant is read-only — $out and $merge are not permitted. Data cannot be inserted, updated, or deleted."
                    if not any("$limit" in stage for stage in pipe):
                        pipe.append({"$limit": 200})

                    try:
                        from db.factory import build_mongo_client
                        logger.info("query_%s on %s — pipeline: %s", name_, collection, pipeline[:600])
                        client = build_mongo_client(cfg_)
                        docs   = list(client[mdb_name_][collection].aggregate(pipe))
                        result = json.dumps(docs, default=str)
                        if len(result) > _SQL_MAX_CHARS:
                            logger.warning("query_%s result truncated (%d chars)", name_, len(result))
                            result = result[:_SQL_MAX_CHARS] + "\n\n[Result truncated.]"
                        logger.info("query_%s: %d doc(s) returned from %s", name_, len(docs), collection)
                        return result
                    except Exception as exc:
                        logger.warning("query_%s failed: %s", name_, exc)
                        return f"Query error: {exc}"

                return mongo_query

            all_tools.append(_make_mongo_query())

    # ── Shared tools ───────────────────────────────────────────────────────────

    @tool
    def search_pdf_library(question: str, top_k: str = "3") -> str:
        """Semantic search over company PDF documents.

        Use for questions about policies, procedures, warranties, product specs,
        HR rules, or any knowledge stored in uploaded documents.

        Args:
            question: Natural-language question to search for.
            top_k:    Number of document chunks to retrieve (default '3').
        """
        chunks = query_pdfs(question, top_k=_to_int(top_k, default=3))
        if not chunks:
            return json.dumps({"found": False, "message": "No relevant content found."})
        return json.dumps({
            "found": True,
            "chunks": [
                {"source": c["source"], "text": c["text"], "relevance": c["score"]}
                for c in chunks
            ],
        })

    all_tools.append(search_pdf_library)

    # ── Chart tool ─────────────────────────────────────────────────────────────

    class _ChartInput(BaseModel):
        chart_type:    str
        title:         str
        labels:        str
        dataset_label: str
        data:          str

        @field_validator("labels", "data", mode="before")
        @classmethod
        def _coerce_to_json_str(cls, v):
            if isinstance(v, (list, tuple)):
                return json.dumps(v)
            return v

    def _generate_chart(chart_type, title, labels, dataset_label, data) -> str:
        try:
            label_list = _parse_list(labels, str)
            data_list  = _parse_list(data, float)
        except (ValueError, TypeError) as exc:
            return f"Error parsing chart data: {exc}"
        return json.dumps({
            "type":          "chart",
            "chart_type":    chart_type,
            "title":         title,
            "labels":        label_list,
            "dataset_label": dataset_label,
            "data":          data_list,
        })

    generate_chart = StructuredTool.from_function(
        func=_generate_chart,
        name="generate_chart",
        args_schema=_ChartInput,
        description=(
            "Render a visual chart from query results. "
            "Call AFTER a query tool when the user asks for a chart/graph/visualization.\n\n"
            "chart_type: 'bar' | 'line' | 'pie' | 'doughnut'\n"
            "labels: JSON array of category/time strings, e.g. '[\"Jan\",\"Feb\"]'\n"
            "data:   JSON array of matching numbers,       e.g. '[1200.5, 980.0]'"
        ),
    )
    all_tools.append(generate_chart)

    return all_tools


# ── Conversation history ───────────────────────────────────────────────────────

_MAX_HISTORY_TURNS = 10  # keep last N human+AI pairs (2*N messages)
_chat_histories: dict[str, list] = {}


def clear_history(thread_id: str) -> None:
    _chat_histories.pop(thread_id, None)


# ── Streaming entry point ──────────────────────────────────────────────────────

def stream_message(message: str, user: dict | None = None, thread_id: str | None = None):
    """Generator yielding newline-delimited JSON events.

    Event shapes:
        {"status": "..."}                         — tool-running indicator
        {"token": "..."}                          — streaming text token
        {"done": true, "confidence": N}           — text complete
        {"done": true, "data": {...}, "confidence": N} — structured response
    """
    user_ctx = (
        f"Current user: {user['name']} | role: {user['role']} | "
        f"department: {user.get('department', 'N/A')}."
        if user else "User is not authenticated."
    )

    tracker = _ConfidenceTracker()
    history = _chat_histories.get(thread_id, []) if thread_id else []

    try:
        tools = _make_tools(user)
        agent = create_react_agent(get_llm(), tools)

        tool_status_shown: set[str] = set()
        chart_data:        dict | None = None

        token_buffer:      list[str] = []
        accumulated_text:  list[str] = []
        current_step:      int  = -1
        step_is_tool_call: bool = False

        for chunk, metadata in agent.stream(
            {"messages": [
                SystemMessage(content=_build_system(user_ctx)),
                *history,
                HumanMessage(content=message),
            ]},
            {"recursion_limit": 10},
            stream_mode="messages",
        ):
            node = metadata.get("langgraph_node", "")
            step = metadata.get("langgraph_step", 0)

            if node == "agent" and isinstance(chunk, AIMessageChunk):
                if step != current_step:
                    if current_step >= 0 and not step_is_tool_call:
                        for tok in token_buffer:
                            accumulated_text.append(tok)
                            yield json.dumps({"token": tok}) + "\n"
                    token_buffer      = []
                    step_is_tool_call = False
                    current_step      = step

                if chunk.tool_call_chunks:
                    step_is_tool_call = True
                    for tc in chunk.tool_call_chunks:
                        name = tc.get("name", "")
                        if name and name not in tool_status_shown:
                            tool_status_shown.add(name)
                            label = name.replace("_", " ").title()
                            yield json.dumps({"status": f"Running {label}…"}) + "\n"
                elif chunk.content:
                    text = _clean(_extract_text(chunk.content))
                    if text:
                        token_buffer.append(text)

            elif node == "tools" and isinstance(chunk, ToolMessage):
                tool_name = chunk.name or ""

                if tool_name.startswith("query_") or tool_name.startswith("schema_"):
                    tracker.record_sql(chunk.content)

                elif tool_name == "search_pdf_library":
                    tracker.record_pdf(chunk.content)

                elif tool_name == "generate_chart":
                    try:
                        chart_data = json.loads(chunk.content)
                    except Exception:
                        pass

        if not step_is_tool_call and token_buffer:
            for tok in token_buffer:
                accumulated_text.append(tok)
                yield json.dumps({"token": tok}) + "\n"

        # Persist conversation turn so follow-up questions have context.
        if thread_id and accumulated_text:
            ai_text = "".join(accumulated_text)
            updated = history + [HumanMessage(content=message), AIMessage(content=ai_text)]
            _chat_histories[thread_id] = updated[-(2 * _MAX_HISTORY_TURNS):]

        confidence = tracker.get()
        logger.info("Response confidence: %d%%", confidence)

        if chart_data:
            yield json.dumps({"done": True, "data": chart_data, "confidence": confidence}) + "\n"
        else:
            yield json.dumps({"done": True, "confidence": confidence}) + "\n"

    except Exception as exc:
        import traceback
        traceback.print_exc()
        msg = _friendly_error(exc)
        s   = str(exc)
        is_failed = "failed_generation" in s or "Failed to call a function" in s
        payload: dict = {"type": "error", "message": msg}
        if is_failed:
            payload["suggestions"] = _SUGGESTIONS
        yield json.dumps({"done": True, "data": payload, "confidence": 0}) + "\n"


# ── Synchronous wrapper ────────────────────────────────────────────────────────

def process_message(message: str, user: dict | None = None) -> dict:
    last: dict = {"type": "error", "message": "No response."}
    for line in stream_message(message, user):
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except Exception:
            continue
        if evt.get("done"):
            last = evt.get("data") or {"type": "text", "message": "Done."}
        elif evt.get("token"):
            if last.get("type") != "text":
                last = {"type": "text", "message": ""}
            last["message"] = last.get("message", "") + evt["token"]
    return last
