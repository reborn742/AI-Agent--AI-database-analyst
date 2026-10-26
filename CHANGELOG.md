# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## [Unreleased]

### Fixed
- **"HTTP 404 from Ollama: model 'qwen2.5:3b' not found".** The model download (`ollama-pull`) was a separate job the app did not
  wait for, so the app could start, and users could ask questions, before the model existed. `docker-compose.yml` now starts the
  app only after the model is installed (the job skips the download when the model is already present, so restarts work offline).
  The app also checks Ollama's model list (`llm.model_status`): the sidebar shows ready / NOT INSTALLED / unreachable, a clear
  message with the exact fix is shown, and Analyze is disabled while the model is definitively missing. The 404 message now covers
  both local Ollama and Docker.
- **Docker login failure on Windows ("MySQL rejected the server's database credentials", MySQL error 1045).**
  `scripts/init_secrets.py` wrote CRLF line endings on Windows. The MySQL init script kept the stray `\r` in the
  `analyst_readonly` password while the app stripped it, so the credentials never matched. The script now always writes LF,
  `docker/mysql-init/03_readonly_user.sh` strips CR/LF, and `.gitattributes` keeps scripts and SQL on LF.
  Existing installs: delete `secrets/*.txt`, rerun `init_secrets.py`, then `docker compose down -v` and `up -d --build`.
- Password files with a UTF-8 BOM are accepted; UTF-16 files (PowerShell `Out-File`) give an actionable error instead of a traceback.
- The credentials error now names the setting the password came from and the account, and the sidebar shows the same.
  `python -m ai_database_analyst check` prints the password source and a 1045 hint.
- `tests/test_validation.py`: `SELEC garbage` parses as an alias in current sqlglot; the test now uses a real syntax error.
- Import ordering in `prompts.py` (ruff I001).

### Added (domain flexibility)
- **Business profiles** (`ANALYST_DOMAIN_FILE`, YAML): organisation context, preferred tables, metric definitions, glossary,
  rules, starter questions and worked SQL examples. The analyst is now domain-agnostic; nothing retail-specific is hard-coded.
  Ships with retail, finance, HR and support examples (`config/`).
- **Hidden data**: `hidden_tables` / `hidden_columns` (glob patterns) plus secret-looking column names by default, enforced in the
  validator (`SELECT *`, bare names, aliases, subqueries, CTEs).
- **Richer schema context**: primary keys, foreign keys, table and column comments are discovered and given to the model.
- **Self-repair**: fixable validation errors and malformed-query MySQL errors are fed back to the model for one more attempt
  (`ANALYST_SQL_RETRIES`); safety violations are never retried.
- **Follow-up questions** ("and only for Europe?") using the previous question and SQL as context.
- Today's date is given to the model so "last 12 months" and "this year" work.
- `check` validates the profile and its SQL examples against the live schema.

### Changed
- Default `ANALYST_NUM_CTX` is now 8192 to leave room for profiles and examples.

## [0.3.0]

### Added
- **Authentication**: local users file with scrypt-hashed passwords, lockout after repeated failures, idle-session timeout,
  and an SSO `proxy` mode. `ai-database-analyst users add|passwd|remove|disable|enable|list` to manage accounts.
- **Audit log**: append-only, rotated JSON-lines record of sign-ins, queries, rejections, errors, rate-limit hits and exports.
- **Per-user rate limiting** (`ANALYST_MAX_QUERIES_PER_MINUTE`).
- **Secrets handling**: `ANALYST_DB_PASSWORD_FILE` / `ANALYST_DB_PASSWORD`; the password is kept out of `Settings`.
- Optional verified TLS to MySQL (`ANALYST_DB_SSL_CA`).
- **Deployment**: `Dockerfile`, `docker-compose.yml` (app + seeded MySQL + Ollama, Docker secrets, non-root, health checks),
  demo schema and synthetic dataset, `Makefile`, `scripts/init_secrets.py`.
- **CLI**: `python -m ai_database_analyst run | check | users`; installable console script `ai-database-analyst`.
- **CI**: lint, tests (3.10 and 3.12), wheel build and install, Docker build, dependency audit; Dependabot; pre-commit.
- **Docs**: architecture diagram, demo guide, deployment guide, configuration reference, security model.
- `scripts/demo_validation.py`: shows the SQL safety layer without a database or model.
- JSON log format and log-level control (`ANALYST_LOG_FORMAT`, `ANALYST_LOG_LEVEL`).

### Changed
- Dependency ranges now have upper bounds.
- `scripts/db_check.py` is now a thin wrapper over `ai-database-analyst check`, which also verifies Ollama and the model.

## [0.2.0]
- Modular package layout, central configuration, SQLGlot validation, read-only execution, deterministic findings.
