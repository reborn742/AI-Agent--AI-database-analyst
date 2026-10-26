"""SQL validation (the security boundary).

The SQL that is executed is regenerated from the parsed SQLGlot tree (with
comments removed), then parsed and checked again. Raw model text is never run.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from typing import Optional

import sqlglot
from sqlglot import exp

from .config import settings
from .errors import QueryValidationError
from .schema import SchemaInfo

# Functions rejected by name (side effects, locks, delays, file access, server info).
FORBIDDEN_FUNCTIONS = frozenset(
    name.upper().replace("_", "")
    for name in (
        "SLEEP", "BENCHMARK", "LOAD_FILE", "GET_LOCK", "RELEASE_LOCK",
        "RELEASE_ALL_LOCKS", "IS_FREE_LOCK", "IS_USED_LOCK", "MASTER_POS_WAIT",
        "SOURCE_POS_WAIT", "WAIT_FOR_EXECUTED_GTID_SET",
        "WAIT_UNTIL_SQL_THREAD_AFTER_GTIDS", "SYS_EXEC", "SYS_EVAL",
        "USER", "CURRENT_USER", "SESSION_USER", "SYSTEM_USER", "VERSION",
        # Newer SQLGlot parses VERSION() as CurrentVersion, so list that name too.
        "CURRENT_VERSION",
        "CONNECTION_ID",
    )
)

# Functions SQLGlot does not model as typed expressions (it returns them as
# "anonymous" functions). Anything anonymous must be on this list; typed
# functions are accepted unless forbidden above.
ALLOWED_ANONYMOUS_FUNCTIONS = frozenset(
    name.upper()
    for name in (
        "ABS", "ACOS", "ASIN", "ATAN", "ATAN2", "BIT_AND", "BIT_OR", "BIT_XOR",
        "CEIL", "CEILING", "CONCAT_WS", "COS", "CUME_DIST", "DAYNAME",
        "DAYOFMONTH", "DAYOFWEEK", "DAYOFYEAR", "DEGREES", "DENSE_RANK", "EXP",
        "FIND_IN_SET", "FIRST_VALUE", "FLOOR", "FORMAT", "FROM_DAYS", "GREATEST",
        "HOUR", "IF", "IFNULL", "LAG", "LAST_DAY", "LAST_VALUE", "LEAD", "LEAST",
        "LN", "LOG", "LOG10", "LOG2", "LPAD", "LTRIM", "MAKEDATE", "MINUTE", "MOD",
        "MONTHNAME", "NTH_VALUE", "NTILE", "NULLIF", "PERCENT_RANK", "PERIOD_DIFF",
        "PI", "POW", "POWER", "QUARTER", "RADIANS", "RANK", "REVERSE", "ROW_NUMBER",
        "RPAD", "RTRIM", "SECOND", "SIGN", "SIN", "SQRT", "STD", "STDDEV",
        "STDDEV_POP", "STDDEV_SAMP", "TAN", "TIMESTAMPADD", "TIMESTAMPDIFF",
        "TO_DAYS", "TRUNCATE", "VAR_POP", "VAR_SAMP", "VARIANCE", "WEEK",
        "WEEKDAY", "WEEKOFYEAR", "YEARWEEK",
        "ANY_VALUE", "AVG", "CHAR_LENGTH", "COALESCE", "CONCAT", "COUNT",
        "CURDATE", "DATE", "DATE_ADD", "DATE_FORMAT", "DATE_SUB", "DATEDIFF",
        "DAY", "EXTRACT", "GROUP_CONCAT", "LEFT", "LENGTH", "LOWER", "MAX", "MIN",
        "MONTH", "NOW", "REPLACE", "RIGHT", "ROUND", "STR_TO_DATE", "SUBSTR",
        "SUBSTRING", "SUM", "TIME", "TIMESTAMP", "TRIM", "UPPER", "YEAR",
    )
)

# Secondary lexical layer on the *regenerated* SQL (string literals blanked).
# This is defense in depth only; the AST checks are the primary control.
_SECONDARY_PATTERNS = (
    r"\bINTO\s+(OUTFILE|DUMPFILE)\b",
    r"\bLOAD_FILE\s*\(",
    r"\bSLEEP\s*\(",
    r"\bBENCHMARK\s*\(",
    r"\b(GET|RELEASE|IS_FREE|IS_USED)_LOCK\s*\(",
    r"\bFOR\s+(UPDATE|SHARE)\b",
    r"\bLOCK\s+IN\s+SHARE\s+MODE\b",
    r"@@?\w",
)

@dataclass(frozen=True)
class ValidatedQuery:
    sql: str
    original_limit: Optional[int]  # LIMIT written in the generated SQL, if any
    cap_applied: bool  # True if the row cap was added or lowered a larger LIMIT



@functools.lru_cache(maxsize=1)
def _node_types() -> dict:
    """Resolve SQLGlot classes lazily; tolerate version differences in class names."""

    def pick(*names: str) -> tuple:
        return tuple(getattr(exp, n) for n in names if hasattr(exp, n))

    return {
        "top_level": pick("Select", "Union", "Intersect", "Except", "SetOperation"),
        "forbidden": tuple(
            (getattr(exp, n), label)
            for n, label in (
                ("Into", "SELECT INTO"),
                ("Lock", "locking clauses (FOR UPDATE / SHARE)"),
                ("Hint", "optimizer hints"),
                ("Parameter", "user variables"),
                ("SessionParameter", "system variables"),
                ("Placeholder", "placeholders"),
                ("Command", "raw commands"),
            )
            if hasattr(exp, n)
        ),
        "anonymous": pick("Anonymous", "AnonymousAggFunc"),
    }


def _clean_error(exc: BaseException) -> str:
    text = re.sub(r"\x1b\[[0-9;]*m", "", str(exc))
    return " ".join(text.split())[:300]


def _strip_code_fence(sql: str) -> str:
    sql = sql.strip()
    sql = re.sub(r"^```(?:sql|mysql)?\s*", "", sql, flags=re.IGNORECASE)
    return re.sub(r"\s*```$", "", sql).strip()


def _parse_single(sql: str) -> exp.Expression:
    try:
        statements = sqlglot.parse(sql, read="mysql")
    except Exception as exc:  # fail closed on any parser failure
        raise QueryValidationError(
            f"The generated SQL could not be parsed: {_clean_error(exc)}", repairable=True
        ) from exc
    statements = [s for s in statements if s is not None]
    if len(statements) != 1:
        raise QueryValidationError("Only one SQL statement is allowed.")
    return statements[0]


def _unwrap_top_level(tree: exp.Expression) -> exp.Expression:
    node = tree
    while isinstance(node, (exp.Subquery, exp.Paren)):
        if any(node.args.get(arg) for arg in ("limit", "order", "offset")):
            raise QueryValidationError(
                "Parenthesised queries with their own ORDER BY or LIMIT are not supported."
            )
        node = node.this
    return node


def _check_tree(query: exp.Expression, schema: SchemaInfo) -> None:
    """Raise QueryValidationError unless the tree is a safe, schema-bound SELECT."""
    types = _node_types()

    if not isinstance(query, types["top_level"]):
        raise QueryValidationError("Only read-only SELECT queries are allowed.")
    if query.args.get("fetch") is not None:
        raise QueryValidationError("FETCH clauses are not supported; use LIMIT.")

    for node_type, label in types["forbidden"]:
        if query.find(node_type) is not None:
            raise QueryValidationError(f"The query uses {label}, which is not allowed.")

    # Recursive CTEs can run away; they are not needed for these questions.
    for with_node in query.find_all(exp.With):
        if with_node.args.get("recursive"):
            raise QueryValidationError("Recursive CTEs are not allowed.")

    # Functions.
    for func in query.find_all(exp.Func):
        if isinstance(func, types["anonymous"]):
            name = (func.name or "").upper()
            if name.replace("_", "") in FORBIDDEN_FUNCTIONS:
                raise QueryValidationError(f"The function {name}() is not allowed.")
            if name not in ALLOWED_ANONYMOUS_FUNCTIONS:
                raise QueryValidationError(
                    f"The function {name}() is not on the allowed function list.", repairable=True
                )
            continue
        try:
            name = type(func).sql_name().upper()
        except Exception:
            name = type(func).__name__.upper()
        candidates = {name.replace("_", ""), type(func).__name__.upper().replace("_", "")}
        if candidates & FORBIDDEN_FUNCTIONS:
            raise QueryValidationError(f"The function {name}() is not allowed.")

    # Complexity bounds (the execution timeout is the real guard against cost).
    if sum(1 for _ in query.find_all(exp.Select)) > settings.max_select_blocks:
        raise QueryValidationError(f"The query has too many nested SELECT blocks (max {settings.max_select_blocks}).")
    tables = list(query.find_all(exp.Table))
    if len(tables) > settings.max_table_references:
        raise QueryValidationError(f"The query references too many tables (max {settings.max_table_references}).")

    # Tables: every physical reference must be a table/view of the configured database.
    cte_names = {
        cte.alias_or_name.lower()
        for cte in query.find_all(exp.CTE)
        if cte.alias_or_name
    }
    opaque_names = set(cte_names)
    for sub in query.find_all(exp.Subquery):
        if sub.alias:
            opaque_names.add(sub.alias.lower())

    physical_columns: dict = {}
    for table in tables:
        if not isinstance(table.this, exp.Identifier):
            raise QueryValidationError("Table-valued functions are not allowed.")
        if table.catalog:
            raise QueryValidationError(
                "Cross-server or catalog-qualified table references are not allowed."
            )
        if table.db and table.db.lower() != settings.db_name.lower():
            raise QueryValidationError("References to other databases are not allowed.")
        table_name = table.name.lower()
        if not table.db and table_name in cte_names:
            continue
        if table_name not in schema.tables:
            raise QueryValidationError(f"Unknown table or view: {table.name}", repairable=True)
        key = (table.alias or table.name).lower()
        physical_columns.setdefault(key, set()).update(schema.tables[table_name])

    # Qualified columns that point at a physical table must exist in it.
    # (Unqualified columns and scoping are left to MySQL, which enforces them.)
    for column in query.find_all(exp.Column):
        if isinstance(column.this, exp.Star) or not column.table:
            continue
        qualifier = column.table.lower()
        if qualifier in opaque_names or qualifier not in physical_columns:
            continue
        if column.name.lower() not in physical_columns[qualifier]:
            raise QueryValidationError(
                f"Column '{column.name}' does not exist in '{column.table}'.", repairable=True
            )

    _check_restricted_columns(query, schema, tables, cte_names)


def _check_restricted_columns(query: exp.Expression, schema: SchemaInfo, tables: list, cte_names: set) -> None:
    """Block every route to columns the profile hides (SELECT *, bare names, aliases of them)."""
    referenced = {t.name.lower() for t in tables if t.db or t.name.lower() not in cte_names}
    restricted = referenced & schema.restricted_tables
    if not restricted:
        return
    for star in query.find_all(exp.Star):
        if not isinstance(star.parent, exp.Count):  # COUNT(*) exposes no column values
            raise QueryValidationError(
                "SELECT * is not allowed on tables with restricted columns; list the columns you need.",
                repairable=True,
            )
    hidden_names = schema.hidden_names_for(restricted)
    visible_names: set = set()
    for table in referenced:
        visible_names |= schema.tables.get(table, frozenset())
    for column in query.find_all(exp.Column):
        name = column.name.lower()
        if isinstance(column.this, exp.Star) or name not in hidden_names or name in visible_names:
            continue
        raise QueryValidationError(f"The column '{column.name}' is restricted and cannot be queried.", repairable=True)


def _literal_limit(query: exp.Expression) -> Optional[int]:
    """Return the top-level LIMIT as an int, None if absent; raise if not a literal."""
    limit_node = query.args.get("limit")
    if limit_node is None:
        return None
    limit_expr = limit_node.expression
    if not isinstance(limit_expr, exp.Literal) or limit_expr.is_string:
        raise QueryValidationError("Only numeric LIMIT values are allowed.")
    try:
        value = int(limit_expr.this)
    except (TypeError, ValueError) as exc:
        raise QueryValidationError("LIMIT must be a whole number.") from exc
    if value < 1:
        raise QueryValidationError("LIMIT must be at least 1.")
    return value


def _strip_string_literals(sql: str) -> str:
    sql = re.sub(r"'(?:[^'\\]|\\.|'')*'", "''", sql)
    return re.sub(r'"(?:[^"\\]|\\.|"")*"', '""', sql)


def validate_sql(sql: str, schema: SchemaInfo) -> ValidatedQuery:
    """Validate model-generated SQL and return the exact SQL to execute."""
    sql = _strip_code_fence(sql)
    if len(sql) > settings.max_sql_chars:
        raise QueryValidationError("The generated SQL is too long.")

    tree = _parse_single(sql)
    query = _unwrap_top_level(tree)
    _check_tree(query, schema)

    # Enforce the row cap on the top-level query (this also covers set operations).
    original_limit = _literal_limit(query)
    cap_applied = False
    if original_limit is None:
        query = query.limit(settings.max_rows)
        cap_applied = True
    elif original_limit > settings.max_rows:
        query = query.copy()
        query.args["limit"].set("expression", exp.Literal.number(settings.max_rows))
        cap_applied = True

    final_sql = query.sql(dialect="mysql", comments=False, pretty=True).strip().rstrip(";")

    # Re-validate exactly what will be executed.
    final_tree = _unwrap_top_level(_parse_single(final_sql))
    _check_tree(final_tree, schema)
    final_limit = _literal_limit(final_tree)
    if final_limit is None or final_limit > settings.max_rows:
        raise QueryValidationError("The row limit could not be enforced on this query.")

    scrubbed = _strip_string_literals(final_sql)
    for pattern in _SECONDARY_PATTERNS:
        if re.search(pattern, scrubbed, flags=re.IGNORECASE):
            raise QueryValidationError("The query contains a prohibited SQL operation.")

    return ValidatedQuery(sql=final_sql, original_limit=original_limit, cap_applied=cap_applied)
