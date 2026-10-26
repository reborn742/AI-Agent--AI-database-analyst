"""Create ./secrets/*.txt with random passwords (never overwrites existing files).

Used by docker-compose.yml as Docker secrets, so no password lives in an
environment variable, a compose file or version control.

Run:  python scripts/init_secrets.py
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path

SECRETS_DIR = Path(__file__).resolve().parent.parent / "secrets"
NAMES = ("mysql_root_password", "analyst_db_password")


def main() -> None:
    SECRETS_DIR.mkdir(mode=0o700, exist_ok=True)
    for name in NAMES:
        path = SECRETS_DIR / f"{name}.txt"
        if path.exists():
            print(f"kept     {path.relative_to(SECRETS_DIR.parent)}")
            continue
        # Alphanumeric only, so the value is safe inside SQL and shell without quoting.
        alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
        value = "".join(secrets.choice(alphabet) for _ in range(32))
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        # newline="\n": on Windows text mode would write CRLF, and the stray \r would become part of
        # the password inside the MySQL container (the app strips it, MySQL would not).
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value + "\n")
        # Containers run as other users, so the file must be world-readable on the host
        # while the directory stays private to you (0700 above).
        os.chmod(path, 0o644)
        print(f"created  {path.relative_to(SECRETS_DIR.parent)}")


if __name__ == "__main__":
    main()
