"""Streamlit interface. All business logic lives in the other modules."""

from __future__ import annotations

import html
import time
import uuid
from typing import Optional

import mysql.connector
import pandas as pd
import streamlit as st

from . import audit as audit_log
from .audit import audit
from .auth import LoginThrottle, UserStore, attempt_login, identity_from_headers, session_expired, valid_username
from .config import settings
from .credentials import password_is_preconfigured, password_source, resolve_db_password
from .domain import get_profile
from .errors import ConfigurationError, OllamaError, QueryValidationError, RateLimitError, SQLGenerationError
from .explain import attempt_explanation
from .llm import model_status
from .log import logger
from .models import AnalysisRun, FollowUp
from .service import run_audited, startup_problems

_CSS = """
<style>
  .block-container {padding-top: 2rem; padding-bottom: 2.5rem; max-width: 1400px;}
  .app-eyebrow {font-size: .78rem; letter-spacing: .12em; text-transform: uppercase; opacity: .72; font-weight: 650;}
  .app-subtitle {font-size: 1.02rem; opacity: .78; margin-top: -.35rem; margin-bottom: 1.2rem;}
  div[data-testid="stMetric"] {border: 1px solid rgba(128,128,128,.24); padding: .9rem 1rem; border-radius: .75rem;}
  div.stButton > button[kind="primary"] {min-height: 2.8rem; font-weight: 650;}
</style>
"""


# Process-wide so that opening a new browser tab does not reset the lockout counter.
_throttle = LoginThrottle(settings.max_login_attempts, settings.login_lockout_s)
_SESSION_KEYS = ("user", "last_active", "last_run", "query_history", "db_password")


def _database_error_message(exc: mysql.connector.Error) -> str:
    errno = getattr(exc, "errno", None)
    if errno == 3024:
        return (
            f"The query exceeded the {settings.query_timeout_ms // 1000}-second execution limit. "
            "Try a narrower question (a shorter date range or fewer groupings)."
        )
    if errno == 1045:
        if password_is_preconfigured():
            return (
                f"MySQL rejected the password supplied by {password_source()} for user '{settings.db_user}'. "
                "The configured password does not match the database account. Ask your administrator to check it "
                "(Docker: after changing secrets, recreate the database volume with `docker compose down -v`). "
                "Administrators can run `python -m ai_database_analyst check` for details."
            )
        return "MySQL rejected the login. Check the database password in the sidebar."
    if errno in (2003, 2002, 2006, 2013):
        return f"Could not reach MySQL at {settings.db_host}:{settings.db_port}. Check that MySQL is running."
    return getattr(exc, "msg", "") or "Unknown database error."


def handle_analyze(question: str, follow_up: bool = False) -> None:
    """Run the pipeline, show any failure, and store the outcome in session state."""
    previous = st.session_state.pop("last_run", None)
    context = FollowUp(previous.question, previous.sql) if follow_up and previous is not None else None
    try:
        run = run_audited(
            question,
            resolve_db_password(st.session_state.get("db_password", "")),
            user=st.session_state["user"],
            session_id=st.session_state["session_id"],
            stage=st.spinner,
            followup=context,
        )
    except RateLimitError as exc:
        st.warning(str(exc))
        return
    except ConfigurationError as exc:
        st.error(str(exc))
        return
    except QueryValidationError as exc:
        st.error(f"The generated SQL was rejected before execution: {exc}")
        if exc.generated_sql:
            with st.expander("Rejected SQL"):
                st.code(exc.generated_sql, language="sql")
        st.caption("Nothing was run against the database. Try rephrasing the question.")
        return
    except OllamaError as exc:
        st.error(f"{exc.title} while generating SQL ({exc.category}): {exc}")
        return
    except SQLGenerationError as exc:
        st.error(f"SQL generation failed: {exc}")
        return
    except ValueError as exc:
        st.error(str(exc))
        return
    except mysql.connector.Error as exc:
        logger.warning("Database error %s: %s", getattr(exc, "errno", None), type(exc).__name__)
        st.error(f"Database operation failed: {_database_error_message(exc)}")
        return
    except Exception as exc:
        logger.exception("Unexpected failure during analysis")
        st.error("An unexpected error prevented the request from completing.")
        st.caption(f"Error type: {type(exc).__name__}. Check the terminal logs for details.")
        return

    st.session_state["last_run"] = run
    history = st.session_state.query_history
    history.insert(0, {"question": question, "sql": run.sql, "rows": len(run.results)})
    st.session_state.query_history = history[:10]


