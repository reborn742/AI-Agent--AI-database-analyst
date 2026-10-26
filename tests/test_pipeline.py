import dataclasses
import json

import mysql.connector
import pandas as pd
import pytest

from ai_database_analyst import pipeline, sqlgen
from ai_database_analyst.db import connect_db
from ai_database_analyst.errors import (
    MissingCredentialsError,
    QueryValidationError,
    SQLGenerationError,
)
from ai_database_analyst.llm import OllamaResult


def _fake_llm(sql):
    def fake(prompt, **kwargs):
        return OllamaResult(json.dumps({"sql": sql}), "stop", 0.1, None, None, None)

    return fake


@pytest.fixture
def wired(monkeypatch, schema):
    monkeypatch.setattr(pipeline, "get_schema", lambda password: schema)
    executed = []

    def fake_run_query(sql, password):
        executed.append(sql)
        return pd.DataFrame({"product_name": ["A", "B"], "units_sold": [10, 7]}), 0.01

    monkeypatch.setattr(pipeline, "run_query", fake_run_query)
    return executed


def test_happy_path(monkeypatch, wired):
    monkeypatch.setattr(sqlgen, "call_ollama", _fake_llm("SELECT product_name, SUM(quantity) units_sold FROM completed_sales GROUP BY product_name"))
    stages = []

    class Stage:
        def __init__(self, message):
            stages.append(message)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    run = pipeline.run_analysis("Which products sold the most?", "pw", stage=Stage)
    assert len(stages) == 4
    assert wired and "LIMIT" in wired[0]
    assert run.explanation_status == "pending"
    assert run.insights  # ranked question + recognisable columns
    assert run.csv.startswith(b"\xef\xbb\xbf")


def test_rejected_sql_is_not_executed_and_is_attached(monkeypatch, wired):
    monkeypatch.setattr(sqlgen, "call_ollama", _fake_llm("DROP TABLE orders"))
    with pytest.raises(QueryValidationError) as info:
        pipeline.run_analysis("anything", "pw")
    assert info.value.generated_sql == "DROP TABLE orders"
    assert wired == []


def test_empty_result_gets_static_explanation(monkeypatch, schema):
    monkeypatch.setattr(pipeline, "get_schema", lambda password: schema)
    monkeypatch.setattr(pipeline, "run_query", lambda sql, password: (pd.DataFrame({"a": []}), 0.0))
    monkeypatch.setattr(sqlgen, "call_ollama", _fake_llm("SELECT region FROM completed_sales"))
    run = pipeline.run_analysis("q", "pw")
    assert run.explanation_status == "static"


def test_model_returning_bad_json(monkeypatch, wired):
    monkeypatch.setattr(
        sqlgen, "call_ollama", lambda prompt, **kw: OllamaResult("not json", "stop", 0.1, None, None, None)
    )
    with pytest.raises(SQLGenerationError):
        pipeline.run_analysis("q", "pw")


def test_missing_password():
    with pytest.raises(MissingCredentialsError):
        connect_db("")


# --- self-repair ---------------------------------------------------------------------------------


class _Db(mysql.connector.Error):
    def __init__(self, errno, msg):
        super().__init__()
        self.errno = errno
        self.msg = msg


def _repair_rig(monkeypatch, schema, *, sqls, reject=(), db_errors=()):
    """Fake generator/validator/database so retry logic is tested without a model or MySQL."""
    from ai_database_analyst.validation import ValidatedQuery

    monkeypatch.setattr(pipeline, "get_schema", lambda password: schema)
    generated, feedbacks, executed = [], [], []
    queue = list(sqls)

    def fake_generate(question, schema, feedback=None, followup=None):
        feedbacks.append(feedback)
        sql = queue.pop(0)
        generated.append(sql)
        return sql

    def fake_validate(sql, schema):
        if sql in reject:
            raise QueryValidationError(f"rejected: {sql}", repairable=sql.startswith("fixable"))
        return ValidatedQuery(sql=sql + " LIMIT 500", original_limit=None, cap_applied=True)

    errors = list(db_errors)

    def fake_run(sql, password):
        executed.append(sql)
        if errors:
            raise errors.pop(0)
        return pd.DataFrame({"a": [1]}), 0.01

    monkeypatch.setattr(pipeline, "generate_sql", fake_generate)
    monkeypatch.setattr(pipeline, "validate_sql", fake_validate)
    monkeypatch.setattr(pipeline, "run_query", fake_run)
    return generated, feedbacks, executed


