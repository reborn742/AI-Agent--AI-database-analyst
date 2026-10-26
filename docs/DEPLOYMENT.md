# Deployment guide

Three supported ways to run it, from quickest to most controlled.

| Option | Use it for |
| --- | --- |
| [Docker Compose](#docker-compose) | Demos, pilots, a single internal server |
| [Virtual environment + systemd](#virtual-environment-and-systemd) | A server where Docker is not allowed |
| [Behind SSO](#behind-a-single-sign-on-proxy) | Company rollout: replaces the local users file |

## Prerequisites

- A MySQL 8 database with a **SELECT-only** account for the app (the Compose stack creates one for you).
- An [Ollama](https://ollama.com) server with the chosen model pulled (the Compose stack runs one).
- 8 GB RAM is comfortable for the default 3B model on CPU. A GPU makes answers near-instant.

## Docker Compose

```bash
python scripts/init_secrets.py                    # writes ./secrets/*.txt (random, git-ignored)
docker compose up -d --build
docker compose run --rm app python -m ai_database_analyst users add admin
```

- The app listens on `127.0.0.1:8501` only. Put a TLS reverse proxy in front (below) before sharing it.
- Data lives in named volumes: `db_data` (MySQL), `ollama_data` (models), `app_data` (users file), `app_logs` (audit log).
- Passwords are Docker secrets mounted as files. They never appear in `docker compose config`, the environment or the image.
- Use your own database instead of the demo one: remove the `db` service, set `ANALYST_DB_HOST`/`ANALYST_DB_NAME`/`ANALYST_DB_USER`
  on `app`, and point `secrets.analyst_db_password.file` at a file holding that account's password.
  Create the account with `GRANT SELECT ON yourdb.* TO 'analyst_readonly'@'%'`. The app's prompts prefer a view
  named `completed_sales`; see `docker/mysql-init/01_schema.sql` for the shape.

Day-2 operations:

```bash
docker compose logs -f app                        # application log (JSON)
docker compose exec app tail -f /app/logs/audit.jsonl
docker compose run --rm app python -m ai_database_analyst users list
docker compose pull && docker compose up -d --build   # upgrade
docker compose exec db sh -c 'mysqldump -uroot -p"$(cat /run/secrets/mysql_root_password)" --single-transaction retail_analytics' > backup.sql
```

## Virtual environment and systemd

```bash
sudo useradd --system --create-home --home-dir /opt/ai-database-analyst analyst
sudo -u analyst python3 -m venv /opt/ai-database-analyst/venv
sudo -u analyst /opt/ai-database-analyst/venv/bin/pip install /path/to/ai-database-analyst   # or the built wheel
sudo install -d -o analyst -g analyst -m 700 /opt/ai-database-analyst/data /opt/ai-database-analyst/logs
sudo install -d -m 750 -g analyst /etc/ai-database-analyst
sudo install -m 640 -g analyst /dev/null /etc/ai-database-analyst/db_password   # then put the password in it
```

`/etc/ai-database-analyst/analyst.env`:

```ini
ANALYST_DB_HOST=db.internal.example.com
ANALYST_DB_PASSWORD_FILE=/etc/ai-database-analyst/db_password
ANALYST_DB_SSL_CA=/etc/ssl/certs/company-ca.pem
ANALYST_USERS_FILE=/opt/ai-database-analyst/data/users.json
ANALYST_AUDIT_LOG=/opt/ai-database-analyst/logs/audit.jsonl
ANALYST_LOG_FORMAT=json
```

`/etc/systemd/system/ai-database-analyst.service`:

```ini
[Unit]
Description=AI Database Analyst
After=network-online.target

[Service]
User=analyst
WorkingDirectory=/opt/ai-database-analyst
EnvironmentFile=/etc/ai-database-analyst/analyst.env
ExecStart=/opt/ai-database-analyst/venv/bin/ai-database-analyst run --server.address=127.0.0.1 --server.port=8501 --server.headless=true
Restart=on-failure
NoNewPrivileges=true
ProtectSystem=strict
ReadWritePaths=/opt/ai-database-analyst
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo -u analyst bash -c 'set -a; . /etc/ai-database-analyst/analyst.env; set +a; \
    /opt/ai-database-analyst/venv/bin/ai-database-analyst users add admin'
sudo systemctl enable --now ai-database-analyst
```

## TLS reverse proxy

Streamlit uses WebSockets, so the proxy **must** forward the upgrade headers. Minimal nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name analyst.example.com;
    ssl_certificate     /etc/ssl/certs/analyst.crt;
    ssl_certificate_key /etc/ssl/private/analyst.key;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;   # local models can take a while
    }
}
```

## Behind a single sign-on proxy

Set `ANALYST_AUTH_MODE=proxy`. The app then skips its own login form and takes the username from the header named by
`ANALYST_PROXY_USER_HEADER` (default `X-Forwarded-User`), which your proxy must set after authenticating the user
(for example oauth2-proxy, Authelia, Pomerium, or an identity-aware cloud load balancer). Requests without the header are denied.
Every audit record then carries the company identity.

> **Critical:** in proxy mode anyone who can reach the app's port directly can forge the header.
> Bind the app to `127.0.0.1` or a private network, allow only the proxy to connect (firewall / security group / network policy),
> and have the proxy **strip any client-supplied copy** of the header before setting its own.

Example with oauth2-proxy: run it with `--pass-user-headers=true` and `--set-xauthrequest=true`, and in nginx use
`auth_request` and `proxy_set_header X-Forwarded-User $user;` from the auth response.

## Hardening checklist

- [ ] App reachable only through a TLS proxy; port 8501 not exposed publicly
- [ ] Database account has `SELECT` on the single analytics schema and nothing else
- [ ] `ANALYST_DB_SSL_CA` set when the database is not on the same host
- [ ] Password supplied via `ANALYST_DB_PASSWORD_FILE`, with 0640 permissions or a platform secret
- [ ] Authentication is `local` with strong passwords, or `proxy` with direct access blocked
- [ ] Audit log directory on persistent storage, shipped to your log platform, and retained per policy
- [ ] The database account sees only data that every app user may see (the app has no row-level permissions)
- [ ] Ollama bound to a private interface (it has no authentication of its own)
- [ ] Dependabot PRs reviewed; `pip-audit` results triaged
