"""Exception types used across the package."""

from __future__ import annotations

from typing import Optional


class QueryValidationError(ValueError):
    """The generated SQL was rejected before execution.

    ``repairable`` marks mistakes the model can plausibly fix when told about them (unknown column,
    syntax error). Safety violations (writes, file access, other databases) are never repairable.
    """

    # Filled in by the pipeline so the UI can show what was rejected.
    generated_sql: Optional[str] = None
    repairable: bool = False

    def __init__(self, message: str = "", *, repairable: bool = False) -> None:
        super().__init__(message)
        self.repairable = repairable


class SQLGenerationError(Exception):
    """The model response could not be turned into a SQL string."""


class MissingCredentialsError(ValueError):
    """No database password was supplied."""


class ConfigurationError(Exception):
    """The deployment is misconfigured (for example, no users file in local auth mode)."""


class RateLimitError(Exception):
    """The user exceeded the per-minute query allowance."""

    def __init__(self, retry_after_s: float) -> None:
        self.retry_after_s = retry_after_s
        super().__init__(f"Too many requests. Try again in {max(1, round(retry_after_s))} s.")


class OllamaError(Exception):
    """Base class for failures talking to Ollama. `category` names the failure."""

    category = "ollama"
    title = "Ollama error"


class OllamaConnectionError(OllamaError):
    category = "connection"
    title = "Cannot reach Ollama"


class OllamaTimeoutError(OllamaError):
    category = "timeout"
    title = "Ollama timed out"


class OllamaHTTPError(OllamaError):
    category = "http"
    title = "Ollama returned an error"


class OllamaResponseError(OllamaError):
    category = "invalid_response"
    title = "Unreadable Ollama response"


class OllamaEmptyResponseError(OllamaError):
    category = "empty_response"
    title = "Empty model response"
