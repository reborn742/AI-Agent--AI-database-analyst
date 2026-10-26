import os
from pathlib import Path

import pytest

from ai_database_analyst import domain
from ai_database_analyst.domain import DomainProfile, get_profile, load_profile, parse_profile
from ai_database_analyst.errors import ConfigurationError
from ai_database_analyst.schema import SENSITIVE_COLUMN_PATTERNS

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def test_default_profile_is_generic_and_hides_secrets():
    profile = DomainProfile()
    assert profile.preferred_sources == () and profile.rules == ()
    assert profile.hidden_columns == SENSITIVE_COLUMN_PATTERNS
    assert get_profile("") == profile


def test_full_profile_parses():
    profile = parse_profile(
        {
            "title": " Finance ",
            "organization": "Acme",
            "description": "Money data.",
            "preferred_sources": [{"name": "invoices", "use_for": "revenue"}],
            "rules": ["Amounts are EUR."],
            "glossary": {"ARR": "annual recurring revenue"},
            "metrics": {"revenue": "SUM(net)"},
            "tables": {"Invoices": "One row per invoice"},
            "columns": {"Invoices.Status": "draft, sent, paid"},
            "examples": ["Revenue by month?"],
            "sql_examples": [{"question": "Q", "sql": "SELECT 1 FROM invoices;"}],
            "hidden_tables": ["audit_*"],
            "hidden_columns": ["customers.email"],
        }
    )
    assert profile.title == "Finance"
    assert profile.preferred_sources[0].name == "invoices"
    assert profile.glossary == (("ARR", "annual recurring revenue"),)
    assert profile.table_descriptions == {"invoices": "One row per invoice"}
    assert profile.column_descriptions == {("invoices", "status"): "draft, sent, paid"}
    assert profile.sql_examples[0].sql == "SELECT 1 FROM invoices"
    assert profile.hidden_columns[0] == "customers.email"
    assert set(SENSITIVE_COLUMN_PATTERNS) <= set(profile.hidden_columns)


def test_sensitive_defaults_can_be_switched_off():
    profile = parse_profile({"hide_sensitive_defaults": False, "hidden_columns": ["a.b"]})
    assert profile.hidden_columns == ("a.b",)


@pytest.mark.parametrize(
    "data, fragment",
    [
        ({"titel": "typo"}, "unknown key"),
        ({"title": 5}, "must be text"),
        ({"title": "x" * 500}, "too long"),
        ({"rules": "not a list"}, "list of text"),
        ({"rules": ["x"] * 99}, "too many"),
        ({"glossary": ["a"]}, "mapping"),
        ({"columns": {"nodot": "x"}}, "table.column"),
        ({"preferred_sources": [{"use_for": "x"}]}, "name"),
        ({"sql_examples": [{"question": "q"}]}, "sql"),
        ({"sql_examples": [{"question": "q", "sql": "s"}] * 6}, "at most 5"),
        (["a list"], "mapping"),
    ],
)
def test_invalid_profiles_give_precise_errors(data, fragment):
    with pytest.raises(ConfigurationError) as info:
        parse_profile(data, "domain.yaml")
    assert fragment in str(info.value)
    assert "domain.yaml" in str(info.value)


def test_empty_file_is_a_valid_generic_profile(tmp_path):
    file = tmp_path / "d.yaml"
    file.write_text("")
    assert load_profile(str(file)).title == DomainProfile().title


def test_missing_and_malformed_files(tmp_path):
    with pytest.raises(ConfigurationError):
        load_profile(str(tmp_path / "absent.yaml"))
    with pytest.raises(ConfigurationError):
        get_profile(str(tmp_path / "absent.yaml"))
    bad = tmp_path / "bad.yaml"
    bad.write_text("title: [unclosed")
    with pytest.raises(ConfigurationError) as info:
        load_profile(str(bad))
    assert "not valid YAML" in str(info.value)


def test_edits_are_picked_up_without_restart(tmp_path):
    file = tmp_path / "d.yaml"
    file.write_text("title: First\n")
    assert get_profile(str(file)).title == "First"
    file.write_text("title: Second\n")
    stat = file.stat()
    os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns + 5_000_000_000))
    assert get_profile(str(file)).title == "Second"


def test_profile_is_cached_between_calls(tmp_path, monkeypatch):
    file = tmp_path / "d.yaml"
    file.write_text("title: Cached\n")
    get_profile(str(file))
    calls = []
    monkeypatch.setattr(domain, "load_profile", lambda path: calls.append(path))
    assert get_profile(str(file)).title == "Cached"
    assert calls == []


def test_every_shipped_profile_is_valid():
    files = sorted(CONFIG_DIR.rglob("*.yaml"))
    assert len(files) >= 5
    for file in files:
        profile = load_profile(str(file))
        assert profile.title, file
