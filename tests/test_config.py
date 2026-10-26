from ai_database_analyst.config import Settings, load_settings


def test_defaults_match_dataclass():
    assert load_settings({}) == Settings()


def test_overrides_apply():
    s = load_settings({"ANALYST_MODEL": " llama3.2:3b ", "ANALYST_DB_PORT": "3307", "ANALYST_MAX_ROWS": "100"})
    assert (s.model, s.db_port, s.max_rows) == ("llama3.2:3b", 3307, 100)


def test_values_are_clamped():
    s = load_settings({"ANALYST_MAX_ROWS": "99999999", "ANALYST_NUM_CTX": "1", "ANALYST_DB_PORT": "0"})
    assert s.max_rows == 5000
    assert s.num_ctx == 2048
    assert s.db_port == 1


def test_invalid_or_blank_values_fall_back():
    s = load_settings({"ANALYST_MAX_ROWS": "lots", "ANALYST_MODEL": "   "})
    assert s.max_rows == Settings().max_rows
    assert s.model == Settings().model


def test_auth_and_audit_defaults_are_secure():
    s = Settings()
    assert s.auth_mode == "local"
    assert s.audit_enabled is True
    assert s.db_ssl_ca == ""


def test_choice_and_bool_overrides():
    s = load_settings({"ANALYST_AUTH_MODE": " PROXY ", "ANALYST_AUDIT_ENABLED": "no", "ANALYST_AUDIT_LOG_QUESTIONS": "0"})
    assert s.auth_mode == "proxy"
    assert s.audit_enabled is False
    assert s.audit_log_questions is False


def test_invalid_choice_or_bool_falls_back_to_secure_default():
    s = load_settings({"ANALYST_AUTH_MODE": "anything-goes", "ANALYST_AUDIT_ENABLED": "maybe"})
    assert s.auth_mode == "local"
    assert s.audit_enabled is True


def test_security_numbers_are_clamped():
    s = load_settings({"ANALYST_MAX_LOGIN_ATTEMPTS": "0", "ANALYST_MAX_QUERIES_PER_MINUTE": "999999"})
    assert s.max_login_attempts == 1
    assert s.max_queries_per_minute == 600
