from decimal import Decimal

import pandas as pd

from ai_database_analyst.analysis import (
    build_deterministic_insights,
    build_result_profile,
    describe_scope,
    fmt_number,
    to_analysis_frame,
)
from ai_database_analyst.config import settings
from ai_database_analyst.validation import ValidatedQuery


def _frame():
    return pd.DataFrame(
        {
            "product_name": ["A", "B", "C"],
            "units_sold": [Decimal("10"), Decimal("7"), Decimal("7")],
        }
    )


def test_decimal_columns_become_numeric():
    out = to_analysis_frame(_frame())
    assert pd.api.types.is_numeric_dtype(out["units_sold"])
    assert out["units_sold"].tolist() == [10.0, 7.0, 7.0]


def test_fmt_number():
    assert fmt_number(1234.0) == "1,234"
    assert fmt_number(1234.5) == "1,234.50"
    assert fmt_number(float("nan")) == "n/a"


def test_ranked_insights():
    insights = build_deterministic_insights("top products", to_analysis_frame(_frame()))
    assert insights[0].startswith("Highest returned value: 10 in units_sold for A")
    assert any("Gap" in i and "3" in i for i in insights)
    assert any("Sum of the 3 returned rows" in i and "24" in i for i in insights)


def test_no_insights_without_ranking_question():
    assert build_deterministic_insights("list products", to_analysis_frame(_frame())) == []


def test_profile_has_sum_for_metric_columns():
    profile = build_result_profile(to_analysis_frame(_frame()), 15)
    assert profile["rows_returned"] == 3
    assert profile["numeric_metrics"]["units_sold"]["sum_of_returned_rows"] == 24.0


def test_scope_descriptions():
    cap = settings.max_rows
    assert "limits output to 5" in describe_scope(ValidatedQuery("x", 5, False), 5)
    assert "capped" in describe_scope(ValidatedQuery("x", None, True), cap)
    assert "all rows" in describe_scope(ValidatedQuery("x", None, True), 10)
