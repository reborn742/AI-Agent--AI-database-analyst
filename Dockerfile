# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app

WORKDIR /app

# Dependencies first so this layer is cached until requirements.txt changes.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app.py ./
COPY .streamlit ./.streamlit
COPY ai_database_analyst ./ai_database_analyst
COPY scripts ./scripts
COPY config ./config

# Run as an unprivileged user. /app/data (users file) and /app/logs (audit log) are
# meant to be volumes; creating them here gives the volumes the right ownership.
RUN useradd --system --uid 10001 --create-home --home-dir /home/app --shell /usr/sbin/nologin app \
    && mkdir -p /app/data /app/logs \
    && chown -R app:app /app/data /app/logs
USER app

ENV ANALYST_USERS_FILE=/app/data/users.json \
    ANALYST_AUDIT_LOG=/app/logs/audit.jsonl

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
