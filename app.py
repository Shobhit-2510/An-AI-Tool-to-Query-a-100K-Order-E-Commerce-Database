"""Streamlit UI for the Text-to-SQL assistant.

Ask a question in plain English -> the chosen free LLM writes SQL -> it runs
read-only on the Project A Supabase database -> results render. A self-correction
loop retries on errors and the retry count is shown for transparency.

Run locally:   streamlit run app.py
"""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from db import get_connection
from execute import generate_and_run
from llm import GEMINI_MODEL, GROQ_MODEL
from schema import get_schema_text

st.set_page_config(page_title="Text-to-SQL Assistant", page_icon="🛢️", layout="wide")

EXAMPLE_QUESTIONS = [
    "How many orders were delivered?",
    "What is the monthly revenue and month-over-month growth for delivered orders?",
    "Which 5 states have the most customers?",
    "What is the average review score for late vs on-time deliveries?",
    "Top 3 product categories by revenue in each state",
]


@st.cache_resource
def _conn():
    return get_connection()


@st.cache_data(show_spinner=False)
def _schema_text():
    return get_schema_text(_conn())


with st.sidebar:
    st.header("How it works")
    st.markdown(
        "1. Your question + the live DB schema go to the LLM.\n"
        "2. It returns a single SQL query.\n"
        "3. **Guardrails** check it (SELECT/WITH only, no writes, capped LIMIT).\n"
        "4. It runs on a **read-only** Postgres role.\n"
        "5. On error, the model sees the error and retries (self-correction)."
    )
    provider = st.radio(
        "Model",
        options=["gemini", "groq"],
        format_func=lambda p: f"Gemini ({GEMINI_MODEL})" if p == "gemini"
        else f"Groq ({GROQ_MODEL})",
    )
    max_retries = st.slider("Max self-correction retries", 0, 3, 2)

st.title("🛢️ Text-to-SQL Assistant")
st.caption("Ask questions about the Olist e-commerce database in plain English.")

with st.expander("Example questions"):
    for q in EXAMPLE_QUESTIONS:
        st.markdown(f"- {q}")

question = st.text_input(
    "Your question", placeholder="e.g. Which 5 states have the most customers?"
)
run = st.button("Run", type="primary")

if run and question.strip():
    with st.spinner(f"Asking {provider}…"):
        try:
            res = generate_and_run(
                _conn(), _schema_text(), question, provider, max_retries=max_retries
            )
        except Exception as exc:
            st.error(f"Setup error (check API keys / DB connection): {exc}")
            st.stop()

    if res.retries:
        st.info(f"Self-corrected after {res.retries} retry(ies).")

    st.subheader("Generated SQL")
    st.code(res.sql, language="sql")

    if res.success:
        df = res.dataframe
        st.subheader(f"Results — {len(df):,} row(s)")
        st.dataframe(df, use_container_width=True)
        st.download_button(
            "Download CSV", df.to_csv(index=False), "results.csv", "text/csv"
        )
    else:
        st.error(f"Query failed after {res.retries} retry(ies).")
        st.code(res.error)
elif run:
    st.warning("Please type a question first.")
