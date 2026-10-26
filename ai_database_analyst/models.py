"""Plain data objects shared between the pipeline and the UI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class RetryFeedback:
    """A failed attempt, shown to the model so it can correct itself."""

    sql: str
    problem: str


@dataclass(frozen=True)
class FollowUp:
    """The previous question and the SQL that answered it, for "and only for Europe?" questions."""

    question: str
    sql: str


@dataclass
class AnalysisRun:
    """Outcome of one question: results, findings and the (mutable) AI explanation."""

    question: str
    sql: str
    results: pd.DataFrame
    analysis: pd.DataFrame
    csv: bytes
    query_seconds: float
    insights: list
    scope_note: str
    explanation_status: str = "pending"  # pending | done | static | failed
    explanation_text: str = ""
    explanation_error: Optional[str] = None
    explanation_truncated: bool = False
    explanation_seconds: Optional[float] = None
    attempts: int = 1  # SQL generation attempts needed (1 = first try)
