#!/bin/bash
# Creates the least-privilege account the app connects with: SELECT on one database, nothing else.
# Run by the official mysql image's entrypoint after the schema and data are loaded.
# The password comes from a Docker secret, never from an environment variable.

if ! declare -F docker_process_sql >/dev/null; then
    # Executed rather than sourced: fall back to the mysql client.
    docker_process_sql() { mysql -uroot -p"${MYSQL_ROOT_PASSWORD}" "$@"; }
fi

# Strip CR as well as LF: secret files created on Windows end in CRLF, and a stray \r would
# become part of the MySQL password while the app (which strips it) sends the clean one.
analyst_password="$(tr -d '\r\n' < "${ANALYST_DB_PASSWORD_FILE:-/run/secrets/analyst_db_password}")"

docker_process_sql <<EOSQL
CREATE USER IF NOT EXISTS 'analyst_readonly'@'%' IDENTIFIED BY '${analyst_password}';
ALTER USER 'analyst_readonly'@'%' IDENTIFIED BY '${analyst_password}';
GRANT SELECT ON retail_analytics.* TO 'analyst_readonly'@'%';
FLUSH PRIVILEGES;
EOSQL
