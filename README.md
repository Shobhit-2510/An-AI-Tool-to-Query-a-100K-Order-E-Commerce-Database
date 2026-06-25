# Text-to-SQL Assistant (Olist e-commerce)

Ask questions about a real e-commerce database in plain English; a free LLM writes
the SQL, it runs **read-only** against the live PostgreSQL database, and you get a
results table back — with a self-correction retry loop, safety guardrails, and a
rigorous evaluation harness.

This is **Project B** of a two-part build. It queries the *same* Supabase PostgreSQL
database created in **Project A** (`../E-Commerce Analytics SQL + Power BI`), which
loads the 9-table [Olist Brazilian E-Commerce](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
dataset (~100K orders). Build Project A first.

> **All free tools:** Google **Gemini 2.0 Flash** + **Groq Llama 3.3 70B** (both free
> API tiers), Supabase free-tier Postgres (reused from Project A), Streamlit, and
> Hugging Face Spaces for the public deployment.

## Architecture

```
Natural-language question
   │
   ▼
schema-aware prompt  (live schema + Olist quirks + 4 few-shot NL→SQL examples)
   │
   ▼
LLM generates SQL    (Gemini 2.0 Flash  OR  Groq Llama 3.3 70B)
   │
   ▼
guardrails           (SELECT/WITH only · block writes/DDL · single statement · LIMIT cap)
   │
   ▼
execute on Postgres  (READ-ONLY role)
   ├── error?   → feed the exact error back to the LLM → retry (max 2–3)
   └── success  → render results table + the generated SQL
```

## Guardrails (defense in depth)

Two independent layers, both documented because engineers care about this:

1. **Database layer** — the app connects as a dedicated **read-only Postgres role**
   (`sql/00_readonly_role.sql`) that only has `SELECT`. Even if the model emits
   `DROP TABLE`, Postgres refuses it.
2. **Application layer** — [src/guardrails.py](src/guardrails.py) rejects any query
   whose first keyword isn't `SELECT`/`WITH`, blocks `DROP/DELETE/UPDATE/INSERT/ALTER/
   TRUNCATE/GRANT/CREATE/…`, refuses multiple statements, and appends a `LIMIT 1000`
   cap so a runaway query can't pull millions of rows.

## Project layout

```
app.py                 Streamlit UI
src/
  db.py                read-only psycopg2 connection (DATABASE_URL_READONLY)
  schema.py            information_schema introspection → compact schema prompt
  prompt.py            schema-aware prompt + few-shot examples (from Project A queries)
  llm.py               provider abstraction: Gemini + Groq behind generate()
  generate.py          question → clean SQL (+ self-correction fix prompt)
  guardrails.py        SQL safety checks + LIMIT enforcement
  execute.py           run query + self-correction retry loop
eval/
  benchmark.jsonl      80 NL→gold-SQL pairs, labelled easy / medium / hard
  run_eval.py          execution-accuracy harness (model × self-correction)
sql/
  00_readonly_role.sql one-time read-only role setup for Supabase
```

## Setup

1. **Build Project A** so the Supabase database exists and is loaded.
2. Create the read-only role: run [sql/00_readonly_role.sql](sql/00_readonly_role.sql)
   in the Supabase SQL editor (set a real password).
3. Get free API keys: [Google AI Studio](https://aistudio.google.com/app/apikey) (Gemini),
   [Groq Console](https://console.groq.com/keys).
4. Configure secrets:
   ```bash
   cp .env.example .env      # then fill in DATABASE_URL_READONLY, GEMINI_API_KEY, GROQ_API_KEY
   pip install -r requirements.txt
   ```

## Run

```bash
streamlit run app.py                 # the app
python src/schema.py                 # print the schema prompt (sanity check the DB connection)
python eval/run_eval.py --limit 10   # quick eval smoke test
python eval/run_eval.py              # full eval: both models × self-correction on/off
```

## Evaluation

The benchmark is **80 hand-written `(question, gold_sql)` pairs** across three tiers:
*easy* (single table), *medium* (one JOIN + GROUP BY), *hard* (window functions /
multi-JOIN — seeded from Project A's analytical queries).

The primary metric is **execution accuracy**: run both the generated SQL and the gold
SQL and compare the result sets **order-insensitively** — many different queries are
equally correct, so this beats string-matching the SQL. `run_eval.py` reports accuracy
overall and **by difficulty tier**, and sweeps **Gemini vs Groq** and **self-correction
on vs off** so you can see each delta.

### Results

_Fill in after running `python eval/run_eval.py` on your loaded database:_

| Config                         | Overall | Easy | Medium | Hard |
|--------------------------------|--------:|-----:|-------:|-----:|
| Gemini, self-correction ON     |       — |    — |      — |    — |
| Gemini, self-correction OFF    |       — |    — |      — |    — |
| Groq,   self-correction ON     |       — |    — |      — |    — |
| Groq,   self-correction OFF    |       — |    — |      — |    — |

## Deploy (Hugging Face Spaces)

1. Create a free **Streamlit** Space and push this repo.
2. In **Settings → Variables and secrets**, add `DATABASE_URL_READONLY`, `GEMINI_API_KEY`,
   and `GROQ_API_KEY` as secrets (never hardcode them).
3. The Space runs `app.py` against `requirements.txt` automatically.

## Notes

- Free-tier rate limits (Gemini ~15 req/min, Groq per-minute token caps): `run_eval.py`
  sleeps between calls and backs off on HTTP 429.
- The `geolocation` table (~1M messy rows, no PK) is intentionally excluded from the
  schema prompt to keep token use down; add it back in `src/schema.py` if needed.
- Execution-accuracy will occasionally mark a correct query wrong when gold rounds a
  number and the model doesn't (or vice versa) — an inherent limitation of comparing
  result sets, noted for transparency.
