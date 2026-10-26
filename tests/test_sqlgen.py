import json

from ai_database_analyst import sqlgen
from ai_database_analyst.domain import DomainProfile, SqlExample
from ai_database_analyst.errors import QueryValidationError
from ai_database_analyst.llm import OllamaResult
from ai_database_analyst.models import FollowUp, RetryFeedback


def test_invalid_profile_examples_are_dropped(monkeypatch, schema):
    def fake_validate(sql, schema):
        if "nope" in sql:
            raise QueryValidationError("Unknown table or view: nope", repairable=True)

    monkeypatch.setattr(sqlgen, "validate_sql", fake_validate)
    sqlgen._example_cache.clear()
    profile = DomainProfile(
        sql_examples=(SqlExample("good", "SELECT 1 FROM orders"), SqlExample("bad", "SELECT * FROM nope"))
    )
    usable = sqlgen.usable_examples(profile, schema)
    assert [e.question for e in usable] == ["good"]


def test_generate_sql_sends_feedback_and_followup(monkeypatch, schema):
    prompts = []

    def fake(prompt, **kwargs):
        prompts.append(prompt)
        return OllamaResult(json.dumps({"sql": "SELECT 1"}), "stop", 0.1, None, None, None)

    monkeypatch.setattr(sqlgen, "call_ollama", fake)
    sql = sqlgen.generate_sql(
        "and for Europe?",
        schema,
        feedback=RetryFeedback("SELECT bad FROM orders", "Unknown column 'bad'"),
        followup=FollowUp("top products", "SELECT product_name FROM completed_sales"),
    )
    assert sql == "SELECT 1"
    prompt = prompts[0]
    assert "YOUR PREVIOUS ATTEMPT FAILED" in prompt
    assert "Unknown column 'bad'" in prompt
    assert "PREVIOUS QUESTION IN THIS CONVERSATION" in prompt
    assert "top products" in prompt
    assert "and for Europe?" in prompt
