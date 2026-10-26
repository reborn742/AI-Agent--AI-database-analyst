import pytest

from ai_database_analyst.credentials import configured_password, password_is_preconfigured, resolve_db_password
from ai_database_analyst.errors import ConfigurationError


def test_nothing_configured_falls_back_to_typed_value():
    assert configured_password({}) == ""
    assert not password_is_preconfigured({})
    assert resolve_db_password("typed", {}) == "typed"


def test_env_variable():
    env = {"ANALYST_DB_PASSWORD": "from-env"}
    assert password_is_preconfigured(env)
    assert resolve_db_password("typed", env) == "from-env"


def test_secret_file_wins_over_env_and_strips_newline(tmp_path):
    secret = tmp_path / "db_password"
    secret.write_text("from-file\n")
    env = {"ANALYST_DB_PASSWORD_FILE": str(secret), "ANALYST_DB_PASSWORD": "from-env"}
    assert resolve_db_password("typed", env) == "from-file"


def test_unreadable_secret_file_raises_without_leaking_anything(tmp_path):
    env = {"ANALYST_DB_PASSWORD_FILE": str(tmp_path / "missing")}
    with pytest.raises(ConfigurationError) as info:
        configured_password(env)
    assert "missing" in str(info.value)


def test_blank_file_variable_is_ignored():
    assert not password_is_preconfigured({"ANALYST_DB_PASSWORD_FILE": "  "})
