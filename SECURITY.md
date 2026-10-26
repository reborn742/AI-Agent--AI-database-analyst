# Security

## Threat model

The app lets people type English and runs the SQL a language model writes. The model is therefore treated as an
**untrusted author**: the question may be a prompt-injection attempt, and the model can also simply be wrong.

| Threat | Control |
| --- | --- |
| Model (or injected prompt) writes `DROP`, `DELETE`, `UPDATE`, DDL, stacked statements | Parsed with SQLGlot; only a single `SELECT` / `WITH` / set operation is accepted |
| Reading other databases or system tables (`mysql.user`, `information_schema`) | Schema allow-list built from the live database; unknown tables and columns are rejected |
| File access, locks, delays, server fingerprinting (`LOAD_FILE`, `INTO OUTFILE`, `SLEEP`, `GET_LOCK`, `VERSION()`) | Function deny-list plus allow-list for functions SQLGlot does not model; `INTO`, locking clauses and optimizer hints rejected |
| Syntax tricks (comments, odd whitespace, code fences) | Executed SQL is **regenerated from the syntax tree** (comments stripped) and validated a second time |
| Runaway or huge queries | Row cap enforced in the SQL and when fetching; `MAX_EXECUTION_TIME`; length and complexity limits |
| Personal or secret data reachable through generated SQL | Tables and columns hidden by the business profile (plus secret-looking names by default) are removed from the schema **and** blocked by the validator: `SELECT *`, bare names, aliases, subqueries and CTEs cannot reach them |
| Validator bug or bypass | Runs in `START TRANSACTION READ ONLY` as an account with `SELECT` only. Both must fail for a write to land |
| Unauthorised use | Sign-in (scrypt hashes, lockout, idle timeout) or SSO proxy identity |
| Brute-force and flooding | Per-account lockout; per-user query rate limit |
| Repudiation ("I never ran that") | Append-only JSON-lines audit log: user, time, question, SQL, outcome |
| Credential exposure | Password never stored in settings, logs or audit; supports secret files; users file mode 0600 |
| Data in transit | Optional verified TLS to MySQL (`ANALYST_DB_SSL_CA`); terminate TLS for browsers at a reverse proxy |
| Prompt injection via data returned to the explainer | Result rows are passed as JSON data inside a delimited block with `<` escaped, and the prompt states they are data, not instructions |

## What this does **not** protect against

State these plainly when assessing fit:

- **Row-level or column-level permissions.** Every signed-in user can query anything the database account can read.
  Give the app an account whose view of the data matches your *least*-privileged user, or deploy one instance per audience.
- **Wrong answers.** A model can write valid SQL that answers a different question. The generated SQL is always shown and the AI
  commentary is labelled, but important decisions should be checked against source data.
- **Sensitive data in questions and results.** Both go to your Ollama server and into the audit log (use
  `ANALYST_AUDIT_LOG_QUESTIONS=false` to store hashes instead). Ollama has no authentication; keep it on a private network.
- **Proxy-mode header forgery** if the app port is reachable without the proxy. See `docs/DEPLOYMENT.md`.
- **Multi-instance consistency.** Rate limiting and login lockout are held in memory per process. Run a single instance, or enforce
  limits at the proxy as well.
- **Audit tamper-resistance.** The log is append-only by convention. Ship it to a write-once log platform if you need that guarantee.

## Reporting a vulnerability

Please do **not** open a public issue for a security problem. Use GitHub's *Report a vulnerability* button on the
repository's Security tab (private advisory), or email the maintainers at the address listed on the repository profile.
Include steps to reproduce and the version (`ai-database-analyst --version`). You will receive an acknowledgement within
five working days.

## Supported versions

Only the latest release receives security fixes.
