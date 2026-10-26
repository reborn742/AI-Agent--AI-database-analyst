import pytest
import requests

from ai_database_analyst import llm
from ai_database_analyst.errors import (
    OllamaConnectionError,
    OllamaEmptyResponseError,
    OllamaHTTPError,
    OllamaResponseError,
    OllamaTimeoutError,
)


class FakeResponse:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


def _call():
    return llm.call_ollama("hi", purpose="test", read_timeout=5, max_tokens=10)


def _patch_post(monkeypatch, result):
    def fake_post(*args, **kwargs):
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(llm.requests, "post", fake_post)


def test_success(monkeypatch):
    _patch_post(monkeypatch, FakeResponse(payload={"response": " ok ", "done_reason": "stop", "eval_count": 3}))
    result = _call()
    assert result.text == "ok"
    assert result.output_tokens == 3
    assert result.truncated is False


def test_truncated_flag(monkeypatch):
    _patch_post(monkeypatch, FakeResponse(payload={"response": "abc", "done_reason": "length"}))
    assert _call().truncated is True


@pytest.mark.parametrize(
    "result, expected",
    [
        (requests.exceptions.ConnectTimeout(), OllamaTimeoutError),
        (requests.exceptions.ReadTimeout(), OllamaTimeoutError),
        (requests.exceptions.ConnectionError("read timed out"), OllamaTimeoutError),
        (requests.exceptions.ConnectionError("refused"), OllamaConnectionError),
        (FakeResponse(status=404, payload={"error": "model not found"}), OllamaHTTPError),
        (FakeResponse(status=500, text="boom"), OllamaHTTPError),
        (FakeResponse(payload=None), OllamaResponseError),
        (FakeResponse(payload=["not", "a", "dict"]), OllamaResponseError),
        (FakeResponse(payload={"error": "bad"}), OllamaResponseError),
        (FakeResponse(payload={"nope": 1}), OllamaResponseError),
        (FakeResponse(payload={"response": "   "}), OllamaEmptyResponseError),
    ],
)
def test_failures_are_classified(monkeypatch, result, expected):
    _patch_post(monkeypatch, result)
    with pytest.raises(expected):
        _call()


def test_404_hint_names_model(monkeypatch):
    _patch_post(monkeypatch, FakeResponse(status=404, payload={"error": "x"}))
    with pytest.raises(OllamaHTTPError, match="ollama pull"):
        _call()


# --- model readiness -------------------------------------------------------------------


def _patch_get(monkeypatch, result, calls=None):
    def fake_get(url, **kwargs):
        if calls is not None:
            calls.append(url)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(llm.requests, "get", fake_get)
    monkeypatch.setattr(llm, "_status_cache", None)


def _tags(*names):
    return FakeResponse(payload={"models": [{"name": n} for n in names]})


def test_model_ready(monkeypatch):
    _patch_get(monkeypatch, _tags("llama3:8b", llm.settings.model))
    status = llm.model_status(use_cache=False)
    assert status.state == "ready"
    assert not status.blocks_queries


def test_model_missing_blocks_and_explains_fix(monkeypatch):
    _patch_get(monkeypatch, _tags("llama3:8b"))
    status = llm.model_status(use_cache=False)
    assert status.state == "missing"
    assert status.blocks_queries
    assert f"ollama pull {llm.settings.model}" in status.detail
    assert "docker compose logs" in status.detail


def test_similar_tag_is_not_the_model(monkeypatch):
    _patch_get(monkeypatch, _tags(llm.settings.model + "-instruct"))
    assert llm.model_status(use_cache=False).state == "missing"


@pytest.mark.parametrize(
    "result",
    [requests.exceptions.ConnectionError("refused"), requests.exceptions.ConnectTimeout()],
)
def test_unreachable_does_not_block(monkeypatch, result):
    _patch_get(monkeypatch, result)
    status = llm.model_status(use_cache=False)
    assert status.state == "unreachable"
    assert not status.blocks_queries


@pytest.mark.parametrize(
    "result",
    [
        FakeResponse(status=404, text="not found"),  # e.g. a proxy without /api/tags
        FakeResponse(payload=None),  # not JSON
        FakeResponse(payload={"unexpected": 1}),
        FakeResponse(payload=["x"]),
        requests.exceptions.ReadTimeout(),
    ],
)
def test_unverifiable_never_blocks(monkeypatch, result):
    _patch_get(monkeypatch, result)
    status = llm.model_status(use_cache=False)
    assert status.state == "unknown"
    assert not status.blocks_queries


def test_status_is_cached(monkeypatch):
    calls = []
    _patch_get(monkeypatch, _tags(llm.settings.model), calls)
    llm.model_status()
    llm.model_status()
    assert len(calls) == 1
    llm.model_status(use_cache=False)
    assert len(calls) == 2


def test_tags_url_derivation(monkeypatch):
    from types import SimpleNamespace

    for generate_url, expected in [
        ("http://localhost:11434/api/generate", "http://localhost:11434/api/tags"),
        ("http://ollama:11434/api/generate/", "http://ollama:11434/api/tags"),
        ("https://gw.example.com/ollama/api/generate", "https://gw.example.com/ollama/api/tags"),
        ("http://localhost:11434", "http://localhost:11434/api/tags"),
    ]:
        monkeypatch.setattr(llm, "settings", SimpleNamespace(ollama_url=generate_url, model="m:1", ollama_connect_timeout_s=5))
        assert llm.tags_url() == expected


def test_404_message_covers_docker_and_local(monkeypatch):
    _patch_post(monkeypatch, FakeResponse(status=404, payload={"error": "model 'x' not found"}))
    with pytest.raises(OllamaHTTPError) as info:
        _call()
    text = str(info.value)
    assert "ollama pull" in text and "docker compose logs" in text
