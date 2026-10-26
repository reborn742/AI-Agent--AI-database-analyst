"""Package logger (terminal only; never log passwords or prompts).

Controlled by two environment variables, read directly (not via ``config``) so
that ``config`` itself can log:

* ``ANALYST_LOG_LEVEL``  DEBUG | INFO | WARNING | ERROR   (default INFO)
* ``ANALYST_LOG_FORMAT`` text | json                      (default text)
"""

from __future__ import annotations

import json
import logging
import os


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


def _level() -> int:
    name = os.environ.get("ANALYST_LOG_LEVEL", "INFO").strip().upper()
    level = logging.getLevelName(name)
    return level if isinstance(level, int) else logging.INFO


logger = logging.getLogger("ai_database_analyst")
if not logger.handlers:
    _handler = logging.StreamHandler()
    if os.environ.get("ANALYST_LOG_FORMAT", "text").strip().lower() == "json":
        _handler.setFormatter(_JsonFormatter())
    else:
        _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [analyst] %(message)s"))
    logger.addHandler(_handler)
    logger.setLevel(_level())
    logger.propagate = False
