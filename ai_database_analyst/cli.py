"""Command line interface.

    python -m ai_database_analyst run                 start the web app
    python -m ai_database_analyst check               verify MySQL and Ollama connectivity
    python -m ai_database_analyst users add alice     manage who can sign in
"""

from __future__ import annotations

import argparse
import getpass
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

from . import __version__
from .auth import UserStore, password_problem, valid_username
from .config import settings
from .credentials import password_source, resolve_db_password
from .errors import ConfigurationError


def _read_new_password(from_stdin: bool) -> str:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("New password: ")
        if password != getpass.getpass("Repeat password: "):
            raise SystemExit("Passwords do not match.")
    problem = password_problem(password)
    if problem:
        raise SystemExit(problem)
    return password


def _cmd_run(args: argparse.Namespace) -> int:
    app = Path(__file__).with_name("streamlit_app.py")
    extra = list(args.streamlit_args)
    if extra[:1] == ["--"]:  # argparse keeps a leading "--"; Streamlit would treat what follows as script arguments
        extra = extra[1:]
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app), *extra])


def _cmd_users(args: argparse.Namespace) -> int:
    path = args.file or settings.users_file
    try:
        store = UserStore.load(path)
    except ConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.action == "list":
        if not store.users:
            print(f"No users in {path}.")
        for name, entry in sorted(store.users.items()):
            print(f"{name}\t{'disabled' if entry.get('disabled') else 'active'}")
        return 0

    name = args.username
    if args.action in ("add", "passwd"):
        if not valid_username(name):
            print("Usernames: letters, digits and . _ @ + - only (max 64 characters).", file=sys.stderr)
            return 2
        exists = name in store.users
        if args.action == "add" and exists:
            print(f"User '{name}' already exists. Use 'passwd' to change the password.", file=sys.stderr)
            return 1
        if args.action == "passwd" and not exists:
            print(f"No such user: {name}", file=sys.stderr)
            return 1
        store.set_password(name, _read_new_password(args.password_stdin))
        store.save()
        print(f"{'Added' if args.action == 'add' else 'Updated'} user '{name}' in {path}.")
        return 0

    if name not in store.users:
        print(f"No such user: {name}", file=sys.stderr)
        return 1
    if args.action == "remove":
        del store.users[name]
    else:
        store.users[name]["disabled"] = args.action == "disable"
    store.save()
    print(f"{args.action.capitalize()}d user '{name}'." if args.action != "remove" else f"Removed user '{name}'.")
    return 0


def _cmd_check(_args: argparse.Namespace) -> int:
    import requests

    from .db import connect_db, get_schema
    from .errors import MissingCredentialsError

    failures = 0
    schema = None
    print(f"MySQL   {settings.db_user}@{settings.db_host}:{settings.db_port}/{settings.db_name}")
    try:
        source = password_source()
        print(f"  password source: {source or 'prompt'}")
        password = resolve_db_password() or getpass.getpass("  password: ")
        connect_db(password).close()
        schema = get_schema(password)
        print(f"  OK: {len(schema.tables)} tables/views readable: {', '.join(sorted(schema.tables))}")
    except (MissingCredentialsError, ConfigurationError) as exc:
        failures += 1
        print(f"  FAIL: {exc}")
    except Exception as exc:  # connector errors, DNS failures, etc.
        failures += 1
        print(f"  FAIL: {type(exc).__name__}: {getattr(exc, 'msg', exc)}")
        if getattr(exc, "errno", None) == 1045:
            print(
                "  hint: the password was rejected. If it comes from ANALYST_DB_PASSWORD_FILE / "
                "ANALYST_DB_PASSWORD, make sure it is the password of this MySQL account."
            )

    print(f"Profile {settings.domain_file or '(none: generic mode)'}")
    try:
        from .domain import get_profile
        from .sqlgen import usable_examples

        profile = get_profile()
        print(
            f"  OK: '{profile.title}'; {len(profile.preferred_sources)} preferred sources, "
            f"{len(profile.metrics)} metrics, {len(profile.glossary)} glossary terms"
        )
        if schema is not None and profile.sql_examples:
            usable = usable_examples(profile, schema)
            dropped = len(profile.sql_examples) - len(usable)
            if dropped:
                failures += 1
                total = len(profile.sql_examples)
                print(f"  FAIL: {dropped} of {total} sql_examples fail validation on the live schema")
            else:
                print(f"  OK: all {len(usable)} sql_examples validate against the live schema")
        if schema is not None:
            missing = [src.name for src in profile.preferred_sources if src.name.lower() not in schema.tables]
            if missing:
                failures += 1
                print(f"  FAIL: preferred_sources not found (or hidden): {', '.join(missing)}")
    except ConfigurationError as exc:
        failures += 1
        print(f"  FAIL: {exc}")

    tags_url = settings.ollama_url.replace("/api/generate", "/api/tags")
    print(f"Ollama  {tags_url} (model {settings.model})")
    try:
        response = requests.get(tags_url, timeout=settings.ollama_connect_timeout_s)
        response.raise_for_status()
        names = {m.get("name") for m in response.json().get("models", [])}
        if settings.model in names or f"{settings.model}:latest" in names:
            print("  OK: model is available")
        else:
            failures += 1
            print(f"  FAIL: model not pulled. Run: ollama pull {settings.model}")
    except Exception as exc:
        failures += 1
        print(f"  FAIL: {type(exc).__name__}: {exc}")
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-database-analyst", description=__doc__.split("\n")[0])
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="start the web app")
    run.add_argument("streamlit_args", nargs=argparse.REMAINDER, help="extra arguments passed to 'streamlit run'")
    run.set_defaults(func=_cmd_run)

    check = sub.add_parser("check", help="verify MySQL and Ollama connectivity")
    check.set_defaults(func=_cmd_check)

    users = sub.add_parser("users", help="manage local sign-in accounts")
    users.add_argument("action", choices=["add", "passwd", "remove", "disable", "enable", "list"])
    users.add_argument("username", nargs="?")
    users.add_argument("--file", help="users file (default: ANALYST_USERS_FILE)")
    users.add_argument("--password-stdin", action="store_true", help="read the password from stdin (automation)")
    users.set_defaults(func=_cmd_users)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "users" and args.action != "list" and not args.username:
        parser.error(f"users {args.action} requires a username")
    return args.func(args)
