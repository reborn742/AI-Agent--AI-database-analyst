"""Regression tests: secret files written on Windows (CRLF, BOM, UTF-16) must not break MySQL login.

The original bug: scripts/init_secrets.py wrote CRLF on Windows, MySQL's init script kept the stray
CR in the account password, the app stripped it, and every login failed with MySQL error 1045.
"""

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import mysql.connector
import pytest

from ai_database_analyst import ui
from ai_database_analyst.credentials import configured_password, password_source
from ai_database_analyst.errors import ConfigurationError

ROOT = Path(__file__).resolve().parent.parent


def _load(path: str):
    spec = importlib.util.spec_from_file_location(Path(path).stem, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_init_secrets_never_writes_carriage_returns(tmp_path, monkeypatch):
    module = _load("scripts/init_secrets.py")
    monkeypatch.setattr(module, "SECRETS_DIR", tmp_path / "secrets")
    module.main()
    files = sorted((tmp_path / "secrets").glob("*.txt"))
    assert [f.name for f in files] == ["analyst_db_password.txt", "mysql_root_password.txt"]
    for file in files:
        data = file.read_bytes()
        assert b"\r" not in data
        assert len(data) == 33 and data.endswith(b"\n")  # 32 characters plus one LF


@pytest.mark.parametrize(
    "raw",
    [b"s3cret-value\n", b"s3cret-value\r\n", b"\xef\xbb\xbfs3cret-value\r\n", b"s3cret-value"],
    ids=["lf", "crlf", "bom+crlf", "no-newline"],
)
def test_password_file_variants_all_yield_the_same_password(tmp_path, raw):
    secret = tmp_path / "pw"
    secret.write_bytes(raw)
    assert configured_password({"ANALYST_DB_PASSWORD_FILE": str(secret)}) == "s3cret-value"


def test_utf16_password_file_gives_an_actionable_error(tmp_path):
    secret = tmp_path / "pw"
    secret.write_bytes("s3cret".encode("utf-16"))  # what PowerShell's Out-File produces
    with pytest.raises(ConfigurationError, match="not UTF-8"):
        configured_password({"ANALYST_DB_PASSWORD_FILE": str(secret)})


def test_password_source_names_the_setting_never_the_value():
    assert password_source({}) == ""
    assert password_source({"ANALYST_DB_PASSWORD": "hunter2"}) == "ANALYST_DB_PASSWORD"
    both = {"ANALYST_DB_PASSWORD": "hunter2", "ANALYST_DB_PASSWORD_FILE": "/run/secrets/x"}
    assert password_source(both) == "ANALYST_DB_PASSWORD_FILE"


def test_rejected_credentials_message_names_source_and_user_without_leaking(monkeypatch):
    monkeypatch.setenv("ANALYST_DB_PASSWORD", "hunter2-secret")
    monkeypatch.delenv("ANALYST_DB_PASSWORD_FILE", raising=False)
    message = ui._database_error_message(mysql.connector.Error("denied", errno=1045))
    assert "ANALYST_DB_PASSWORD" in message and ui.settings.db_user in message
    assert "hunter2-secret" not in message


def test_rejected_typed_password_still_points_at_the_sidebar(monkeypatch):
    monkeypatch.delenv("ANALYST_DB_PASSWORD", raising=False)
    monkeypatch.delenv("ANALYST_DB_PASSWORD_FILE", raising=False)
    message = ui._database_error_message(mysql.connector.Error("denied", errno=1045))
    assert "sidebar" in message


@pytest.mark.skipif(os.name == "nt" or not shutil.which("bash"), reason="needs a POSIX bash")
def test_mysql_init_script_strips_carriage_returns_from_the_secret(tmp_path):
    secret = tmp_path / "analyst_db_password"
    secret.write_bytes(b"AbC123xyz\r\n")
    script = ROOT / "docker" / "mysql-init" / "03_readonly_user.sh"
    # Define docker_process_sql first (as the mysql image does) so it echoes the SQL it would run.
    result = subprocess.run(
        ["bash", "-c", f"docker_process_sql() {{ cat; }}; source '{script}'"],
        env={**os.environ, "ANALYST_DB_PASSWORD_FILE": str(secret)},
        capture_output=True,
        check=True,
    )
    assert b"\r" not in result.stdout
    assert b"IDENTIFIED BY 'AbC123xyz'" in result.stdout
