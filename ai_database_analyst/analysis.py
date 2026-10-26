"""Deterministic analysis: facts computed by Python, never by the model."""

from __future__ import annotations

import re
from decimal import Decimal

import pandas as pd

from .config import settings
from .validation import ValidatedQuery

_METRIC_NAME = (
    r"(revenue|profit|quantity|units|amount|sales|orders|count|expense|spend|salary|hours|income"
    r"|budget|headcount|tickets|invoices|total)"
)
_AVG_NAME = r"(revenue|profit|quantity|units|amount|sales|orders|count|price|cost|margin|discount)"
_RANK_METRIC = (
    r"(units|quantity|revenue|gross_profit|profit|sales|amount|order_count|customer_count|total_count|count"
    r"|expense|spend|salary|hours|income|budget|headcount|tickets|invoices|total)"
)


def to_analysis_frame(results: pd.DataFrame) -> pd.DataFrame:
    """Copy of the results with DECIMAL columns as floats, for analysis and charts only.

    MySQL returns DECIMAL (SUM/AVG of money) as Decimal objects, which pandas
    treats as non-numeric. The displayed table and CSV keep the original values.
    """
    frame = results.copy()
    for column in frame.columns:
        series = frame[column]
        if pd.api.types.is_object_dtype(series):
            non_null = series.dropna()
            if len(non_null) and all(isinstance(v, Decimal) for v in non_null):
                frame[column] = pd.to_numeric(
                    series.map(lambda v: float(v) if isinstance(v, Decimal) else v),
                    errors="coerce",
                )
    return frame


def fmt_number(value: float) -> str:
    if pd.isna(value):
        return "n/a"
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.2f}"


def build_result_profile(analysis: pd.DataFrame, preview_rows: int) -> dict:
    """Small deterministic facts computed over ALL returned rows."""
    profile: dict = {
        "rows_returned": int(len(analysis)),
        "rows_shown_in_preview": int(min(len(analysis), preview_rows)),
        "columns": [str(c) for c in analysis.columns][:settings.explain_max_columns],
        "numeric_metrics": {},
    }
    if analysis.empty:
        return profile

    numeric_columns = analysis.select_dtypes(include="number").columns[:settings.explain_max_columns]
    for column in numeric_columns:
        series = pd.to_numeric(analysis[column], errors="coerce").dropna()
        if series.empty:
            continue
        name = str(column).lower()
        stats = {
            "non_null_values": int(series.count()),
            "minimum": round(float(series.min()), 4),
            "maximum": round(float(series.max()), 4),
        }
        if re.search(_METRIC_NAME, name):
            stats["sum_of_returned_rows"] = round(float(series.sum()), 4)
        if re.search(_AVG_NAME, name):
            stats["average"] = round(float(series.mean()), 4)
        if len(series) >= 2 and re.search(_METRIC_NAME, name):
            stats["first_row_minus_second_row"] = round(float(series.iloc[0] - series.iloc[1]), 4)
        profile["numeric_metrics"][str(column)] = stats
    return profile


def build_deterministic_insights(question: str, analysis: pd.DataFrame) -> list:
    """Reproducible facts for recognizable ranked results (no duplicates)."""
    if analysis.empty or not re.search(
        r"\b(top|most|highest|best|leading|rank(?:ed|ing)?)\b", question, re.I
    ):
        return []

    metric_column = None
    for column in analysis.columns:
        if re.search(_RANK_METRIC, str(column).lower()) and pd.api.types.is_numeric_dtype(analysis[column]):
            metric_column = column
            break
    if metric_column is None:
        return []

    entity_column = None
    preferred = (
        "product_name", "item_name", "category_name", "customer_name", "store_name",
        "sales_channel", "region", "category", "product", "name",
        "employee_name", "department", "department_name", "account_name", "vendor_name", "supplier_name",
        "project_name", "team", "team_name", "segment", "status", "city", "country",
    )
    for preferred_name in preferred:
        for column in analysis.columns:
            if str(column).lower() == preferred_name and not pd.api.types.is_numeric_dtype(analysis[column]):
                entity_column = column
                break
        if entity_column is not None:
            break
    if entity_column is None:
        return []

    ranked = analysis[[entity_column, metric_column]].copy()
    ranked[metric_column] = pd.to_numeric(ranked[metric_column], errors="coerce")
    ranked = ranked.dropna(subset=[metric_column]).sort_values(metric_column, ascending=False)
    if ranked.empty:
        return []

    insights = []
    best_value = float(ranked.iloc[0][metric_column])
    leaders = ranked.loc[ranked[metric_column] == best_value, entity_column].astype(str).tolist()
    if len(leaders) > 1:
        insights.append(
            f"Highest returned value: {fmt_number(best_value)} in {metric_column}; tied between {', '.join(leaders)}."
        )
    else:
        insights.append(
            f"Highest returned value: {fmt_number(best_value)} in {metric_column} for {leaders[0]}."
        )

    if len(ranked) >= 2:
        second_value = float(ranked.iloc[1][metric_column])
        insights.append(
            f"Gap between the two highest returned values: {fmt_number(best_value - second_value)} in {metric_column}."
        )

    insights.append(
        f"Sum of the {len(ranked)} returned rows for {metric_column}: {fmt_number(float(ranked[metric_column].sum()))}."
    )
    return list(dict.fromkeys(insights))


def describe_scope(validated: ValidatedQuery, row_count: int) -> str:
    max_rows = settings.max_rows
    if validated.original_limit is not None and validated.original_limit <= max_rows:
        return (
            f"The query itself limits output to {validated.original_limit} rows; "
            "other matching rows may exist."
        )
    if validated.cap_applied and row_count >= max_rows:
        return f"The result was capped at {max_rows} rows; more matching rows may exist."
    return "The query returned all rows matching its conditions."
