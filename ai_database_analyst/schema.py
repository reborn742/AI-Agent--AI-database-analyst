"""Schema description used for prompting and for validation.

``SchemaInfo`` is built from the live database, then filtered: tables and columns the business
profile hides (personal data, secrets) are removed, so the model never sees them and the
validator rejects any attempt to reach them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Iterable, Optional

# Columns hidden by default. Word-bounded patterns avoid false hits such as "classname" for "ssn".
SENSITIVE_COLUMN_PATTERNS = (
    "*.password",
    "*.*password*",
    "*.*passwd*",
    "*.*secret*",
    "*.*api_key*",
    "*.*apikey*",
    "*.ssn",
    "*.*_ssn",
    "*.ssn_*",
    "*.*social_security*",
    "*.*credit_card*",
    "*.*card_number*",
    "*.*cvv*",
)

_MAX_COMMENT = 120


def _tidy(text: str, limit: int = _MAX_COMMENT) -> str:
    """One line, no double quotes (they delimit the comment in the prompt), bounded length."""
    text = re.sub(r"\s+", " ", str(text or "")).replace('"', "'").strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _matches(value: str, patterns: Iterable[str]) -> bool:
    return any(fnmatchcase(value, pattern.lower()) for pattern in patterns)


@dataclass(frozen=True)
class SchemaInfo:
    """Schema text for the prompt plus lower-cased table/column names for validation."""

    prompt_text: str
    tables: dict
    # table -> lower-cased names of columns that exist in the database but are hidden from users
    hidden: dict = field(default_factory=dict)

    @property
    def allowed_tables(self) -> frozenset:
        return frozenset(self.tables)

    @property
    def restricted_tables(self) -> frozenset:
        """Tables that have at least one hidden column."""
        return frozenset(self.hidden)

    def hidden_names_for(self, tables: Iterable[str]) -> frozenset:
        names: set = set()
        for table in tables:
            names |= self.hidden.get(table, frozenset())
        return frozenset(names)

    @classmethod
    def from_columns(
        cls,
        columns: dict,
        *,
        primary_keys: Optional[dict] = None,
        foreign_keys: Optional[dict] = None,
        table_comments: Optional[dict] = None,
        column_comments: Optional[dict] = None,
        hidden_tables: Iterable[str] = (),
        hidden_columns: Iterable[str] = (),
    ) -> "SchemaInfo":
        """Build from ``{table: [(column, type), ...]}``.

        Optional enrichments use lower-cased keys: ``primary_keys`` {table: [col]},
        ``foreign_keys`` {(table, col): (ref_table, ref_col)}, ``table_comments`` {table: text},
        ``column_comments`` {(table, col): text}. ``hidden_*`` take glob patterns such as
        ``employees.salary`` or ``*.email``.
        """
        primary_keys = primary_keys or {}
        foreign_keys = foreign_keys or {}
        table_comments = table_comments or {}
        column_comments = column_comments or {}
        hidden_tables = [p.lower() for p in hidden_tables]
        hidden_columns = [p.lower() for p in hidden_columns]

        def is_hidden(table: str, column: str) -> bool:
            return _matches(table, hidden_tables) or _matches(f"{table}.{column}", hidden_columns)

        lines = []
        tables: dict = {}
        hidden: dict = {}
        for table_name, cols in columns.items():
            table = table_name.lower()
            if _matches(table, hidden_tables):
                continue
            pks = set(primary_keys.get(table, ()))
            parts = []
            hidden_here = set()
            for name, ctype in cols:
                column = name.lower()
                if is_hidden(table, column):
                    hidden_here.add(column)
                    continue
                flags = [ctype]
                if column in pks:
                    flags.append("PK")
                reference = foreign_keys.get((table, column))
                if reference and not is_hidden(*reference):
                    flags.append(f"FK->{reference[0]}.{reference[1]}")
                text = f"{name} ({', '.join(flags)})"
                comment = _tidy(column_comments.get((table, column), ""))
                if comment:
                    text += f' "{comment}"'
                parts.append((column, text))
            if not parts:  # nothing visible: treat the whole table as hidden
                continue
            label = table_name
            description = _tidy(table_comments.get(table, ""), 160)
            if description:
                label += f" [{description}]"
            lines.append(f"{label}: " + ", ".join(text for _, text in parts))
            tables[table] = frozenset(column for column, _ in parts)
            if hidden_here:
                hidden[table] = frozenset(hidden_here)
        return cls(prompt_text="\n".join(lines), tables=tables, hidden=hidden)
