"""Authentication primitives (no Streamlit imports, standard library only).

* Passwords are stored as salted ``scrypt`` hashes in a JSON users file.
* Failed logins are throttled per username, process-wide.
* ``proxy`` mode trusts a header set by an SSO reverse proxy instead.

The users file looks like::

    {"version": 1, "users": {"alice": {"password_hash": "scrypt$...", "disabled": false}}}
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Optional

from .errors import ConfigurationError

MIN_PASSWORD_LENGTH = 12
_USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._@+-]{0,63}$")

# scrypt cost parameters (32 MiB). Stored inside every hash, so they can be raised later.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SCRYPT_MAXMEM = 128 * 1024 * 1024
_KEY_LEN = 32
_MAX_TRACKED = 10_000


def valid_username(username: str) -> bool:
    return bool(_USERNAME_RE.match(username or ""))


def password_problem(password: str) -> Optional[str]:
    """Return why a password is unacceptable, or None."""
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if password.strip() != password or not password.strip():
        return "Password must not start or end with whitespace."
    return None


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def hash_password(password: str, *, n: int = _SCRYPT_N, r: int = _SCRYPT_R, p: int = _SCRYPT_P) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, maxmem=_SCRYPT_MAXMEM, dklen=_KEY_LEN)
    return f"scrypt${n}${r}${p}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time check of ``password`` against a hash made by ``hash_password``."""
    try:
        scheme, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            maxmem=_SCRYPT_MAXMEM,
            dklen=len(expected),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


@functools.lru_cache(maxsize=1)
def _dummy_hash() -> str:
    """Verified against when the username is unknown, so response time does not reveal valid usernames."""
    return hash_password("not-a-real-password")


@dataclass
class UserStore:
    """The users file. ``load`` reads it; ``save`` writes it atomically with 0600 permissions."""

    path: Path
    users: dict

    @classmethod
    def load(cls, path: str) -> "UserStore":
        file = Path(path)
        if not file.exists():
            return cls(path=file, users={})
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
            users = data["users"]
            if not isinstance(users, dict):
                raise TypeError("'users' must be an object")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ConfigurationError(f"Users file {file} is unreadable or malformed: {exc}") from exc
        return cls(path=file, users=users)

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"version": 1, "users": self.users}, indent=2, sort_keys=True) + "\n"
        fd, tmp_name = tempfile.mkstemp(dir=self.path.parent, prefix=".users-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
            try:
                os.chmod(tmp_name, 0o600)
            except OSError:  # not supported on every platform/filesystem
                pass
            os.replace(tmp_name, self.path)
        except BaseException:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def set_password(self, username: str, password: str) -> None:
        entry = self.users.get(username, {})
        entry["password_hash"] = hash_password(password)
        entry.setdefault("disabled", False)
        self.users[username] = entry

    def active_usernames(self) -> list:
        return sorted(name for name, entry in self.users.items() if not entry.get("disabled"))

    def verify(self, username: str, password: str) -> bool:
        entry = self.users.get(username)
        if not entry or entry.get("disabled"):
            verify_password(password, _dummy_hash())
            return False
        return verify_password(password, str(entry.get("password_hash", "")))


class LoginThrottle:
    """Lock a username for ``lockout_s`` after ``max_attempts`` consecutive failures."""

    def __init__(self, max_attempts: int, lockout_s: float, clock: Callable[[], float] = time.monotonic) -> None:
        self._max = max_attempts
        self._lockout = lockout_s
        self._clock = clock
        self._failures: dict = {}
        self._locked_until: dict = {}
        self._lock = threading.Lock()

    def retry_after(self, username: str) -> float:
        """Seconds until ``username`` may try again (0 if not locked)."""
        key = username.lower()
        with self._lock:
            until = self._locked_until.get(key)
            if until is None:
                return 0.0
            remaining = until - self._clock()
            if remaining <= 0:
                self._locked_until.pop(key, None)
                self._failures.pop(key, None)
                return 0.0
            return remaining

    def record_failure(self, username: str) -> None:
        key = username.lower()
        with self._lock:
            if len(self._failures) > _MAX_TRACKED:  # bound memory under a flood of random usernames
                self._failures = {k: v for k, v in self._failures.items() if k in self._locked_until}
            count = self._failures.get(key, 0) + 1
            self._failures[key] = count
            if count >= self._max:
                self._locked_until[key] = self._clock() + self._lockout

    def record_success(self, username: str) -> None:
        key = username.lower()
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)


@dataclass(frozen=True)
class LoginResult:
    ok: bool
    reason: str  # ok | invalid | locked
    retry_after_s: float = 0.0

    @property
    def message(self) -> str:
        if self.reason == "locked":
            return f"Too many failed attempts. Try again in {max(1, round(self.retry_after_s))} s."
        return "Invalid username or password."


def attempt_login(username: str, password: str, store: UserStore, throttle: LoginThrottle) -> LoginResult:
    """Check credentials, applying the lockout policy. Never reveals which part was wrong."""
    username = (username or "").strip()
    wait = throttle.retry_after(username)
    if wait > 0:
        return LoginResult(False, "locked", wait)
    if valid_username(username) and store.verify(username, password or ""):
        throttle.record_success(username)
        return LoginResult(True, "ok")
    if not valid_username(username):
        verify_password(password or "", _dummy_hash())  # keep timing similar for malformed usernames
    # Unknown, malformed and disabled usernames are throttled too, so lockouts do not reveal valid accounts.
    throttle.record_failure(username)
    return LoginResult(False, "invalid")


def identity_from_headers(headers: Mapping[str, str], header_name: str) -> Optional[str]:
    """Username from a reverse-proxy header (proxy mode). None if absent or implausible."""
    value = None
    try:
        value = headers.get(header_name)
        if value is None:
            wanted = header_name.lower()
            value = next((v for k, v in headers.items() if k.lower() == wanted), None)
    except Exception:  # headers object of an unexpected shape: treat as unauthenticated
        return None
    value = (value or "").strip()
    return value if valid_username(value) else None


def session_expired(last_active: Optional[float], now: float, timeout_min: int) -> bool:
    """True if more than ``timeout_min`` minutes passed since ``last_active``."""
    return last_active is not None and (now - last_active) > timeout_min * 60
