"""Read-only Postgres connection for the Text-to-SQL app.

Connects with the DATABASE_URL_READONLY credential (a SELECT-only role on the
same Supabase database built in Project A). Mirrors the connection helper from
Project A's src/db.py, but deliberately points at the restricted role so the
database itself is the last line of defense against destructive SQL.
"""

import os
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def get_connection():
    """Return a psycopg2 connection using the read-only credential.

    On Hugging Face Spaces the variable is injected as a Space secret; locally
    it comes from .env.
    """
    url = os.environ.get("DATABASE_URL_READONLY")
    if not url:
        raise RuntimeError(
            "DATABASE_URL_READONLY is not set. Copy .env.example to .env and fill it in "
            "(or add it as a Space secret when deploying)."
        )
    return psycopg2.connect(url)
