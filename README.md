# Text-to-SQL Assistant 🛢️

Ask questions about an e-commerce database **in plain English** and get answers back as a
table. Behind the scenes, a free AI model writes the SQL for you, the query runs **read-only**
against a live PostgreSQL database, and the results are shown along with the exact SQL that was
generated.

> **Example:** You type *"Which 5 states have the most customers?"* → the assistant writes
> `SELECT customer_state, COUNT(*) ... GROUP BY ... ORDER BY ... LIMIT 5;` → runs it → shows you
> the table.

This is **Project B** of a two-part portfolio build:

- **Project A** (`../E-Commerce Analytics SQL + Power BI`) builds the database: it loads the
  [Olist Brazilian E-Commerce dataset](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce)
  (~100,000 real orders across 9 tables) into a free cloud PostgreSQL database and builds a Power BI
  dashboard on top.
- **Project B** (this folder) builds an AI assistant that lets anyone query *that same database*
  without knowing SQL.

You must set up Project A first, because Project B talks to the database Project A creates.

---

## Table of contents

1. [What this project demonstrates](#what-this-project-demonstrates)
2. [How it works (the big picture)](#how-it-works-the-big-picture)
3. [The tools used (all free)](#the-tools-used-all-free)
4. [Project layout — what every file does](#project-layout--what-every-file-does)
5. [The database it queries](#the-database-it-queries)
6. [Setup — step by step](#setup--step-by-step)
7. [Running the app](#running-the-app)
8. [The safety guardrails](#the-safety-guardrails-defense-in-depth)
9. [Evaluation — how we measure quality](#evaluation--how-we-measure-quality)
10. [Deploying for free](#deploying-for-free-hugging-face-spaces)
11. [Troubleshooting](#troubleshooting)
12. [Glossary](#glossary)

---

## What this project demonstrates

If you're reading this as a recruiter or as a beginner trying to learn, here's what's interesting:

- **Text-to-SQL** — turning natural language into correct database queries using an LLM.
- **Production thinking** — not just "call the AI," but error handling, automatic retries when the
  AI makes a mistake, and security guardrails so the AI can never damage the database.
- **Rigorous evaluation** — an 80-question benchmark that measures how often the AI gets the answer
  right, broken down by difficulty, and comparing two different AI models.

---

## How it works (the big picture)

```
        You type a question in English
                    │
                    ▼
   We build a "prompt" for the AI that includes:
     • the database structure (tables & columns)
     • a few example question→SQL pairs
     • your question
                    │
                    ▼
   The AI (Gemini or Groq) writes ONE SQL query
                    │
                    ▼
   Guardrails check the SQL is safe
     (must be a read-only SELECT, no DROP/DELETE, capped row count)
                    │
                    ▼
   Run the SQL on PostgreSQL using a READ-ONLY login
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
   ❌ error?                ✅ success?
   Send the error           Show the results
   back to the AI           table + the SQL
   and ask it to fix
   (up to 2 retries)
```

The "send the error back and ask the AI to fix it" part is called the **self-correction loop**.
It's what makes the assistant robust: if the AI references a column that doesn't exist, it sees the
database's error message and tries again.

---

## The tools used (all free)

| Purpose | Tool | Why |
|---|---|---|
| The AI that writes SQL | **Google Gemini 2.5 Flash** | Generous free API tier, strong at SQL |
| A second AI (for comparison) | **Groq — GPT OSS 120B** | Free, very fast; lets us compare two models |
| Database | **Supabase** (cloud PostgreSQL) | Free tier, reused from Project A |
| Web app interface | **Streamlit** | Turns a Python script into a web app with no front-end code |
| Hosting the live app | **Hugging Face Spaces** | Free public URL for your portfolio |

Using **two** AI providers is deliberate: it lets the evaluation compare "Model A vs Model B,"
which is a stronger story than testing just one.

---

## Project layout — what every file does

```
Text2SQL Project/
├── app.py                      # The Streamlit web app (the user interface)
├── requirements.txt            # Python packages this project needs
├── .env.example                # Template for your secret keys (copy to .env)
├── .env                        # YOUR secrets — never shared, never committed
├── .gitignore                  # Tells git which files to never upload
│
├── src/                        # The "brain" of the app, split into small pieces
│   ├── db.py                   # Opens a READ-ONLY connection to the database
│   ├── schema.py               # Reads the database structure into text for the AI
│   ├── prompt.py               # Builds the instructions + examples sent to the AI
│   ├── llm.py                  # Talks to Gemini and Groq behind one simple function
│   ├── generate.py             # Asks the AI for SQL and cleans up its response
│   ├── guardrails.py           # Safety checks on the SQL before running it
│   └── execute.py              # Runs the SQL + the self-correction retry loop
│
├── eval/                       # Measuring how good the assistant is
│   ├── benchmark.jsonl         # 80 test questions with hand-written correct SQL
│   └── run_eval.py             # Runs the test and prints an accuracy report
│
└── sql/                        # One-time database setup scripts (run in Supabase)
    ├── 00_readonly_role.sql        # Creates the read-only database login
    └── 01_readonly_rls_policies.sql# Lets that login actually read the data
```

### How the pieces connect

When you ask a question in `app.py`, this is the chain of calls:

1. `app.py` calls `execute.generate_and_run(...)`.
2. `execute.py` asks `generate.py` for SQL.
3. `generate.py` uses `prompt.py` to build the prompt (which uses the schema text from `schema.py`),
   then calls `llm.py` to reach the AI.
4. `execute.py` checks the returned SQL with `guardrails.py`.
5. `execute.py` runs it through the connection from `db.py`.
6. If it errors, `execute.py` loops back to step 2 with the error attached.

Each file is small and does one job — this makes the project easy to read and to test.

---

## The database it queries

The Olist dataset models a real online marketplace. The 8 tables this assistant uses:

| Table | What it holds |
|---|---|
| `customers` | One row per order's customer. **Note:** `customer_id` is per-order; `customer_unique_id` identifies the real person across orders. |
| `orders` | Each order, its status, and delivery timestamps |
| `order_items` | The products inside each order, with price and freight |
| `order_payments` | How each order was paid (type, installments, value) |
| `order_reviews` | The 1–5 star review for an order |
| `products` | Product details and category (Portuguese names) |
| `sellers` | Seller location |
| `product_category_name_translation` | Maps Portuguese category names → English |

**Two quirks the AI is told about** (in `src/schema.py`):
- To count real people, use `customer_unique_id`, **not** `customer_id`.
- Some product columns are misspelled in the source data: `product_name_lenght`,
  `product_description_lenght` (the typo "lenght" is real and must be used).

The `geolocation` table (~1 million messy rows) is intentionally left out to keep the AI prompt small.

---

## Setup — step by step

### Prerequisites
- **Project A must be done** — its database must exist and be loaded with data.
- **Python 3.9+** installed.

### Step 1 — Install the Python packages
```bash
pip install -r requirements.txt
```

### Step 2 — Create a read-only database login
By default the database login can do anything (read *and* write). We don't want the AI to ever be
able to delete data, so we create a special login that can **only read**.

In the **Supabase dashboard → SQL Editor**, run the contents of
[sql/00_readonly_role.sql](sql/00_readonly_role.sql) — but change the password first:

```sql
ALTER ROLE t2sql_readonly WITH PASSWORD 'a-strong-password-letters-and-digits-only';
```
> Avoid the characters `@ : / #` in the password — they break the database connection string.

### Step 3 — Let that login actually read the data
Project A turns on **Row-Level Security (RLS)** — a PostgreSQL feature that hides *all* rows from
any login unless a rule explicitly allows it. So the brand-new read-only login sees **zero rows**
until we add read rules.

In the **Supabase SQL Editor**, run the contents of
[sql/01_readonly_rls_policies.sql](sql/01_readonly_rls_policies.sql). It adds a "this login may read
this table" rule to all 8 tables, while keeping RLS on (so the public internet still can't read your
data).

> **Why this matters:** without this step, every question returns an empty result even though the
> data is there. This is the single most common setup mistake.

### Step 4 — Get two free AI API keys
- **Gemini:** https://aistudio.google.com/app/apikey
- **Groq:** https://console.groq.com/keys

### Step 5 — Fill in your secrets
Copy the template and open the new file:
```bash
cp .env.example .env
```
Edit `.env` so it has three lines:
```
DATABASE_URL_READONLY=postgresql://t2sql_readonly.<project-ref>:<password>@<host>:5432/postgres
GEMINI_API_KEY=your-gemini-key
GROQ_API_KEY=your-groq-key
```

**About the database URL** (this trips people up): Supabase's connection pooler requires the
**project reference appended to the username**. If Project A's URL uses
`postgres.ymfoghvgnxzdsqfghfmb`, then your read-only username is
`t2sql_readonly.ymfoghvgnxzdsqfghfmb` — same host, same port (`5432`), same database (`postgres`);
only the username and password change.

### Step 6 — Test the connection
```bash
python src/schema.py
```
If it prints the list of tables and columns, your database setup is correct. ✅

---

## Running the app

```bash
python -m streamlit run app.py
```
> If `streamlit run app.py` gives "command not recognized," use `python -m streamlit run app.py` —
> it's the same thing but works even when Streamlit isn't on your system PATH.

This opens `http://localhost:8501` in your browser. Then:
1. Pick a model in the sidebar (Gemini or Groq).
2. Type a question.
3. Click **Run** — you'll see the generated SQL, the results table, the retry count, and a CSV
   download button.

### Questions to try

**Easy:** *How many orders were delivered?* · *How many unique customers are there?* ·
*List all distinct order statuses.*

**Medium:** *What is the total revenue from delivered orders?* ·
*What are the top 5 product categories by revenue?* ·
*How many delivered orders were there each month?*

**Hard:** *Show monthly revenue with month-over-month growth.* ·
*What are the top 3 product categories by revenue in each state?* ·
*How does late delivery affect the average review score?*

**Should be blocked by guardrails:** *Delete all orders* · *Drop the customers table*

---

## The safety guardrails (defense in depth)

There are **two independent layers** protecting the database, so even if one fails the other holds:

1. **Application layer** — [src/guardrails.py](src/guardrails.py) inspects the AI's SQL *before*
   running it and rejects anything that:
   - doesn't start with `SELECT` or `WITH`,
   - contains a write/destructive keyword (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`,
     `TRUNCATE`, `GRANT`, `CREATE`, …),
   - contains more than one statement (blocks SQL injection via `;`).
   It also appends `LIMIT 1000` if the query has no limit, so a query can't accidentally pull
   millions of rows.

2. **Database layer** — the app logs in as the **read-only role** from Step 2. Even if a destructive
   query somehow got past the app checks, PostgreSQL itself refuses it (`permission denied`). This
   was verified during setup: a `CREATE TABLE` attempt by this login is rejected.

This "two layers" approach is called **defense in depth** — a standard security principle.

---

## Evaluation — how we measure quality

A demo that "usually works" isn't enough; we measure exactly how often it's right.

### The benchmark
[eval/benchmark.jsonl](eval/benchmark.jsonl) contains **80 test cases**, each a JSON line with a
question, the hand-written *correct* ("gold") SQL, and a difficulty label:

```json
{"id": 2, "difficulty": "easy", "question": "How many orders were delivered?", "gold_sql": "SELECT COUNT(*) FROM orders WHERE order_status = 'delivered';"}
```

The 80 are split **30 easy** (single table), **30 medium** (a join + grouping), and **20 hard**
(window functions, multiple joins — adapted from Project A's real analytical queries).

### The metric: execution accuracy
For each question we run **both** the AI's SQL and the gold SQL, then compare the **result sets**,
ignoring row/column order. If the two tables of results match, it's counted correct. This is better
than checking if the SQL *text* matches, because many different queries can be equally correct.

### Running it
```bash
python eval/run_eval.py --limit 10     # quick smoke test (first 10 questions)
python eval/run_eval.py                # full run: both models × self-correction on/off
```
It prints accuracy **overall and per difficulty tier**, for four configurations: Gemini and Groq,
each with the self-correction loop on and off — so you can see how much each model and the retry
loop help.

### Results

> ⏳ **Valid numbers pending a clean run.** The evaluation harness is complete and correct, but
> producing a full results table needs free-tier quota that resets daily — and an initial round of
> runs (plus debugging two harness bugs, below) used up today's budget across all providers. Run
> **one** of the commands below after the daily reset to populate this table.

Run a single clean configuration (fits one day's free budget):

```bash
# Gemini (flash-lite has the largest free daily allowance):
GEMINI_MODEL=gemini-2.5-flash-lite python eval/run_eval.py --provider gemini --self-correct-only --sleep 4
# Groq:
python eval/run_eval.py --provider groq --self-correct-only --sleep 1
```

| Config                                   | Overall | Easy | Medium | Hard |
|------------------------------------------|--------:|-----:|-------:|-----:|
| Gemini (flash-lite), self-correction ON  |       — |    — |      — |    — |
| Groq (Llama 3.3 70B), self-correction ON |       — |    — |      — |    — |

**Two correctness fixes made to the harness while validating it** (both would otherwise distort the
score):
- *Result comparison ignored column names.* A correct answer that aliased a column (`COUNT(*) AS
  total` vs the default `count`) was wrongly marked incorrect. Now the comparison ignores column
  names/order and normalizes numeric type and rounding, comparing only the set of result values.
- *Rate-limit handling.* Per-minute throttles were being misread as daily walls. The harness now
  backs off and retries on any 429, and **skips** (rather than fails) any question that never
  returns an answer — so accuracy is measured only over questions the model actually answered.

> **Why the free tiers run out:** the full matrix (80 questions × 2 models × 2 modes ≈ 320+ calls,
> with self-correction retries) far exceeds a single day's free budget. Run one configuration per
> provider per day; the harness paces itself and skips un-answerable (rate-limited) questions.

---

## Deploying for free (Hugging Face Spaces)

To get a public URL you can put on a resume:

1. Create a free **Streamlit Space** at https://huggingface.co/spaces.
2. Push this project's files to the Space's git repository.
3. In **Space Settings → Variables and secrets**, add three **secrets** (not public variables):
   `DATABASE_URL_READONLY`, `GEMINI_API_KEY`, `GROQ_API_KEY`.
4. The Space automatically installs `requirements.txt` and runs `app.py`. Done — share the URL.

> Never put your keys directly in the code. They live only in `.env` (local) or Space secrets
> (deployed). The `.gitignore` already prevents `.env` from being uploaded.

---

## Troubleshooting

| Symptom | Cause & fix |
|---|---|
| Every question returns **0 rows** but no error | RLS is blocking the read-only login. Run [sql/01_readonly_rls_policies.sql](sql/01_readonly_rls_policies.sql) in Supabase (Step 3). |
| `DATABASE_URL_READONLY is not set` | You haven't created `.env` or the variable name is wrong. Copy `.env.example` to `.env`. |
| Connection authentication fails | The pooler username needs the project ref, e.g. `t2sql_readonly.<project-ref>`. Also check the password has no `@ : / #`. |
| `streamlit: command not recognized` | Use `python -m streamlit run app.py`. |
| Gemini error `429 ... limit: 0` | That model has no free quota on your account/region. We use `gemini-2.5-flash`, which has free quota; change the model in `src/llm.py` if needed. |
| `permission denied for schema public` when reading | The read policies (Step 3) weren't applied, or were applied to the wrong role name. |

---

## Glossary

- **SQL** — the language for querying databases.
- **LLM** — Large Language Model; the AI that writes the SQL (Gemini, Llama).
- **PostgreSQL / Postgres** — the database system used here.
- **Supabase** — a service that hosts PostgreSQL databases with a free tier.
- **Prompt** — the full set of instructions + context sent to the AI.
- **Few-shot examples** — example question→SQL pairs included in the prompt to teach the AI the
  expected style.
- **Self-correction loop** — feeding the database's error message back to the AI so it can fix its
  own SQL.
- **Guardrails** — safety checks that block dangerous SQL.
- **RLS (Row-Level Security)** — a PostgreSQL feature that hides rows unless a rule allows access.
- **Execution accuracy** — the eval metric: did the AI's query produce the same results as the
  correct query?
- **Streamlit** — a Python library that turns scripts into web apps.

---

*Project B of a two-part build. See `../E-Commerce Analytics SQL + Power BI` for Project A (the
database and dashboard).*