def test_fixable_validation_error_is_retried_with_feedback(monkeypatch, schema):
    generated, feedbacks, executed = _repair_rig(
        monkeypatch, schema, sqls=["fixable bad", "good"], reject={"fixable bad"}
    )
    run = pipeline.run_analysis("q", "pw")
    assert run.attempts == 2
    assert generated == ["fixable bad", "good"]
    assert feedbacks[0] is None
    assert feedbacks[1].sql == "fixable bad" and "rejected" in feedbacks[1].problem
    assert executed == ["good LIMIT 500"]


def test_safety_violations_are_never_retried(monkeypatch, schema):
    generated, _, executed = _repair_rig(monkeypatch, schema, sqls=["DROP TABLE x", "unused"], reject={"DROP TABLE x"})
    with pytest.raises(QueryValidationError) as info:
        pipeline.run_analysis("q", "pw")
    assert generated == ["DROP TABLE x"]
    assert info.value.generated_sql == "DROP TABLE x"
    assert executed == []


def test_retries_are_bounded(monkeypatch, schema):
    generated, _, _ = _repair_rig(
        monkeypatch, schema, sqls=["fixable 1", "fixable 2", "fixable 3"], reject={"fixable 1", "fixable 2", "fixable 3"}
    )
    with pytest.raises(QueryValidationError) as info:
        pipeline.run_analysis("q", "pw")
    assert len(generated) == 1 + pipeline.settings.sql_retries
    assert info.value.generated_sql == generated[-1]


def test_retries_can_be_disabled(monkeypatch, schema):
    monkeypatch.setattr(pipeline, "settings", dataclasses.replace(pipeline.settings, sql_retries=0))
    generated, _, _ = _repair_rig(monkeypatch, schema, sqls=["fixable 1", "unused"], reject={"fixable 1"})
    with pytest.raises(QueryValidationError):
        pipeline.run_analysis("q", "pw")
    assert generated == ["fixable 1"]


def test_malformed_query_error_from_mysql_is_retried(monkeypatch, schema):
    generated, feedbacks, executed = _repair_rig(
        monkeypatch, schema, sqls=["first", "second"], db_errors=[_Db(1054, "Unknown column 'x' in 'field list'")]
    )
    run = pipeline.run_analysis("q", "pw")
    assert run.attempts == 2
    assert "Unknown column 'x'" in feedbacks[1].problem
    assert executed == ["first LIMIT 500", "second LIMIT 500"]


def test_operational_mysql_errors_are_not_retried(monkeypatch, schema):
    generated, _, _ = _repair_rig(monkeypatch, schema, sqls=["first", "unused"], db_errors=[_Db(1045, "Access denied")])
    with pytest.raises(mysql.connector.Error):
        pipeline.run_analysis("q", "pw")
    assert generated == ["first"]


def test_followup_is_passed_to_the_generator(monkeypatch, schema):
    from ai_database_analyst.models import FollowUp

    seen = []
    _repair_rig(monkeypatch, schema, sqls=["good"])
    monkeypatch.setattr(
        pipeline, "generate_sql", lambda question, schema, feedback=None, followup=None: seen.append(followup) or "good"
    )
    context = FollowUp("earlier", "SELECT 1")
    pipeline.run_analysis("and now?", "pw", followup=context)
    assert seen == [context]
