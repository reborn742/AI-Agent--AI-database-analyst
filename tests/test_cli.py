import json

import pytest

from ai_database_analyst import auth
from ai_database_analyst.cli import main

PASSWORD = "a-long-enough-password"


@pytest.fixture(autouse=True)
def fast_scrypt(monkeypatch):
    original = auth.hash_password
    monkeypatch.setattr(auth, "hash_password", lambda password, **kw: original(password, n=2**10))
    auth._dummy_hash.cache_clear()


def _run(tmp_path, monkeypatch, *args, stdin=PASSWORD + "\n"):
    import io
    import sys

    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    return main(["users", *args, "--file", str(tmp_path / "users.json")])


def test_add_list_passwd_disable_remove_flow(tmp_path, monkeypatch, capsys):
    assert _run(tmp_path, monkeypatch, "add", "alice", "--password-stdin") == 0
    assert _run(tmp_path, monkeypatch, "list") == 0
    assert "alice\tactive" in capsys.readouterr().out

    store = auth.UserStore.load(str(tmp_path / "users.json"))
    assert store.verify("alice", PASSWORD)

    assert _run(tmp_path, monkeypatch, "passwd", "alice", "--password-stdin", stdin="another-long-password\n") == 0
    assert auth.UserStore.load(str(tmp_path / "users.json")).verify("alice", "another-long-password")

    assert _run(tmp_path, monkeypatch, "disable", "alice") == 0
    assert auth.UserStore.load(str(tmp_path / "users.json")).active_usernames() == []
    assert _run(tmp_path, monkeypatch, "enable", "alice") == 0
    assert auth.UserStore.load(str(tmp_path / "users.json")).active_usernames() == ["alice"]

    assert _run(tmp_path, monkeypatch, "remove", "alice") == 0
    assert json.loads((tmp_path / "users.json").read_text())["users"] == {}


def test_add_existing_user_fails(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, "add", "alice", "--password-stdin") == 0
    assert _run(tmp_path, monkeypatch, "add", "alice", "--password-stdin") == 1


def test_bad_username_and_unknown_user(tmp_path, monkeypatch):
    assert _run(tmp_path, monkeypatch, "add", "bad name", "--password-stdin") == 2
    assert _run(tmp_path, monkeypatch, "remove", "ghost") == 1
    assert _run(tmp_path, monkeypatch, "passwd", "ghost", "--password-stdin") == 1


def test_weak_password_is_refused(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(tmp_path, monkeypatch, "add", "alice", "--password-stdin", stdin="short\n")
    assert not (tmp_path / "users.json").exists()


def test_username_required(tmp_path, monkeypatch):
    with pytest.raises(SystemExit):
        _run(tmp_path, monkeypatch, "add")


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as info:
        main(["--version"])
    assert info.value.code == 0
    assert "0." in capsys.readouterr().out


def test_run_launches_streamlit_with_extra_flags(monkeypatch):
    import subprocess
    import sys

    calls = []
    monkeypatch.setattr(subprocess, "call", lambda command: calls.append(command) or 0)
    assert main(["run", "--", "--server.port=9000"]) == 0
    command = calls[0]
    assert command[:4] == [sys.executable, "-m", "streamlit", "run"]
    assert command[4].endswith("streamlit_app.py")
    assert command[5:] == ["--server.port=9000"]
