# Configuration reference

Every setting is an optional `ANALYST_*` environment variable (a `.env` file in the working directory is also read;
real environment variables win). Numeric values are clamped to a safe range, and invalid values fall back to the
default with a warning in the log. `.env.example` is a ready-to-copy template.

## Ollama

| Variable | Default | Notes |
| --- | --- | --- |
| `ANALYST_OLLAMA_URL` | `http://localhost:11434/api/generate` | Under Compose: `http://ollama:11434/api/generate` |
| `ANALYST_MODEL` | `qwen2.5:3b` | Any model pulled into Ollama |
| `ANALYST_NUM_CTX` | `8192` | 2048–16384. Business profiles, examples and wide schemas need room; keep identical for both calls so the model is not reloaded |
| `ANALYST_KEEP_ALIVE` | `30m` | How long Ollama keeps the model in memory |
| `ANALYST_SQL_READ_TIMEOUT_S` | `180` | 30–900 |
| `ANALYST_EXPLAIN_READ_TIMEOUT_S` | `180` | 30–900 |
| `ANALYST_SQL_MAX_TOKENS` | `600` | 64–2048 |
| `ANALYST_EXPLAIN_MAX_TOKENS` | `300` | 64–1024 |

## Business profile

| Variable | Default | Notes |
| --- | --- | --- |
| `ANALYST_DOMAIN_FILE` | *(empty = generic)* | YAML profile describing your business, metrics, glossary, examples and hidden data. See [DOMAINS.md](DOMAINS.md). Edits apply to the next question |
| `ANALYST_SQL_RETRIES` | `1` | 0–3 extra attempts when the model's SQL fails validation in a fixable way or MySQL reports a malformed query. Safety violations are never retried |

## MySQL

| Variable | Default | Notes |
| --- | --- | --- |
| `ANALYST_DB_HOST` / `ANALYST_DB_PORT` | `127.0.0.1` / `3306` | |
| `ANALYST_DB_NAME` | `retail_analytics` | |
| `ANALYST_DB_USER` | `analyst_readonly` | Must have `SELECT` only |
| `ANALYST_DB_SSL_CA` | *(empty)* | Path to a CA bundle. Enables TLS and verifies the server certificate |
| `ANALYST_DB_PASSWORD_FILE` | *(empty)* | Path to a file containing the password (Docker/Kubernetes secret). **Preferred** |
| `ANALYST_DB_PASSWORD` | *(empty)* | Password in the environment. Visible to anyone who can inspect the process; prefer the file form |

If neither password variable is set, each user types the password in the sidebar (it is kept only in that browser
session). If one is set, the sidebar field is hidden. The password is never part of `Settings` and never logged.

## Query limits

| Variable | Default | Notes |
| --- | --- | --- |
| `ANALYST_MAX_ROWS` | `500` | 1–5000. Enforced in the SQL itself and again when fetching |
| `ANALYST_QUERY_TIMEOUT_MS` | `10000` | 1000–120000. Applied as `MAX_EXECUTION_TIME` |
| `ANALYST_MAX_QUERIES_PER_MINUTE` | `20` | 1–600, per user |

## Authentication

| Variable | Default | Notes |
| --- | --- | --- |
| `ANALYST_AUTH_MODE` | `local` | `local` (users file) · `proxy` (trust SSO proxy header) · `none` (development only) |
| `ANALYST_USERS_FILE` | `data/users.json` | Created by `users add`, mode 0600 |
| `ANALYST_PROXY_USER_HEADER` | `X-Forwarded-User` | Proxy mode only |
| `ANALYST_MAX_LOGIN_ATTEMPTS` | `5` | Consecutive failures before lockout (1–100) |
| `ANALYST_LOGIN_LOCKOUT_S` | `300` | 10–86400 |
| `ANALYST_SESSION_TIMEOUT_MIN` | `60` | Idle time before sign-out (1–1440), local mode |

## Audit log

| Variable | Default | Notes |
| --- | --- | --- |
| `ANALYST_AUDIT_ENABLED` | `true` | If enabled but unwritable, the app refuses to start rather than run unaudited |
| `ANALYST_AUDIT_LOG` | `logs/audit.jsonl` | |
| `ANALYST_AUDIT_LOG_QUESTIONS` | `true` | `false` stores a SHA-256 of each question instead of its text |
| `ANALYST_AUDIT_MAX_BYTES` | `10485760` | Rotation size (10 MiB) |
| `ANALYST_AUDIT_BACKUPS` | `10` | Rotated files kept |

## Application log (stderr)

| Variable | Default | Notes |
| --- | --- | --- |
| `ANALYST_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `ANALYST_LOG_FORMAT` | `text` | `json` for log aggregators (the Compose file sets this) |

## Audit event reference

Each line is one JSON object with `ts` (UTC, ISO-8601), `event`, `user`, `app_version` and event-specific fields.

| `event` | Extra fields |
| --- | --- |
| `login_success`, `login_failure`, `login_locked`, `logout`, `session_timeout` | `session` |
| `query_ok` | `session`, `question`, `sql`, `rows`, `attempts`, `followup`, `query_s`, `elapsed_s` |
| `query_rejected` | `session`, `question`, `sql`, `reason` |
| `query_error` | `session`, `question`, `error_type`, `error_code`, `elapsed_s` |
| `rate_limited` | `session`, `retry_after_s` |
| `export_csv` | `session`, `rows`, `sql` |

Example:

```json
{"ts": "2026-10-25T14:03:11.482+00:00", "event": "query_ok", "user": "alice", "app_version": "0.3.0", "session": "9f1c2ab04e7d", "question": "Which 5 products sold the most units?", "sql": "SELECT ...", "rows": 5, "query_s": 0.02, "elapsed_s": 14.7}
```
