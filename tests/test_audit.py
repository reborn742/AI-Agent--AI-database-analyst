import hashlib
import json

import pytest

from ai_database_analyst import audit as audit_mod
from ai_database_analyst.audit import AuditLog


@pytest.fixture
def log(tmp_path):
    instance = AuditLog(str(tmp_path / "logs" / "audit.jsonl"), max_bytes=1_000_000, backup_count=2)
    yield instance
    instance.close()


def _lines(log):
    return [json.loads(line) for line in log.path.read_text(encoding="utf-8").splitlines()]


def test_records_one_json_object_per_event(log):
    log.record(audit_mod.QUERY_OK, "alice", question="top products", sql="SELECT 1", rows=3)
    log.record(audit_mod.LOGOUT, "alice")
    first, second = _lines(log)
    assert first["event"] == "query_ok"
    assert first["user"] == "alice"
    assert first["question"] == "top products"
    assert first["rows"] == 3
    assert first["ts"].endswith("+00:00")
    assert second["event"] == "logout"


def test_sensitive_fields_are_dropped(log):
    log.record(audit_mod.LOGIN_SUCCESS, "alice", password="hunter2", db_password="x", api_token="t", session="s1")
    (entry,) = _lines(log)
    assert "password" not in entry and "db_password" not in entry and "api_token" not in entry
    assert entry["session"] == "s1"
    assert "hunter2" not in log.path.read_text()


def test_none_values_are_omitted_and_missing_user_is_dash(log):
    log.record(audit_mod.QUERY_ERROR, None, error_code=None, error_type="OllamaTimeoutError")
    (entry,) = _lines(log)
    assert entry["user"] == "-"
    assert "error_code" not in entry


def test_long_text_is_truncated(log):
    log.record(audit_mod.QUERY_REJECTED, "alice", sql="x" * 5000)
    (entry,) = _lines(log)
    assert len(entry["sql"]) < 2100
    assert entry["sql"].endswith("[truncated]")


def test_question_can_be_hashed_instead_of_stored(tmp_path):
    instance = AuditLog(str(tmp_path / "a.jsonl"), max_bytes=1_000_000, backup_count=1, log_questions=False)
    try:
        instance.record(audit_mod.QUERY_OK, "alice", question="secret merger revenue")
    finally:
        instance.close()
    text = (tmp_path / "a.jsonl").read_text()
    entry = json.loads(text)
    assert "question" not in entry
    assert entry["question_sha256"] == hashlib.sha256(b"secret merger revenue").hexdigest()
    assert "merger" not in text


def test_unicode_is_preserved(log):
    log.record(audit_mod.QUERY_OK, "zoë", question="Quelle région a vendu le plus ? 日本")
    (entry,) = _lines(log)
    assert entry["question"].endswith("日本")


def test_file_rotates(tmp_path):
    instance = AuditLog(str(tmp_path / "r.jsonl"), max_bytes=500, backup_count=2)
    try:
        for i in range(40):
            instance.record(audit_mod.QUERY_OK, "alice", question=f"question number {i}", rows=i)
    finally:
        instance.close()
    assert (tmp_path / "r.jsonl.1").exists()


def test_audit_never_raises_when_unwritable(monkeypatch):
    def boom():
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(audit_mod, "get_audit_log", boom)
    audit_mod.audit(audit_mod.LOGOUT, "alice")  # must not raise


def test_disabled_audit_is_a_noop_and_not_a_problem(monkeypatch):
    monkeypatch.setattr(audit_mod, "settings", audit_mod.settings.__class__(audit_enabled=False))
    monkeypatch.setattr(audit_mod, "_instance", None)
    assert audit_mod.get_audit_log() is None
    assert audit_mod.audit_problem() is None
    audit_mod.audit(audit_mod.LOGOUT, "alice")
