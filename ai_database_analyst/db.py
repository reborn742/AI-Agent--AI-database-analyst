"""MySQL access: connection, schema discovery and read-only query execution."""

from __future__ import annotations

import time
from contextlib import suppress
from typing import Any

import mysql.connector
import pandas as pd

from .config import settings
from .domain import get_profile
from .errors import MissingCredentialsError
from .log import logger
from .schema import SchemaInfo


def connect_db(password: str):
    if not password:
        raise MissingCredentialsError("Enter the database password in the sidebar.")
    options: dict = {}
    if settings.db_ssl_ca:
        options.update(ssl_ca=settings.db_ssl_ca, ssl_verify_cert=True, ssl_disabled=False)
    return mysql.connector.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=password,
        database=settings.db_name,
        connection_timeout=settings.db_connect_timeout_s,
        autocommit=False,
        **options,
    )


def _safe_close(resource: Any, label: str) -> None:
    try:
        resource.close()
    except Exception as exc:  # cleanup must never mask the real result/error
        logger.debug("Ignoring error while closing %s: %s", label, type(exc).__name__)


def _to_text(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).decode("utf-8", errors="replace")
    return str(value)


def _read_metadata(cursor: Any) -> dict:
    """Primary keys, foreign keys and comments. Best effort: the schema still works without them."""
    meta: dict = {"pk": {}, "fk": {}, "table_comments": {}, "column_comments": {}}
    queries = (
        (
            "SELECT TABLE_NAME, COLUMN_NAME, COLUMN_KEY, COLUMN_COMMENT FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = %s",
            "columns",
        ),
        (
            "SELECT TABLE_NAME, COLUMN_NAME, REFERENCED_TABLE_NAME, REFERENCED_COLUMN_NAME "
            "FROM information_schema.KEY_COLUMN_USAGE "
            "WHERE TABLE_SCHEMA = %s AND REFERENCED_TABLE_NAME IS NOT NULL",
            "foreign keys",
        ),
        ("SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s", "tables"),
    )
    for sql, label in queries:
        try:
            cursor.execute(sql, (settings.db_name,))
            rows = cursor.fetchall()
        except mysql.connector.Error as exc:
            logger.warning("Could not read %s metadata (%s); continuing without it.", label, type(exc).__name__)
            continue
        for row in rows:
            values = [_to_text(v) if v is not None else "" for v in row]
            table = values[0].lower()
            if label == "columns":
                if values[2] == "PRI":
                    meta["pk"].setdefault(table, []).append(values[1].lower())
                if values[3]:
                    meta["column_comments"][(table, values[1].lower())] = values[3]
            elif label == "foreign keys":
                meta["fk"].setdefault((table, values[1].lower()), (values[2].lower(), values[3].lower()))
            elif values[1]:
                meta["table_comments"][table] = values[1]
    return meta


def get_schema(password: str) -> SchemaInfo:
    """Read tables, views and columns (plus keys and comments) from the configured database.

    Tables and columns hidden by the business profile are removed here, before the schema reaches
    the model or the validator.
    """
    profile = get_profile()
    connection = connect_db(password)
    cursor = None
    meta: dict = {}
    try:
        cursor = connection.cursor()
        cursor.execute("SHOW FULL TABLES")
        table_rows = cursor.fetchall()

        columns_by_table: dict = {}
        for row in table_rows:
            table_name = _to_text(row[0])
            table_type = _to_text(row[1])
            if table_type not in ("BASE TABLE", "VIEW"):
                continue
            safe_name = table_name.replace("`", "``")
            cursor.execute(f"SHOW COLUMNS FROM `{safe_name}`")
            columns_by_table[table_name] = [
                (_to_text(col[0]), _to_text(col[1])) for col in cursor.fetchall()
            ]
        meta = _read_metadata(cursor)
    finally:
        if cursor is not None:
            _safe_close(cursor, "schema cursor")
        _safe_close(connection, "schema connection")

    if not columns_by_table:
        raise ValueError(f"No tables or views were found in {settings.db_name}.")
    table_comments = {**meta["table_comments"], **profile.table_descriptions}
    column_comments = {**meta["column_comments"], **profile.column_descriptions}
    return SchemaInfo.from_columns(
        columns_by_table,
        primary_keys=meta["pk"],
        foreign_keys=meta["fk"],
        table_comments=table_comments,
        column_comments=column_comments,
        hidden_tables=profile.hidden_tables,
        hidden_columns=profile.hidden_columns,
    )


def _unique_columns(columns: list) -> list:
    seen: dict = {}
    result = []
    for column in columns:
        name = str(column)
        seen[name] = seen.get(name, 0) + 1
        result.append(name if seen[name] == 1 else f"{name}_{seen[name]}")
    return result


def run_query(sql: str, password: str) -> tuple:
    """Run validated SQL in a read-only transaction. Returns (DataFrame, seconds)."""
    connection = connect_db(password)
    cursor = None
    started = time.perf_counter()
    try:
        # Buffered: the SQL already carries LIMIT <= max_rows, and a buffered
        # cursor leaves no unread result that could break rollback/close.
        cursor = connection.cursor(buffered=True)
        cursor.execute(f"SET SESSION MAX_EXECUTION_TIME = {int(settings.query_timeout_ms)}")
        cursor.execute("START TRANSACTION READ ONLY")
        cursor.execute(sql)
        if cursor.description is None:
            raise ValueError("The query did not return a result set.")
        columns = _unique_columns([d[0] for d in cursor.description])
        rows = cursor.fetchmany(settings.max_rows)
        frame = pd.DataFrame(rows, columns=columns)
        return frame, round(time.perf_counter() - started, 2)
    finally:
        with suppress(Exception):
            connection.rollback()
        if cursor is not None:
            _safe_close(cursor, "query cursor")
        _safe_close(connection, "query connection")
