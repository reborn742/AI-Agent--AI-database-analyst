"""Natural-language question -> candidate SQL (unvalidated model output)."""

from __future__ import annotations

import json
from typing import Optional

from .config import settings
from .domain import DomainProfile, get_profile
from .errors import QueryValidationError, SQLGenerationError
from .llm import call_ollama, estimate_tokens
from .log import logger
from .models import FollowUp, RetryFeedback
from .prompts import build_sql_prompt
from .schema import SchemaInfo
from .validation import validate_sql

_example_cache: dict = {}


def usable_examples(profile: DomainProfile, schema: SchemaInfo) -> tuple:
    """Worked examples from the profile that are valid against the *live* schema.

    Examples that reference tables or columns that do not exist (or hidden ones) are dropped, so a
    stale profile can never teach the model something the validator would reject.
    """
    key = (profile.sql_examples, schema.prompt_text)
    if key not in _example_cache:
        good = []
        for example in profile.sql_examples:
            try:
                validate_sql(example.sql, schema)
            except QueryValidationError as exc:
                logger.warning("Ignoring profile example %r: %s", example.question[:60], exc)
                continue
            good.append(example)
        if len(_example_cache) > 32:
            _example_cache.clear()
        _example_cache[key] = tuple(good)
    return _example_cache[key]


def generate_sql(
    question: str,
    schema: SchemaInfo,
    *,
    feedback: Optional[RetryFeedback] = None,
    followup: Optional[FollowUp] = None,
) -> str:
    if not isinstance(question, str) or not question.strip():
        raise ValueError("Enter a question before generating SQL.")
    if len(question) > settings.max_question_chars:
        raise ValueError(f"Questions must be {settings.max_question_chars:,} characters or fewer.")
    if len(schema.prompt_text) > settings.max_schema_chars:
        raise ValueError("The database schema is too large to send safely to the local model.")

    profile = get_profile()
    prompt = build_sql_prompt(
        question,
        schema.prompt_text,
        profile,
        examples=usable_examples(profile, schema),
        feedback=feedback,
        followup=followup,
    )

    # Silent truncation of the schema/rules would produce wrong SQL, so fail loudly.
    if estimate_tokens(prompt) + settings.sql_max_tokens > settings.num_ctx:
        raise SQLGenerationError(
            "The schema and question are too large for the model's context window "
            f"({settings.num_ctx} tokens). Raise ANALYST_NUM_CTX or reduce the schema."
        )

    result = call_ollama(
        prompt,
        purpose="SQL generation",
        read_timeout=settings.sql_read_timeout_s,
        max_tokens=settings.sql_max_tokens,
        json_mode=True,
    )

    try:
        parsed = json.loads(result.text)
    except json.JSONDecodeError as exc:
        hint = " The output reached the token limit and was cut off." if result.truncated else ""
        raise SQLGenerationError("The model did not return valid JSON." + hint) from exc

    sql = parsed.get("sql") if isinstance(parsed, dict) else None
    if not isinstance(sql, str) or not sql.strip():
        raise SQLGenerationError("The model did not return a valid SQL query.")
    return sql.strip()