def _audit_export(run: AnalysisRun) -> None:
    audit(
        audit_log.EXPORT_CSV,
        st.session_state.get("user"),
        session=st.session_state.get("session_id"),
        rows=len(run.results),
        sql=run.sql,
    )


def _request_explanation_retry() -> None:
    run = st.session_state.get("last_run")
    if run is not None:
        run.explanation_status = "pending"


def render_chart(analysis: pd.DataFrame) -> None:
    if analysis.empty or len(analysis.columns) < 2:
        return
    numeric_columns = analysis.select_dtypes(include="number").columns.tolist()
    categorical_columns = [c for c in analysis.columns if c not in numeric_columns]
    if not (numeric_columns and categorical_columns):
        return
    with st.expander("Visualize results"):
        category_column = st.selectbox("Category", categorical_columns, key="chart_category")
        value_column = st.selectbox("Numeric value", numeric_columns, key="chart_value")
        chart_data = analysis[[category_column, value_column]].dropna()
        if not chart_data.empty:
            st.bar_chart(chart_data.set_index(category_column)[value_column])


def render_run(run: AnalysisRun) -> None:
    results = run.results

    st.subheader("Generated SQL")
    st.code(run.sql, language="sql")
    note = f"Query completed in {run.query_seconds:.2f} s."
    if run.attempts > 1:
        note += f" The first attempt needed a correction, so the query was regenerated {run.attempts - 1}x."
    st.caption(note)

    st.subheader("Query Results")
    st.caption(f"Showing {len(results):,} returned rows. Results are capped at {settings.max_rows:,} rows per query.")
    st.dataframe(results, width="stretch", hide_index=True)
    st.download_button(
        label="Download results as CSV",
        data=run.csv,
        file_name="ai_database_analyst_results.csv",
        mime="text/csv",
        on_click=_audit_export,
        args=(run,),
        help=f"Export the rows returned by this query (same {settings.max_rows}-row cap).",
    )

    col1, col2 = st.columns(2)
    col1.metric("Rows returned", len(results))
    col2.metric("Columns returned", len(results.columns))

    render_chart(run.analysis)

    if run.insights:
        st.subheader("Computed findings")
        st.caption("Calculated directly from the returned rows by Python (not AI-generated).")
        for insight in run.insights:
            st.markdown(f"- {insight}")

    st.subheader("AI Analysis")
    if run.explanation_status == "pending":
        with st.spinner(
            f"Interpreting the results with {settings.model} (local CPU models can take a minute)..."
        ):
            attempt_explanation(run)

    status = run.explanation_status
    if status == "done":
        st.write(run.explanation_text)
        detail = f"Generated by {settings.model}"
        if run.explanation_seconds is not None:
            detail += f" in {run.explanation_seconds:.1f} s"
        st.caption(
            detail + ". AI interpretation of the executed SQL and returned rows; "
            "verify important decisions against source data."
        )
        if run.explanation_truncated:
            st.caption("The response reached the configured output limit and may be cut off.")
    elif status == "static":
        st.info(run.explanation_text)
    else:
        st.warning(f"The query succeeded, but the AI explanation failed. {run.explanation_error}")
        st.caption(
            "Your results, CSV download and computed findings are unaffected. "
            "Details are in the terminal log."
        )
        st.button("Retry AI explanation", on_click=_request_explanation_retry)


def render_history() -> None:
    with st.expander("Query History"):
        if not st.session_state.query_history:
            st.caption("Your recent queries will appear here.")
            return
        for index, item in enumerate(st.session_state.query_history, start=1):
            st.markdown(f"**{index}. {item['question']}**")
            st.caption(f"Rows returned: {item['rows']}")
            st.code(item["sql"], language="sql")
            st.divider()


def _sign_out(reason_event: str = audit_log.LOGOUT) -> None:
    audit(reason_event, st.session_state.get("user"), session=st.session_state.get("session_id"))
    for key in _SESSION_KEYS:
        st.session_state.pop(key, None)


def _render_login() -> None:
    """Show the sign-in form; on success store the user and rerun."""
    _, centre, _ = st.columns([1, 1.2, 1])
    with centre:
        st.subheader("Sign in")
        with st.form("login", clear_on_submit=False):
            username = st.text_input("Username", autocomplete="username")
            password = st.text_input("Password", type="password", autocomplete="current-password")
            submitted = st.form_submit_button("Sign in", type="primary")
        if not submitted:
            return
        try:
            result = attempt_login(username, password, UserStore.load(settings.users_file), _throttle)
        except ConfigurationError as exc:
            st.error(str(exc))
            return
        session_id = st.session_state["session_id"]
        name = username.strip()
        if result.ok:
            st.session_state["session_id"] = uuid.uuid4().hex[:12]  # fresh id per sign-in
            audit(audit_log.LOGIN_SUCCESS, name, session=st.session_state["session_id"])
            st.session_state["user"] = name
            st.session_state["last_active"] = time.time()
            st.rerun()
        event = audit_log.LOGIN_LOCKED if result.reason == "locked" else audit_log.LOGIN_FAILURE
        # People sometimes type their password into the username box, so malformed names are never logged.
        audit(event, name if valid_username(name) else "(invalid)", session=session_id)
        st.error(result.message)


