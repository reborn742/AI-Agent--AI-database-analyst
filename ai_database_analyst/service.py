"""Application service layer: the pipeline plus rate limiting and auditing.

The UI calls :func:`run_audited` instead of the bare pipeline, so every query
is attributed to a user and leaves an audit record whatever the outcome.
No Streamlit imports here.
"""

from __future__ import annotations

import time
from typing import Optional

from . import audit as audit_log
from .audit import audit
from .auth import UserStore
from .config import settings
from .domain import get_profile
from .errors import ConfigurationError, QueryValidationError, RateLimitError
from .models import AnalysisRun, FollowUp
from .pipeline import StageFactory, _no_stage, run_analysis
from .ratelimit import RateLimiter

_limiter: Optional[RateLimiter] = None


def _get_limiter() -> RateLimiter:
    global _limiter
    if _limiter is None:
        _limiter = RateLimiter(settings.max_queries_per_minute)
    return _limiter


def run_audited(
    question: str,
    password: str,
    *,
    user: str,
    session_id: str = "-",
    stage: StageFactory = _no_stage,
    followup: Optional[FollowUp] = None,
) -> AnalysisRun:
    """Run one question for ``user``: rate-limit, execute, audit. Re-raises pipeline errors unchanged."""
    wait = _get_limiter().acquire(user)
    if wait > 0:
        audit(audit_log.RATE_LIMITED, user, session=session_id, retry_after_s=round(wait, 1))
        raise RateLimitError(wait)

    started = time.perf_counter()
    try:
        run = run_analysis(question, password, stage=stage, followup=followup)
    except QueryValidationError as exc:
        audit(
            audit_log.QUERY_REJECTED,
            user,
            session=session_id,
            question=question,
            sql=exc.generated_sql,
            reason=str(exc),
        )
        raise
    except Exception as exc:
        audit(
            audit_log.QUERY_ERROR,
            user,
            session=session_id,
            question=question,
            error_type=type(exc).__name__,
            error_code=getattr(exc, "errno", None),
            elapsed_s=round(time.perf_counter() - started, 2),
        )
        raise

    audit(
        audit_log.QUERY_OK,
        user,
        session=session_id,
        question=question,
        sql=run.sql,
        rows=len(run.results),
        attempts=run.attempts,
        followup=followup is not None,
        query_s=run.query_seconds,
        elapsed_s=round(time.perf_counter() - started, 2),
    )
    return run


def startup_problems() -> list:
    """Configuration problems that must block the app, as human-readable strings."""
    problems = []
    if settings.auth_mode == "local":
        try:
            store = UserStore.load(settings.users_file)
        except ConfigurationError as exc:
            problems.append(str(exc))
        else:
            if not store.active_usernames():
                problems.append(
                    f"No users are configured (looked in {settings.users_file}). "
                    "Create one with:  python -m ai_database_analyst users add <username>"
                )
    try:
        get_profile()
    except ConfigurationError as exc:
        problems.append(str(exc))
    problem = audit_log.audit_problem()
    if problem:
        problems.append(problem)
    return problems

