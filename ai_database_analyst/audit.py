"""Append-only audit trail: one JSON object per line, size-rotated.

Every sign-in, sign-out, query, rejection, rate-limit hit and CSV export is
recorded with who, when and what. Passwords never reach this module; any field
whose name contains "password" or "secret" is dropped as a safety net.

Failures to write are logged to the application log but never break a request.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional

from . import __version__
from .config import settings
from .log import logger

# Event names.
LOGIN_SUCCESS = "login_success"
LOGIN_FAILURE = "login_failure"
LOGIN_LOCKED = "login_locked"
LOGOUT = "logout"
SESSION_TIMEOUT = "session_timeout"
QUERY_OK = "query_ok"
QUERY_REJECTED = "query_rejected"
QUERY_ERROR = "query_error"
RATE_LIMITED = "rate_limited"
EXPORT_CSV = "export_csv"

_MAX_TEXT = 2000
_SENSITIVE = ("password", "secret", "token")


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > _MAX_TEXT:
        return value[:_MAX_TEXT] + "...[truncated]"
    return value


class AuditLog:
    """Writes audit events to ``path`` (created with 0600 permissions where supported)."""

    def __init__(self, path: str, *, max_bytes: int, backup_count: int, log_questions: bool = True) -> None:
        self.path = Path(path)
        self.log_questions = log_questions
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            fd = os.open(self.path, os.O_CREAT | os.O_WRONLY, 0o600)
            os.close(fd)
        self._logger = logging.Logger(f"audit:{self.path}")  # not in the global registry: no leaks between instances
        self._handler = RotatingFileHandler(self.path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(self._handler)
        self._logger.propagate = False
        self._lock = threading.Lock()

    def record(self, event: str, user: Optional[str] = None, **fields: Any) -> None:
        entry: dict = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "event": event,
            "user": user or "-",
            "app_version": __version__,
        }
        question = fields.pop("question", None)
        if question is not None:
            if self.log_questions:
                entry["question"] = _clip(question)
            else:
                entry["question_sha256"] = hashlib.sha256(str(question).encode("utf-8")).hexdigest()
        for key, value in fields.items():
            if any(word in key.lower() for word in _SENSITIVE) or value is None:
                continue
            entry[key] = _clip(value)
        line = json.dumps(entry, ensure_ascii=False, default=str)
        with self._lock:
            self._logger.info(line)

    def close(self) -> None:
        self._handler.close()
        self._logger.removeHandler(self._handler)


_instance: Optional[AuditLog] = None
_instance_lock = threading.Lock()


def get_audit_log() -> Optional[AuditLog]:
    """The process-wide audit log, or None when auditing is disabled or cannot be opened."""
    global _instance
    if not settings.audit_enabled:
        return None
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                try:
                    _instance = AuditLog(
                        settings.audit_log_path,
                        max_bytes=settings.audit_max_bytes,
                        backup_count=settings.audit_backup_count,
                        log_questions=settings.audit_log_questions,
                    )
                except OSError as exc:
                    logger.error("Audit log %s cannot be opened: %s", settings.audit_log_path, exc)
                    return None
    return _instance


def audit(event: str, user: Optional[str] = None, **fields: Any) -> None:
    """Record an audit event. Never raises."""
    try:
        log = get_audit_log()
        if log is not None:
            log.record(event, user, **fields)
    except Exception:  # an audit failure must not take the app down, but it must be visible
        logger.exception("Failed to write audit event %s", event)


def audit_problem() -> Optional[str]:
    """Why auditing is enabled but not working, or None if fine/disabled."""
    if settings.audit_enabled and get_audit_log() is None:
        return f"The audit log at {settings.audit_log_path} cannot be written. Fix the path or permissions."
    return None
