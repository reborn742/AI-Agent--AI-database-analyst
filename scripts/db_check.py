"""Connectivity smoke test (kept for convenience; same as ``ai-database-analyst check``).

Run:  python scripts/db_check.py
"""

import sys

from ai_database_analyst.cli import main

if __name__ == "__main__":
    sys.exit(main(["check"]))
