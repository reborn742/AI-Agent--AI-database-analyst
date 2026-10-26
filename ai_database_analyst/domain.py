"""Business profile: what this database is about and how the organisation talks about it.

A YAML file (``ANALYST_DOMAIN_FILE``) teaches the analyst your data without touching code:
preferred tables, metric definitions, glossary, example questions, a few worked SQL examples,
and which tables or columns must stay invisible. With no file the analyst is fully generic and
works from the live schema alone. See ``config/domain.example.yaml``.

Edits to the file take effect on the next question; no restart needed.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import yaml

from .config import settings
from .errors import ConfigurationError
from .schema import SENSITIVE_COLUMN_PATTERNS

_ALLOWED_KEYS = frozenset(
    {
        "title", "subtitle", "eyebrow", "organization", "description", "preferred_sources", "rules",
        "glossary", "metrics", "tables", "columns", "examples", "sql_examples", "hidden_tables",
        "hidden_columns", "hide_sensitive_defaults",
    }
)


@dataclass(frozen=True)
class PreferredSource:
    name: str
    use_for: str


@dataclass(frozen=True)
class SqlExample:
    question: str
    sql: str


@dataclass(frozen=True)
class DomainProfile:
    title: str = "AI Database Analyst"
    subtitle: str = (
        "Ask questions about your company data in plain English. Queries are validated, read-only and audited."
    )
    eyebrow: str = "Local AI · Read-only"
    organization: str = ""
    description: str = ""
    preferred_sources: tuple = ()
    rules: tuple = ()
    glossary: tuple = ()  # ((term, definition), ...)
    metrics: tuple = ()  # ((name, definition), ...)
    table_descriptions: dict = field(default_factory=dict)  # lower-cased table -> text
    column_descriptions: dict = field(default_factory=dict)  # (table, column) lower-cased -> text
    examples: tuple = ()
    sql_examples: tuple = ()
    hidden_tables: tuple = ()
    hidden_columns: tuple = SENSITIVE_COLUMN_PATTERNS


class _Reader:
    """Typed access to the parsed YAML with errors that name the file and the key."""

    def __init__(self, data: dict, path: str) -> None:
        self.data = data
        self.path = path

    def fail(self, key: str, problem: str) -> ConfigurationError:
        return ConfigurationError(f"Domain profile {self.path}: '{key}' {problem}.")

    def text(self, key: str, limit: int, default: str = "") -> str:
        value = self.data.get(key)
        if value is None:
            return default
        if not isinstance(value, str):
            raise self.fail(key, "must be text")
        value = value.strip()
        if len(value) > limit:
            raise self.fail(key, f"is too long (max {limit} characters)")
        return value

    def strings(self, key: str, max_items: int, max_len: int) -> tuple:
        value = self.data.get(key)
        if value is None:
            return ()
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise self.fail(key, "must be a list of text items")
        if len(value) > max_items:
            raise self.fail(key, f"has too many items (max {max_items})")
        items = [v.strip() for v in value if v.strip()]
        if any(len(v) > max_len for v in items):
            raise self.fail(key, f"has an item longer than {max_len} characters")
        return tuple(items)

    def mapping(self, key: str, max_items: int, max_key: int, max_value: int) -> dict:
        value = self.data.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise self.fail(key, "must be a mapping of text to text")
        if len(value) > max_items:
            raise self.fail(key, f"has too many entries (max {max_items})")
        result = {k.strip(): v.strip() for k, v in value.items()}
        if any(len(k) > max_key or len(v) > max_value for k, v in result.items()):
            raise self.fail(key, f"has an entry that is too long (key {max_key}, value {max_value} characters)")
        return result


def parse_profile(data: Any, path: str = "<memory>") -> DomainProfile:
    """Validate parsed YAML and build a profile. Raises ConfigurationError with a precise message."""
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigurationError(f"Domain profile {path}: the file must contain a YAML mapping.")
    unknown = sorted(set(data) - _ALLOWED_KEYS)
    if unknown:
        raise ConfigurationError(
            f"Domain profile {path}: unknown key(s) {', '.join(map(str, unknown))}. "
            f"Allowed: {', '.join(sorted(_ALLOWED_KEYS))}."
        )
    r = _Reader(data, path)
    defaults = DomainProfile()

    sources = []
    raw_sources = data.get("preferred_sources")
    if raw_sources is not None:
        if not isinstance(raw_sources, list) or len(raw_sources) > 10:
            raise r.fail("preferred_sources", "must be a list of at most 10 entries")
        for entry in raw_sources:
            if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                raise r.fail("preferred_sources", "entries need a 'name' and a 'use_for'")
            sources.append(PreferredSource(entry["name"].strip(), str(entry.get("use_for", "")).strip()[:200]))

    examples = []
    raw_examples = data.get("sql_examples")
    if raw_examples is not None:
        if not isinstance(raw_examples, list) or len(raw_examples) > 5:
            raise r.fail("sql_examples", "must be a list of at most 5 entries")
        for entry in raw_examples:
            if not isinstance(entry, dict) or not all(isinstance(entry.get(k), str) for k in ("question", "sql")):
                raise r.fail("sql_examples", "entries need a 'question' and a 'sql'")
            if len(entry["question"]) > 200 or len(entry["sql"]) > 1500:
                raise r.fail("sql_examples", "has an entry that is too long")
            examples.append(SqlExample(entry["question"].strip(), entry["sql"].strip().rstrip(";")))

    column_descriptions = {}
    for key, value in r.mapping("columns", 300, 120, 120).items():
        table, dot, column = key.lower().partition(".")
        if not dot or not column:
            raise r.fail("columns", f"keys must look like table.column (got '{key}')")
        column_descriptions[(table, column)] = value

    hidden_columns = list(r.strings("hidden_columns", 100, 120))
    if data.get("hide_sensitive_defaults", True) is not False:
        hidden_columns.extend(SENSITIVE_COLUMN_PATTERNS)

    return DomainProfile(
        title=r.text("title", 80, defaults.title),
        subtitle=r.text("subtitle", 240, defaults.subtitle),
        eyebrow=r.text("eyebrow", 60, defaults.eyebrow),
        organization=r.text("organization", 80),
        description=r.text("description", 1500),
        preferred_sources=tuple(sources),
        rules=r.strings("rules", 25, 300),
        glossary=tuple(r.mapping("glossary", 40, 60, 200).items()),
        metrics=tuple(r.mapping("metrics", 30, 60, 250).items()),
        table_descriptions={k.lower(): v for k, v in r.mapping("tables", 100, 80, 160).items()},
        column_descriptions=column_descriptions,
        examples=r.strings("examples", 12, 200),
        sql_examples=tuple(examples),
        hidden_tables=r.strings("hidden_tables", 100, 80),
        hidden_columns=tuple(hidden_columns),
    )


def load_profile(path: str) -> DomainProfile:
    file = Path(path)
    try:
        text = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise ConfigurationError(f"Domain profile {path} cannot be read: {exc.strerror or exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Domain profile {path} is not valid YAML: {exc}") from exc
    return parse_profile(data, path)


_cache: dict = {}
_lock = threading.Lock()


def get_profile(path: Optional[str] = None) -> DomainProfile:
    """The active profile (generic when no file is configured). Re-read when the file changes."""
    path = settings.domain_file if path is None else path
    if not path.strip():
        return DomainProfile()
    try:
        stamp = Path(path).stat().st_mtime_ns
    except OSError as exc:
        raise ConfigurationError(f"Domain profile {path} cannot be read: {exc.strerror or exc}") from exc
    with _lock:
        cached = _cache.get(path)
        if cached and cached[0] == stamp:
            return cached[1]
    profile = load_profile(path)
    with _lock:
        _cache[path] = (stamp, profile)
    return profile
