"""Question -> schema -> SQL -> validation -> execution -> findings.

No Streamlit imports here: the UI passes a ``stage`` factory (e.g. ``st.spinner``)
to show progress, and handles the exceptions this function raises.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any, Callable, ContextManager, Optional

import mysql.connector

from .analysis import build_deterministic_insights, describe_scope, to_analysis_frame
from .config import settings
from .db import get_schema, run_query
from .errors import QueryValidationError
from .log import logger
from .models import AnalysisRun, FollowUp, RetryFeedback
from .sqlgen import generate_sql
from .validation import validate_sql

StageFactory = Callable[[str], ContextManager[Any]]

# MySQL errors that mean "the query is wrong" rather than "the system is unwell": unknown column or
# table, syntax error, ambiguous column, bad GROUP BY, unknown function. The model may fix these.
REPAIRABLE_DB_ERRNOS = frozenset({1052, 1054, 1055, 1064, 1066, 1109, 1111, 1140, 1146, 1248, 1305})


def _no_stage(_message: str) -> ContextManager[Any]:
    return nullcontext()


def run_analysis(
    question: str,
    password: str,
    stage: StageFactory = _no_stage,
    followup: Optional[FollowUp] = None,
) -> AnalysisRun:
    """Run one question end to end.

    If the model's SQL fails validation in a fixable way (unknown column, syntax error) or MySQL
    rejects it as malformed, the model is shown the problem and tries again, up to
    ``settings.sql_retries`` extra times. Safety violations are never retried.

    Raises QueryValidationError (with ``generated_sql`` set), SQLGenerationError,
    OllamaError, ValueError or mysql.connector.Error; the caller decides how to show them.
    The AI explanation is NOT generated here; see explain.attempt_explanation.
    """
    logger.info("Analysis started (question length %d)", len(question))

    with stage("Reading the database schema..."):
        schema = get_schema(password)

    feedback: Optional[RetryFeedback] = None
    attempt = 0
    while True:
        attempt += 1
        label = f"Generating SQL with {settings.model}..."
        if attempt > 1:
            label = f"Refining the query (attempt {attempt})..."
        with stage(label):
            generated_sql = generate_sql(question, schema, feedback=feedback, followup=followup)

        with stage("Validating the generated SQL..."):
            try:
                validated = validate_sql(generated_sql, schema)
            except QueryValidationError as exc:
                exc.generated_sql = generated_sql
                logger.warning("SQL rejected (attempt %d): %s | sql=%s", attempt, exc, generated_sql[:500])
                if exc.repairable and attempt <= settings.sql_retries:
                    feedback = RetryFeedback(generated_sql, str(exc))
                    continue
                raise

        with stage("Running the read-only query..."):
            try:
                results, query_seconds = run_query(validated.sql, password)
            except mysql.connector.Error as exc:
                if getattr(exc, "errno", None) in REPAIRABLE_DB_ERRNOS and attempt <= settings.sql_retries:
                    logger.warning("MySQL rejected the query (attempt %d, errno %s)", attempt, exc.errno)
                    feedback = RetryFeedback(validated.sql, str(getattr(exc, "msg", "") or exc))
                    continue
                raise
        break

    analysis = to_analysis_frame(results)
    run = AnalysisRun(
        question=question,
        sql=validated.sql,
        results=results,
        analysis=analysis,
        csv=results.to_csv(index=False).encode("utf-8-sig"),
        query_seconds=query_seconds,
        insights=build_deterministic_insights(question, analysis),
        scope_note=describe_scope(validated, len(results)),
        attempts=attempt,
    )
    if results.empty:
        run.explanation_status = "static"
        run.explanation_text = "The query completed successfully but returned no matching rows."

    logger.info("Query returned %d rows in %.2fs", len(results), query_seconds)
    return run
