"""Turn a natural-language question into a clean SQL string."""

import re

from prompt import build_fix_prompt, build_prompt
import llm


def _strip_sql(text):
    """Remove markdown fences / stray prose the model sometimes adds."""
    if text is None:
        return ""
    text = text.strip()
    # Pull contents out of a ```sql ... ``` (or plain ``` ... ```) fence if present.
    fence = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence:
        text = fence.group(1)
    # Drop a leading "SQL:" label if the model echoed it.
    text = re.sub(r"^\s*SQL\s*:\s*", "", text, flags=re.IGNORECASE)
    return text.strip().rstrip(";").strip() + ";" if text.strip() else ""


def generate_sql(schema_text, question, provider="gemini"):
    """First-attempt SQL generation."""
    prompt = build_prompt(schema_text, question)
    return _strip_sql(llm.generate(prompt, provider))


def fix_sql(schema_text, question, bad_sql, error, provider="gemini"):
    """Self-correction: ask the model to repair SQL given the Postgres error."""
    prompt = build_fix_prompt(schema_text, question, bad_sql, error)
    return _strip_sql(llm.generate(prompt, provider))
