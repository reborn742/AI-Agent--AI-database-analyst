import pandas as pd
import pytest

from ai_database_analyst import service
from ai_database_analyst.errors import ConfigurationError, QueryValidationError, RateLimitError
from ai_database_analyst.models import AnalysisRun, FollowUp
from ai_database_analyst.ratelimit import RateLimiter

audit_mod = service.audit_log


@pytest.fixture
def events(monkeypatch):
    captured = []
    monkeypatch.setattr(service, "audit", lambda event, user=None, **fields: captured.append((event, user, fields)))
    monkeypatch.setattr(service, "_limiter", RateLimiter(2, 60))
    return captured


def _run_ok():
    frame = pd.DataFrame({"a": [1, 2, 3]})
    return AnalysisRun(
        question="q", sql="SELECT 1", results=frame, analysis=frame, csv=b"", query_seconds=0.5, insights=[], scope_note=""
    )


def test_success_is_audited_with_user_and_sql(monkeypatch, events):
    monkeypatch.setattr(service, "run_analysis", lambda q, p, stage=None, followup=None: _run_ok())
    run = service.run_audited("top products", "pw", user="alice", session_id="s1")
    assert run.sql == "SELECT 1"
    event, user, fields = events[0]
    assert (event, user) == (audit_mod.QUERY_OK, "alice")
    assert fields["question"] == "top products"
    assert fields["rows"] == 3
    assert fields["session"] == "s1"
    assert "pw" not in repr(events)


def test_rejection_is_audited_and_reraised(monkeypatch, events):
    def reject(q, p, stage=None, followup=None):
        exc = QueryValidationError("Only SELECT statements are allowed.")
        exc.generated_sql = "DROP TABLE orders"
        raise exc

    monkeypatch.setattr(service, "run_analysis", reject)
    with pytest.raises(QueryValidationError):
        service.run_audited("drop it", "pw", user="mallory")
    event, user, fields = events[0]
    assert (event, user) == (audit_mod.QUERY_REJECTED, "mallory")
    assert fields["sql"] == "DROP TABLE orders"


def test_unexpected_error_is_audited_without_message_text(monkeypatch, events):
    class FakeDbError(Exception):
        errno = 1045

    def fail(q, p, stage=None, followup=None):
        raise FakeDbError("Access denied for user 'x' using password: YES")

    monkeypatch.setattr(service, "run_analysis", fail)
    with pytest.raises(FakeDbError):
        service.run_audited("q", "pw", user="alice")
    event, _user, fields = events[0]
    assert event == audit_mod.QUERY_ERROR
    assert fields["error_type"] == "FakeDbError"
    assert fields["error_code"] == 1045
    assert "Access denied" not in repr(fields)


def test_rate_limit_blocks_before_running_and_is_audited(monkeypatch, events):
    calls = []
    monkeypatch.setattr(service, "run_analysis", lambda q, p, stage=None, followup=None: calls.append(q) or _run_ok())
    service.run_audited("1", "pw", user="alice")
    service.run_audited("2", "pw", user="alice")
    with pytest.raises(RateLimitError) as info:
        service.run_audited("3", "pw", user="alice")
    assert info.value.retry_after_s > 0
    assert calls == ["1", "2"]
    assert events[-1][0] == audit_mod.RATE_LIMITED
    service.run_audited("1", "pw", user="bob")  # other users are unaffected


def test_startup_problems_local_mode_without_users(tmp_path, monkeypatch):
    cfg = service.settings.__class__(users_file=str(tmp_path / "none.json"), audit_enabled=False)
    monkeypatch.setattr(service, "settings", cfg)
    monkeypatch.setattr(audit_mod, "settings", cfg)
    problems = service.startup_problems()
    assert len(problems) == 1 and "No users are configured" in problems[0]


def test_startup_problems_reports_malformed_users_file(tmp_path, monkeypatch):
    bad = tmp_path / "users.json"
    bad.write_text("nope")
    cfg = service.settings.__class__(users_file=str(bad), audit_enabled=False)
    monkeypatch.setattr(service, "settings", cfg)
    monkeypatch.setattr(audit_mod, "settings", cfg)
    assert "malformed" in service.startup_problems()[0]


def test_startup_ok_in_none_mode(monkeypatch):
    cfg = service.settings.__class__(auth_mode="none", audit_enabled=False)
    monkeypatch.setattr(service, "settings", cfg)
    monkeypatch.setattr(audit_mod, "settings", cfg)
    assert service.startup_problems() == []


def test_configuration_error_is_exported():
    assert issubclass(ConfigurationError, Exception)


def test_followup_and_attempts_are_audited(monkeypatch, events):
    seen = []

    def fake(q, p, stage=None, followup=None):
        seen.append(followup)
        run = _run_ok()
        run.attempts = 2
        return run

    monkeypatch.setattr(service, "run_analysis", fake)
    context = FollowUp("earlier question", "SELECT 1")
    service.run_audited("and for Europe?", "pw", user="alice", followup=context)
    assert seen == [context]
    fields = events[0][2]
    assert fields["attempts"] == 2
    assert fields["followup"] is True


def test_startup_reports_bad_domain_profile(tmp_path, monkeypatch):
    bad = tmp_path / "domain.yaml"
    bad.write_text("not_a_real_key: 1\n")
    from ai_database_analyst import domain

    cfg = service.settings.__class__(auth_mode="none", audit_enabled=False, domain_file=str(bad))
    monkeypatch.setattr(service, "settings", cfg)
    monkeypatch.setattr(audit_mod, "settings", cfg)
    monkeypatch.setattr(domain, "settings", cfg)
    problems = service.startup_problems()
    assert any("unknown key" in p for p in problems)
