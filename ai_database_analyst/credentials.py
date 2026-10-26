"""Database password resolution.

The password is deliberately *not* part of ``Settings``. Sources, highest
priority first:

1. ``ANALYST_DB_PASSWORD_FILE``: path to a file (Docker/Kubernetes secrets).
2. ``ANALYST_DB_PASSWORD``: environment variable (prefer the file form).
3. The value typed into the sidebar by the signed-in user.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping, Optional

from .errors import ConfigurationError


def _read_secret_file(path: str) -> str:
    """Read a secret file. Tolerates CRLF line endings and a UTF-8 BOM (both common on Windows)."""
    try:
        return Path(path).read_text(encoding="utf-8-sig").rstrip("\r\n")
    except OSError as exc:
        # Report the path (not a secret) and the reason, never the contents.
        raise ConfigurationError(f"Cannot read ANALYST_DB_PASSWORD_FILE ({path}): {exc.strerror or exc}") from exc
    except UnicodeDecodeError as exc:
        raise ConfigurationError(
            f"ANALYST_DB_PASSWORD_FILE ({path}) is not UTF-8 text. "
            "Re-create it as plain UTF-8 (PowerShell's Out-File writes UTF-16 by default)."
        ) from exc


def configured_password(environ: Optional[Mapping[str, str]] = None) -> str:
    """Return the server-side password, or an empty string if none is configured."""
    environ = os.environ if environ is None else environ
    file_path = (environ.get("ANALYST_DB_PASSWORD_FILE") or "").strip()
    if file_path:
        return _read_secret_file(file_path)
    return environ.get("ANALYST_DB_PASSWORD", "")


def password_is_preconfigured(environ: Optional[Mapping[str, str]] = None) -> bool:
    environ = os.environ if environ is None else environ
    return bool((environ.get("ANALYST_DB_PASSWORD_FILE") or "").strip() or environ.get("ANALYST_DB_PASSWORD"))


def password_source(environ: Optional[Mapping[str, str]] = None) -> str:
    """Name of the setting the server-side password comes from ('' when none). Never the value."""
    environ = os.environ if environ is None else environ
    if (environ.get("ANALYST_DB_PASSWORD_FILE") or "").strip():
        return "ANALYST_DB_PASSWORD_FILE"
    if environ.get("ANALYST_DB_PASSWORD"):
        return "ANALYST_DB_PASSWORD"
    return ""


def resolve_db_password(typed: str = "", environ: Optional[Mapping[str, str]] = None) -> str:
    """Server-side secret if present, otherwise what the user typed."""
    return configured_password(environ) or typed
