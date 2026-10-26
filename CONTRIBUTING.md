# Contributing

## Setup

```bash
make install-dev          # creates .venv and installs runtime + dev dependencies
make test                 # pytest with coverage
make lint                 # ruff
pre-commit install        # optional: lint and secret scan on every commit
```

Without `make`: `python -m venv .venv`, activate it, `pip install -r requirements-dev.txt`, then `pytest` and `ruff check .`.

## Ground rules

- **Anything that decides what SQL runs lives in `validation.py` and must have tests.** Add the new accepted/rejected
  case to `tests/test_validation.py` in the same change. A change that loosens validation needs a written reason in the PR.
- Business logic stays out of `ui.py`. If you need Streamlit-free logic, put it in `service.py`, `pipeline.py` or a new module.
- Never log or audit secrets or passwords. `tests/test_audit.py` guards the audit log.
- New settings go in `config.py`, `.env.example` and `docs/CONFIGURATION.md`, with a clamp and a test.
- Keep the test suite offline: no real MySQL, Ollama or network (see how `test_pipeline.py` fakes them).

## Pull requests

CI must pass: lint, tests on Python 3.10 and 3.12, wheel build, Docker build. Update `CHANGELOG.md` under *Unreleased*.
