"""AI explanation of results. Fails independently of the query results."""

from __future__ import annotations

import pandas as pd

from .config import settings
from .errors import OllamaError
from .llm import OllamaResult, call_ollama
from .log import logger
from .models import AnalysisRun
from .prompts import build_explanation_prompt


def explain_results(question: str, sql: str, analysis: pd.DataFrame, scope_note: str) -> OllamaResult:
    prompt = build_explanation_prompt(question, sql, analysis, scope_note)
    return call_ollama(
        prompt,
        purpose="result explanation",
        read_timeout=settings.explain_read_timeout_s,
        max_tokens=settings.explain_max_tokens,
    )


def attempt_explanation(run: AnalysisRun) -> None:
    """Fill in the explanation fields of a run. Never raises and never touches results."""
    run.explanation_error = None
    try:
        result = explain_results(run.question, run.sql, run.analysis, run.scope_note)
    except OllamaError as exc:
        run.explanation_status = "failed"
        run.explanation_error = f"{exc.title} ({exc.category}): {exc}"
        return
    except Exception as exc:  # the explanation must never discard the results
        logger.exception("Unexpected failure while generating the explanation")
        run.explanation_status = "failed"
        run.explanation_error = (
            f"Unexpected error ({type(exc).__name__}). See the terminal log for details."
        )
        return
    run.explanation_status = "done"
    run.explanation_text = result.text
    run.explanation_truncated = result.truncated
    run.explanation_seconds = result.elapsed_s