def _authenticate() -> Optional[str]:
    """Return the signed-in username, or None after rendering whatever the person must do next."""
    mode = settings.auth_mode
    if mode == "none":
        st.warning("Authentication is disabled (ANALYST_AUTH_MODE=none). Use this for local development only.")
        return st.session_state.setdefault("user", "anonymous")

    if mode == "proxy":
        user = identity_from_headers(st.context.headers, settings.proxy_user_header)
        if user is None:
            st.error(
                f"Access denied: the {settings.proxy_user_header} header is missing. "
                "This app must be reached through the company single sign-on proxy."
            )
            return None
        st.session_state["user"] = user
        return user

    # local mode
    user = st.session_state.get("user")
    if user and session_expired(st.session_state.get("last_active"), time.time(), settings.session_timeout_min):
        _sign_out(audit_log.SESSION_TIMEOUT)
        st.info("You were signed out after a period of inactivity. Please sign in again.")
        user = None
    if user:
        st.session_state["last_active"] = time.time()
        return user
    _render_login()
    return None


def main() -> None:
    st.set_page_config(page_title="AI Database Analyst", page_icon="📊", layout="wide")
    st.markdown(_CSS, unsafe_allow_html=True)
    try:
        profile = get_profile()
    except ConfigurationError as exc:
        st.error(str(exc))
        st.stop()
    st.markdown(f'<div class="app-eyebrow">{html.escape(profile.eyebrow)}</div>', unsafe_allow_html=True)
    st.title(profile.title)
    st.markdown(f'<div class="app-subtitle">{html.escape(profile.subtitle)}</div>', unsafe_allow_html=True)

    if "session_id" not in st.session_state:
        st.session_state["session_id"] = uuid.uuid4().hex[:12]

    problems = startup_problems()
    if problems:
        for problem in problems:
            st.error(problem)
        st.stop()

    user = _authenticate()
    if user is None:
        st.stop()

    if "query_history" not in st.session_state:
        st.session_state.query_history = []

    llm_status = model_status()

    with st.sidebar:
        st.caption(f"Signed in as **{user}**")
        if settings.auth_mode == "local":
            st.button("Sign out", on_click=_sign_out)
        st.header("Database Connection")
        st.caption(f"Database: {settings.db_name}")
        st.caption(f"User: {settings.db_user}")
        if password_is_preconfigured():
            st.caption(f"Database credentials are managed by the server ({password_source()}).")
        else:
            st.text_input("Database password", type="password", key="db_password", autocomplete="off")
        model_note = {
            "ready": "ready",
            "missing": "NOT INSTALLED",
            "unreachable": "Ollama unreachable",
        }.get(llm_status.state, "status unknown")
        st.caption(f"AI model: {settings.model} ({model_note})")
        st.divider()
        st.caption(f"Queries are limited to read-only SQL and capped at {settings.max_rows} result rows.")
        st.caption("Activity is recorded in an audit log." if settings.audit_enabled else "Audit logging is off.")

    if llm_status.state == "missing":
        st.error(llm_status.detail)
    elif llm_status.state == "unreachable":
        st.warning(llm_status.detail)

    question = st.text_input(
        "Your question",
        placeholder=profile.examples[0] if profile.examples else "Ask a question about your data",
        max_chars=settings.max_question_chars,
        help="Ask one question about the available tables and views.",
    )
    follow_up = False
    if st.session_state.get("last_run") is not None:
        follow_up = st.checkbox(
            "Follow-up to my previous question",
            help='Tick this when the question refers back, e.g. "and only for Europe?" or "now by month".',
        )

    if profile.examples:
        with st.expander("Example questions"):
            columns = st.columns(2)
            for i, example in enumerate(profile.examples):
                with columns[i % 2]:
                    st.markdown(f"- {example}")

    if st.button(
        "Analyze",
        type="primary",
        disabled=not question.strip() or llm_status.blocks_queries,
        help="The AI model is not installed yet; see the message above." if llm_status.blocks_queries else None,
    ):
        handle_analyze(question, follow_up)

    run = st.session_state.get("last_run")
    if run is not None:
        render_run(run)

    render_history()
