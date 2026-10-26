"""Ollama client with classified failures."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlsplit, urlunsplit

import requests

from .config import settings
from .errors import (
    OllamaConnectionError,
    OllamaEmptyResponseError,
    OllamaError,
    OllamaHTTPError,
    OllamaResponseError,
    OllamaTimeoutError,
)
from .log import logger


@dataclass(frozen=True)
class OllamaResult:
    """Text produced by the model (the `response` field) plus run metadata."""

    text: str
    done_reason: Optional[str]
    elapsed_s: float
    load_s: Optional[float]
    prompt_tokens: Optional[int]
    output_tokens: Optional[int]

    @property
    def truncated(self) -> bool:
        return self.done_reason == "length"


def estimate_tokens(text: str) -> int:
    """Deliberately conservative token estimate (about 3 characters per token)."""
    return len(text) // 3 + 1


def _ns_to_s(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return round(value / 1e9, 2)
    return None


def _extract_http_error_text(response: Any) -> str:
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict) and isinstance(data.get("error"), str):
        return data["error"].strip()[:300]
    text = getattr(response, "text", "")
    return text.strip()[:300] if isinstance(text, str) else ""


def call_ollama(
    prompt: str,
    *,
    purpose: str,
    read_timeout: int,
    max_tokens: int,
    json_mode: bool = False,
) -> OllamaResult:
    """Send one non-streaming request to Ollama and classify any failure.

    There are no automatic retries: a failure is reported with its category.
    The Ollama API response is the JSON envelope; the model's output is the
    string in its `response` field.
    """
    url = settings.ollama_url
    connect_timeout = settings.ollama_connect_timeout_s
    body: dict[str, Any] = {
        "model": settings.model,
        "prompt": prompt,
        "stream": False,
        "keep_alive": settings.keep_alive,
        "options": {
            "temperature": 0,
            "num_predict": max_tokens,
            "num_ctx": settings.num_ctx,
        },
    }
    if json_mode:
        body["format"] = "json"

    logger.info(
        "Ollama %s request: model=%s prompt_chars=%d est_prompt_tokens=%d "
        "max_tokens=%d connect_timeout=%ss read_timeout=%ss",
        purpose, settings.model, len(prompt), estimate_tokens(prompt), max_tokens,
        connect_timeout, read_timeout,
    )
    started = time.perf_counter()

    try:
        response = requests.post(url, json=body, timeout=(connect_timeout, read_timeout))
    except requests.exceptions.ConnectTimeout as exc:
        logger.warning("Ollama %s: connect timeout after %ss", purpose, connect_timeout)
        raise OllamaTimeoutError(
            f"Connecting to Ollama at {url} timed out after "
            f"{connect_timeout}s. Check that Ollama is running and not blocked."
        ) from exc
    except requests.exceptions.ReadTimeout as exc:
        waited = time.perf_counter() - started
        logger.warning("Ollama %s: read timeout after %.1fs (limit %ss)", purpose, waited, read_timeout)
        raise OllamaTimeoutError(
            f"Ollama accepted the request but did not finish the {purpose} within "
            f"{read_timeout}s. Ollama is reachable; the local model is slow for this "
            "prompt, still loading, or busy with another request."
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        # requests can wrap a body-phase read timeout in a ConnectionError.
        if "read timed out" in str(exc).lower():
            logger.warning("Ollama %s: read timeout (wrapped) after %.1fs", purpose, time.perf_counter() - started)
            raise OllamaTimeoutError(
                f"Ollama stopped responding while sending the {purpose} "
                f"(read timeout {read_timeout}s)."
            ) from exc
        logger.warning("Ollama %s: connection failed: %s", purpose, type(exc).__name__)
        raise OllamaConnectionError(
            f"Could not connect to Ollama at {url}. Check that Ollama is "
            "running and that the URL and port are correct."
        ) from exc
    except requests.exceptions.RequestException as exc:
        logger.warning("Ollama %s: request failed: %s", purpose, type(exc).__name__)
        raise OllamaError(
            f"The request to Ollama failed ({type(exc).__name__})."
        ) from exc

    elapsed = time.perf_counter() - started

    if response.status_code >= 400:
        detail = _extract_http_error_text(response)
        logger.warning("Ollama %s: HTTP %s: %s", purpose, response.status_code, detail)
        hint = ""
        if response.status_code == 404:
            hint = (
                f" The model may not be installed. Local Ollama: run `ollama pull {settings.model}` "
                "(compare with `ollama list`). Docker: it downloads on first start; "
                "follow `docker compose logs -f ollama-pull` until it finishes."
            )
        elif response.status_code >= 500:
            hint = " This is a server-side failure in Ollama (for example out of memory); check the Ollama log."
        raise OllamaHTTPError(
            f"HTTP {response.status_code} from Ollama"
            + (f": {detail}." if detail else ".")
            + hint
        )

    try:
        payload = response.json()
    except ValueError as exc:
        logger.warning("Ollama %s: HTTP %s but body is not valid JSON", purpose, response.status_code)
        raise OllamaResponseError(
            f"Ollama answered HTTP {response.status_code} but the response body was not valid JSON."
        ) from exc

    if not isinstance(payload, dict):
        raise OllamaResponseError("Ollama returned JSON that is not an object.")

    api_error = payload.get("error")
    if api_error:
        logger.warning("Ollama %s: API error field present", purpose)
        raise OllamaResponseError(f"Ollama reported an error: {str(api_error)[:300]}")

    text = payload.get("response")
    if not isinstance(text, str):
        raise OllamaResponseError("The Ollama response had no text in its 'response' field.")

    done_reason = payload.get("done_reason") if isinstance(payload.get("done_reason"), str) else None
    result = OllamaResult(
        text=text.strip(),
        done_reason=done_reason,
        elapsed_s=round(elapsed, 2),
        load_s=_ns_to_s(payload.get("load_duration")),
        prompt_tokens=payload.get("prompt_eval_count") if isinstance(payload.get("prompt_eval_count"), int) else None,
        output_tokens=payload.get("eval_count") if isinstance(payload.get("eval_count"), int) else None,
    )

    logger.info(
        "Ollama %s done: wall=%.1fs load=%ss prompt_tokens=%s output_tokens=%s done_reason=%s",
        purpose, elapsed, result.load_s, result.prompt_tokens, result.output_tokens, result.done_reason,
    )
    if result.prompt_tokens is not None and result.prompt_tokens >= settings.num_ctx - 8:
        logger.warning(
            "Ollama %s: prompt used %s tokens of a %s-token context window; input may have been truncated.",
            purpose, result.prompt_tokens, settings.num_ctx,
        )

    if not result.text:
        raise OllamaEmptyResponseError(
            "The model returned an empty response"
            + (f" (done_reason={done_reason})." if done_reason else ".")
        )
    return result


# --------------------------------------------------
# Model readiness (is the configured model installed on the Ollama server?)
# --------------------------------------------------


@dataclass(frozen=True)
class ModelStatus:
    """Result of asking Ollama which models it has.

    state: ready (installed) | missing (server answered, model not listed) |
           unreachable (cannot connect) | unknown (could not verify; do not block).
    """

    state: str
    detail: str

    @property
    def blocks_queries(self) -> bool:
        return self.state == "missing"


_READY_TTL_S = 10.0
_NOT_READY_TTL_S = 3.0
_status_cache: Optional[tuple] = None  # (valid_until_monotonic, ModelStatus)


def tags_url() -> str:
    """The Ollama endpoint that lists installed models, derived from the generate URL."""
    parts = urlsplit(settings.ollama_url)
    path = parts.path.rstrip("/")
    if path.endswith("/api/generate"):
        path = path[: -len("/api/generate")]
    return urlunsplit((parts.scheme, parts.netloc, path + "/api/tags", "", ""))


def missing_model_help() -> str:
    return (
        f"The AI model `{settings.model}` is not installed on the Ollama server at {settings.ollama_url}.\n\n"
        f"- **Local Ollama:** run `ollama pull {settings.model}`, then reload this page. "
        "`ollama list` shows what is installed.\n"
        "- **Docker:** the model downloads on first start (about 2 GB). Follow "
        "`docker compose logs -f ollama-pull`; it is ready when that job exits with code 0.\n"
        "- If you installed a different model, set `ANALYST_MODEL` to its exact name."
    )


def _query_model_status() -> ModelStatus:
    url = tags_url()
    try:
        response = requests.get(url, timeout=(settings.ollama_connect_timeout_s, 5))
    except (requests.exceptions.ConnectTimeout, requests.exceptions.ConnectionError):
        return ModelStatus(
            "unreachable",
            f"Cannot reach Ollama at {url}. Check that Ollama is running and the URL is correct.",
        )
    except requests.exceptions.RequestException as exc:
        return ModelStatus("unknown", f"Could not check the model list ({type(exc).__name__}).")

    if response.status_code != 200:
        return ModelStatus("unknown", f"Could not check the model list (HTTP {response.status_code} from {url}).")
    try:
        data = response.json()
    except ValueError:
        return ModelStatus("unknown", "Could not check the model list (response was not valid JSON).")
    models = data.get("models") if isinstance(data, dict) else None
    if not isinstance(models, list):
        return ModelStatus("unknown", "Could not check the model list (unexpected response format).")

    names = {m.get("name") for m in models if isinstance(m, dict)}
    wanted = settings.model if ":" in settings.model else f"{settings.model}:latest"
    if settings.model in names or wanted in names:
        return ModelStatus("ready", f"Model {settings.model} is installed.")
    return ModelStatus("missing", missing_model_help())


def model_status(*, use_cache: bool = True) -> ModelStatus:
    """Cached check (10 s when ready, 3 s otherwise) so page reruns stay cheap."""
    global _status_cache
    now = time.monotonic()
    if use_cache and _status_cache is not None and _status_cache[0] > now:
        return _status_cache[1]
    status = _query_model_status()
    if status.state != "ready":
        logger.warning("Model readiness: %s (%s)", status.state, status.detail.splitlines()[0])
    ttl = _READY_TTL_S if status.state == "ready" else _NOT_READY_TTL_S
    _status_cache = (now + ttl, status)
    return status
