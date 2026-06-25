"""Execute generated SQL against Postgres with a self-correction retry loop.

Flow per attempt:  generate (or fix) -> guardrail check -> run.
On a guardrail rejection or a Postgres error we feed the failure back to the
model and retry, up to max_retries times. The DB connection uses the read-only
role, so a write that slips past the guardrail is still refused by Postgres.
"""

from dataclasses import dataclass, field

import pandas as pd

from generate import fix_sql, generate_sql
from guardrails import enforce_limit, is_safe


@dataclass
class Result:
    question: str
    provider: str
    sql: str = ""            # final SQL actually executed (or last attempted)
    dataframe: object = None  # pandas.DataFrame on success, else None
    retries: int = 0          # number of correction attempts beyond the first
    success: bool = False
    error: str = ""
    attempts: list = field(default_factory=list)  # SQL tried, in order


def run_query(conn, sql):
    """Run a read-only query and return a DataFrame. Rolls back on failure so the
    connection stays usable for the next retry."""
    try:
        return pd.read_sql_query(sql, conn)
    except Exception:
        conn.rollback()
        raise


def generate_and_run(conn, schema_text, question, provider="gemini", max_retries=2,
                     limit_cap=1000):
    """Generate SQL for `question`, execute it, self-correct on error.

    Returns a Result. `retries` counts correction rounds (0 = first try worked).
    """
    res = Result(question=question, provider=provider)
    sql = generate_sql(schema_text, question, provider)

    for attempt in range(max_retries + 1):
        res.attempts.append(sql)
        res.sql = sql
        res.retries = attempt

        ok, reason = is_safe(sql)
        if not ok:
            error = f"Guardrail rejected query: {reason}"
        else:
            try:
                res.dataframe = run_query(conn, enforce_limit(sql, limit_cap))
                res.success = True
                res.error = ""
                return res
            except Exception as exc:  # Postgres / driver error
                error = str(exc).strip()

        res.error = error
        if attempt == max_retries:
            break
        # Self-correction: hand the model the failed SQL and the exact error.
        sql = fix_sql(schema_text, question, sql, error, provider)

    return res
