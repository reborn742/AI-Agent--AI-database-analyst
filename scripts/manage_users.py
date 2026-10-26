"""Manage sign-in accounts (same as ``ai-database-analyst users ...``).

Run:  python scripts/manage_users.py add alice
"""

import sys

from ai_database_analyst.cli import main

if __name__ == "__main__":
    sys.exit(main(["users", *sys.argv[1:]]))
