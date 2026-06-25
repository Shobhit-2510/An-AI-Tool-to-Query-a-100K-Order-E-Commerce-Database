"""App-level SQL safety checks (the first of two defense layers; the read-only
Postgres role is the second).

Even though the app connects as a SELECT-only user, we refuse anything that isn't
a plain read up front: it gives a clear message instead of a database error and
stops a runaway query from pulling the whole table.
"""

import re

# Statement-starting keywords we allow.
_ALLOWED_START = ("select", "with")

# Keywords that must never appear (write / DDL / privilege ops).
_FORBIDDEN = (
    "drop", "delete", "update", "insert", "alter", "truncate",
    "grant", "revoke", "create", "replace", "merge", "call",
    "copy", "vacuum", "comment", "execute", "do",
)


def _strip_comments(sql):
    """Remove -- line comments and /* */ block comments before keyword checks."""
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    return sql


def is_safe(sql):
    """Return (ok, reason). ok=True means the query is a single read-only statement."""
    if not sql or not sql.strip():
        return False, "Empty query."

    cleaned = _strip_comments(sql).strip()

    # Single statement only: a semicolon may appear only as the final character.
    inner = cleaned.rstrip(";")
    if ";" in inner:
        return False, "Multiple statements are not allowed."

    lowered = inner.lower()
    first_word = re.match(r"\s*([a-z]+)", lowered)
    if not first_word or first_word.group(1) not in _ALLOWED_START:
        return False, "Only SELECT or WITH queries are allowed."

    # Word-boundary match so columns like 'created_at' don't trip 'create'.
    for kw in _FORBIDDEN:
        if re.search(rf"\b{kw}\b", lowered):
            return False, f"Forbidden keyword detected: {kw.upper()}."

    return True, "ok"


def enforce_limit(sql, cap=1000):
    """Append LIMIT <cap> if the query has no top-level LIMIT already."""
    no_comments = _strip_comments(sql)
    if re.search(r"\blimit\b", no_comments, re.IGNORECASE):
        return sql
    return sql.rstrip().rstrip(";").rstrip() + f"\nLIMIT {cap};"
