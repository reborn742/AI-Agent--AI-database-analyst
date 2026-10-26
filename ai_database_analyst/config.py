"""Central configuration.

Every setting has a safe default and can be overridden with an ``ANALYST_*``
environment variable (or a ``.env`` file in the working directory). Numeric
overrides are clamped to a sane range; invalid values fall back to the default.

Secrets (the database password) are intentionally not part of this module:
see ``credentials.py``. Keeping them out of ``Settings`` means they can never
appear in a ``repr()``, a log line or a crash report.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping, Optional

from .log import logger


def _env_str(environ: Mapping[str, str], name: str, default: str) -> str:
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip()


def _env_int(
    environ: Mapping[str, str], name: str, default: int, low: int, high: int
) -> int:
    """Read an optional integer override, clamped to [low, high]."""
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Ignoring %s: value is not an integer.", name)
        return default
    return min(max(value, low), high)


_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _env_bool(environ: Mapping[str, str], name: str, default: bool) -> bool:
    """Read an optional boolean override (true/false, yes/no, on/off, 1/0)."""
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    logger.warning("Ignoring %s: expected true or false.", name)
    return default


def _env_choice(environ: Mapping[str, str], name: str, default: str, choices: tuple) -> str:
    """Read an optional override that must be one of ``choices``."""
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value not in choices:
        logger.warning("Ignoring %s: expected one of %s.", name, ", ".join(choices))
        return default
    return value


AUTH_MODES = ("local", "proxy", "none")


@dataclass(frozen=True)
class Settings:
    # --- Ollama -----------------------------------------------------------
    ollama_url: str = "http://localhost:11434/api/generate"
    model: str = "qwen2.5:3b"
    # Connection and read timeouts are separate: with stream=False Ollama sends
    # nothing until generation finishes, so the read timeout must cover prompt
    # evaluation + the whole generation.
    ollama_connect_timeout_s: int = 5
    sql_read_timeout_s: int = 180
    explain_read_timeout_s: int = 180
    sql_max_tokens: int = 600
    explain_max_tokens: int = 300
    keep_alive: str = "30m"
    # Identical for every call so Ollama does not reload the model between
    # SQL generation and explanation.
    num_ctx: int = 8192

    # --- Database ---------------------------------------------------------
    db_name: str = "retail_analytics"
    db_user: str = "analyst_readonly"
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_connect_timeout_s: int = 5
    # Path to a CA bundle. When set, the connection must use TLS and the server
    # certificate is verified against it.
    db_ssl_ca: str = ""

    # --- Business context ---------------------------------------------------
    # YAML file describing the business (see config/domain.example.yaml). Empty = generic.
    domain_file: str = ""
    # Extra attempts the model gets to fix a query that failed validation or errored in MySQL.
    sql_retries: int = 1

    # --- Authentication ---------------------------------------------------
    # local: users file with scrypt hashes | proxy: trust an SSO reverse proxy
    # header | none: no login (local development only).
    auth_mode: str = "local"
    users_file: str = "data/users.json"
    proxy_user_header: str = "X-Forwarded-User"
    max_login_attempts: int = 5
    login_lockout_s: int = 300
    session_timeout_min: int = 60

    # --- Abuse protection and audit trail ---------------------------------
    max_queries_per_minute: int = 20
    audit_enabled: bool = True
    audit_log_path: str = "logs/audit.jsonl"
    # False stores a SHA-256 of the question instead of its text.
    audit_log_questions: bool = True
    audit_max_bytes: int = 10_485_760
    audit_backup_count: int = 10

    # --- Query limits -----------------------------------------------------
    max_rows: int = 500
    query_timeout_ms: int = 10000
    max_question_chars: int = 1000
    max_schema_chars: int = 30000

    # --- SQL validation bounds -------------------------------------------
    max_sql_chars: int = 8000
    max_table_references: int = 10
    max_select_blocks: int = 12

    # --- Explanation prompt bounds ---------------------------------------
    explain_preview_rows: int = 15
    explain_max_columns: int = 12
    explain_max_cell_chars: int = 60
    explain_max_sql_chars: int = 1500


def load_settings(environ: Optional[Mapping[str, str]] = None) -> Settings:
    """Build Settings from the environment (and ``.env`` when using os.environ)."""
    if environ is None:
        try:
            from dotenv import load_dotenv

            load_dotenv()  # never overrides variables already set in the real env
        except ImportError:
            pass
        environ = os.environ

    d = Settings()
    return Settings(
        ollama_url=_env_str(environ, "ANALYST_OLLAMA_URL", d.ollama_url),
        model=_env_str(environ, "ANALYST_MODEL", d.model),
        ollama_connect_timeout_s=d.ollama_connect_timeout_s,
        sql_read_timeout_s=_env_int(environ, "ANALYST_SQL_READ_TIMEOUT_S", d.sql_read_timeout_s, 30, 900),
        explain_read_timeout_s=_env_int(environ, "ANALYST_EXPLAIN_READ_TIMEOUT_S", d.explain_read_timeout_s, 30, 900),
        sql_max_tokens=_env_int(environ, "ANALYST_SQL_MAX_TOKENS", d.sql_max_tokens, 64, 2048),
        explain_max_tokens=_env_int(environ, "ANALYST_EXPLAIN_MAX_TOKENS", d.explain_max_tokens, 64, 1024),
        keep_alive=_env_str(environ, "ANALYST_KEEP_ALIVE", d.keep_alive),
        num_ctx=_env_int(environ, "ANALYST_NUM_CTX", d.num_ctx, 2048, 16384),
        db_name=_env_str(environ, "ANALYST_DB_NAME", d.db_name),
        db_user=_env_str(environ, "ANALYST_DB_USER", d.db_user),
        db_host=_env_str(environ, "ANALYST_DB_HOST", d.db_host),
        db_port=_env_int(environ, "ANALYST_DB_PORT", d.db_port, 1, 65535),
        db_connect_timeout_s=d.db_connect_timeout_s,
        db_ssl_ca=_env_str(environ, "ANALYST_DB_SSL_CA", d.db_ssl_ca),
        domain_file=_env_str(environ, "ANALYST_DOMAIN_FILE", d.domain_file),
        sql_retries=_env_int(environ, "ANALYST_SQL_RETRIES", d.sql_retries, 0, 3),
        auth_mode=_env_choice(environ, "ANALYST_AUTH_MODE", d.auth_mode, AUTH_MODES),
        users_file=_env_str(environ, "ANALYST_USERS_FILE", d.users_file),
        proxy_user_header=_env_str(environ, "ANALYST_PROXY_USER_HEADER", d.proxy_user_header),
        max_login_attempts=_env_int(environ, "ANALYST_MAX_LOGIN_ATTEMPTS", d.max_login_attempts, 1, 100),
        login_lockout_s=_env_int(environ, "ANALYST_LOGIN_LOCKOUT_S", d.login_lockout_s, 10, 86400),
        session_timeout_min=_env_int(environ, "ANALYST_SESSION_TIMEOUT_MIN", d.session_timeout_min, 1, 1440),
        max_queries_per_minute=_env_int(environ, "ANALYST_MAX_QUERIES_PER_MINUTE", d.max_queries_per_minute, 1, 600),
        audit_enabled=_env_bool(environ, "ANALYST_AUDIT_ENABLED", d.audit_enabled),
        audit_log_path=_env_str(environ, "ANALYST_AUDIT_LOG", d.audit_log_path),
        audit_log_questions=_env_bool(environ, "ANALYST_AUDIT_LOG_QUESTIONS", d.audit_log_questions),
        audit_max_bytes=_env_int(environ, "ANALYST_AUDIT_MAX_BYTES", d.audit_max_bytes, 100_000, 1_073_741_824),
        audit_backup_count=_env_int(environ, "ANALYST_AUDIT_BACKUPS", d.audit_backup_count, 1, 1000),
        max_rows=_env_int(environ, "ANALYST_MAX_ROWS", d.max_rows, 1, 5000),
        query_timeout_ms=_env_int(environ, "ANALYST_QUERY_TIMEOUT_MS", d.query_timeout_ms, 1000, 120000),
        max_question_chars=d.max_question_chars,
        max_schema_chars=d.max_schema_chars,
        max_sql_chars=d.max_sql_chars,
        max_table_references=d.max_table_references,
        max_select_blocks=d.max_select_blocks,
        explain_preview_rows=d.explain_preview_rows,
        explain_max_columns=d.explain_max_columns,
        explain_max_cell_chars=d.explain_max_cell_chars,
        explain_max_sql_chars=d.explain_max_sql_chars,
    )


settings = load_settings()
