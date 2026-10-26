# AI Database Analyst

[![CI](https://github.com/OWNER/ai-database-analyst/actions/workflows/ci.yml/badge.svg)](https://github.com/OWNER/ai-database-analyst/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.10%20|%203.12-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Ask questions about your MySQL data in plain English. A **local** language model writes the SQL, a strict validator
decides whether it may run, and results come back as a table, chart, CSV and a plain-language explanation.
Your data never leaves your network, and the database is only ever touched in read-only mode.

![Architecture](docs/architecture.svg)

## Works on your data, in your words

It is not tied to any one business. Point it at any MySQL database and optionally add a short YAML **business profile** (metric
definitions, glossary, preferred tables, example questions) so it answers the way your organisation talks. Profiles for retail,
finance, HR and support are included. It also hides sensitive tables and columns, answers follow-up questions, and corrects its own
SQL when it makes a fixable mistake. See [docs/DOMAINS.md](docs/DOMAINS.md).

## Why it is safe to put in front of colleagues

- **The model is untrusted.** Generated SQL is parsed, checked against the live schema, rebuilt from the syntax tree, checked again,
  row-capped, and executed in a `READ ONLY` transaction by a `SELECT`-only account. [Details](SECURITY.md)
- **Sign-in and accountability.** Local accounts (scrypt-hashed, lockout, idle timeout) or SSO via your proxy. Every sign-in, query,
  rejection and export lands in an append-only JSON audit log.
- **Sensitive data stays invisible.** Tables and columns you hide (and anything named like a password or card number) are removed
  from what the model sees and blocked in the validator.
- **Secrets stay out of config.** Database credentials come from Docker/Kubernetes secrets or a secret file, never from settings or logs.
- **Verified in CI.** Lint, tests on two Python versions, wheel build, Docker build, dependency audit.

## Quick start (Docker, about 5 minutes plus the model download)

```bash
python scripts/init_secrets.py                                        # random passwords into ./secrets/
docker compose up -d --build                                          # app + seeded MySQL + Ollama
docker compose run --rm app python -m ai_database_analyst users add admin
```

Open <http://localhost:8501>, sign in, and try *"Which 5 products sold the most units?"*
The first start downloads the `qwen2.5:3b` model (about 2 GB); `docker compose ps` shows when it is ready.
Follow the [demo guide](docs/DEMO.md) for a 10-minute walkthrough.

## Run without Docker

You need Python 3.10+, a MySQL database with a `SELECT`-only account, and [Ollama](https://ollama.com).

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # adjust DB host/name/user
ollama pull qwen2.5:3b
python -m ai_database_analyst users add admin          # create your sign-in
python -m ai_database_analyst check                    # verifies MySQL and Ollama
python -m ai_database_analyst run                      # http://localhost:8501
```

To use the demo profile and data locally, add `ANALYST_DOMAIN_FILE=config/domain.retail.yaml` to `.env`.
For your own database, see [Making it yours](docs/DOMAINS.md).

Quick local experiment without a login: `ANALYST_AUTH_MODE=none` (the app shows a warning banner).
To load the demo dataset into your own MySQL: run `docker/mysql-init/01_schema.sql` then `02_seed.sql` against an empty database.

`make help` lists shortcuts (`make install`, `make run`, `make test`, `make docker-up`, ...).

## Commands

| Command | What it does |
| --- | --- |
| `python -m ai_database_analyst run` | Start the web app (extra flags go to Streamlit, e.g. `--server.port=9000`) |
| `python -m ai_database_analyst check` | Check MySQL connectivity, schema access, and that the Ollama model is pulled |
| `python -m ai_database_analyst users add\|passwd\|remove\|disable\|enable\|list NAME` | Manage sign-in accounts |
| `python scripts/demo_validation.py` | Show the SQL validator allowing and blocking queries, no database or model needed |
| `python scripts/generate_seed_data.py` | Regenerate the synthetic demo dataset |

After `pip install .` the same commands are available as `ai-database-analyst ...`.

## Configuration

Every setting is an optional `ANALYST_*` environment variable (or `.env` entry) with a safe default; numeric values are clamped.
The most important ones:

| Variable | Default | Purpose |
| --- | --- | --- |
| `ANALYST_AUTH_MODE` | `local` | `local` users file · `proxy` SSO header · `none` development only |
| `ANALYST_DB_PASSWORD_FILE` | *(sidebar)* | Path to the database password (Docker secret) |
| `ANALYST_DB_SSL_CA` | *(off)* | CA bundle; enables verified TLS to MySQL |
| `ANALYST_DOMAIN_FILE` | *(generic)* | Business profile YAML ([docs](docs/DOMAINS.md)) |
| `ANALYST_MODEL` | `qwen2.5:3b` | Ollama model |
| `ANALYST_MAX_ROWS` | `500` | Result cap per query |
| `ANALYST_MAX_QUERIES_PER_MINUTE` | `20` | Per-user rate limit |
| `ANALYST_AUDIT_LOG` | `logs/audit.jsonl` | Audit trail location |

Full list with ranges, plus the audit event reference: [docs/CONFIGURATION.md](docs/CONFIGURATION.md).

## Documentation

| | |
| --- | --- |
| [Architecture](docs/ARCHITECTURE.md) | Request flow, modules, design decisions |
| [Demo guide](docs/DEMO.md) | A 10-minute script that shows features and proves the safety claims |
| [Deployment](docs/DEPLOYMENT.md) | Docker Compose, systemd, TLS proxy, SSO, hardening checklist |
| [Business profiles](docs/DOMAINS.md) | Adapt it to finance, HR, support, operations or your own domain |
| [Configuration](docs/CONFIGURATION.md) | Every setting and audit event |
| [Security](SECURITY.md) | Threat model, limits, how to report a vulnerability |
| [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) | |

## Project layout

```
ai_database_analyst/    the package (see docs/ARCHITECTURE.md for per-module responsibilities)
app.py                  Streamlit entry point (3 lines)
tests/                  offline unit tests (no MySQL, Ollama or network needed)
config/                 business profiles (retail demo, template, finance/HR/support examples)
docker/mysql-init/      demo schema, synthetic data, read-only user
scripts/                demo and maintenance helpers
docs/                   architecture, demo, deployment, configuration
.github/                CI workflow, Dependabot
```

## Development

```bash
make install-dev && make test && make lint
```

See [CONTRIBUTING.md](CONTRIBUTING.md). Tested with Python 3.12, streamlit 1.66, sqlglot 30.24, pandas 3.0,
mysql-connector-python 26.10.

## Known limitations

- No row-level permissions: all signed-in users can query whatever the database account can read.
- A small local model sometimes writes the wrong query. The SQL is always shown so people can judge it; use a larger model for accuracy.
- Login lockout and rate limiting are per process. Run one instance, or also limit at your proxy.
- MySQL only (the validator and prompts target the MySQL dialect).
- Single-database scope: questions are answered from one schema at a time.

## License

[MIT](LICENSE)
