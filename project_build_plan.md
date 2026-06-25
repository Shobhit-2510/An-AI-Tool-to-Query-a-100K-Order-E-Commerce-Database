# Build Plan: SQL Analytics + Text-to-SQL Assistant

Two connected projects sharing one PostgreSQL database. Build **Project A first**, then **Project B** on top of it. Target: OCS recruiting for analytics/data roles (Amex, Accenture).

**Core principle:** the database you build in A is the database B queries. Same schema, same data, one coherent story.

---

# PROJECT A — SQL-first Customer Analytics + Dashboard

**What you're proving:** that you can write real SQL (especially window functions), model a relational dataset, and translate query output into business recommendations. This is the day-job of an analytics consultant.

**Time:** ~1.5–2 weeks (most of it is learning the SQL patterns, not typing).

## Dataset

**Olist Brazilian E-Commerce** — search "Olist" on Kaggle, free download. ~100K orders across 9 relational CSV tables. The relational structure is the whole point: it forces JOINs and looks like a real business schema instead of a single churn CSV.

Tables you'll actually use:
- `orders` — order_id, customer_id, order_status, order_purchase_timestamp, order_approved_at, order_delivered_customer_date, order_estimated_delivery_date
- `customers` — customer_id, **customer_unique_id**, customer_state, customer_city
- `order_items` — order_id, product_id, seller_id, price, freight_value
- `order_payments` — order_id, payment_type, payment_installments, payment_value
- `order_reviews` — order_id, review_score
- `products`, `sellers`, `geolocation`, `product_category_name_translation`

### The one gotcha that will save you (and impress in interviews)

In Olist, `customer_id` is a **per-order key** — a new value for every order. The column that identifies a real person across multiple orders is **`customer_unique_id`** (in the customers table). So for any retention / repeat-purchase / RFM work, you must join `orders → customers` and aggregate on `customer_unique_id`, NOT `customer_id`. Get this wrong and your retention curves will look flat and wrong. Mention this nuance in your README — it signals you actually understood the data.

## Stack & setup

- **PostgreSQL**, not SQLite. Postgres is the stronger resume signal and supports the window functions you'll show off.
- Two hosting options — **pick Supabase** because Project B needs the DB reachable from a deployed app:
  - *Supabase free tier* → cloud-hosted Postgres with a connection string. Reused directly in Project B. **Recommended.**
  - *Local Docker* (`docker run postgres`) → simpler offline, but you'd have to host it again later.
- **Dashboard:** Tableau Public (gives a live shareable URL for your resume) OR Power BI (more in-demand keyword in corporate India). Either is fine — pick based on link-vs-keyword.
- DBeaver or the Supabase SQL editor for writing queries.

## Phase 1 — Setup & load (1–2 days)

- [ ] Create a Supabase project; note the connection string.
- [ ] Download the 9 Olist CSVs.
- [ ] Write `00_schema.sql` — `CREATE TABLE` for each, with sensible types (timestamps as `timestamp`, money as `numeric`) and primary/foreign keys.
- [ ] Load CSVs (`\copy` from psql, or Supabase's table import UI).
- [ ] Sanity-check row counts: ~99k orders, ~99k customers, ~112k order_items.

## Phase 2 — SQL analysis (the core, 5–7 days)

Write each as its own `.sql` file with a comment header stating the business question. These templates are correct starting points — adapt column names to your exact load.

### 2a. Monthly cohort retention

```sql
-- Question: of customers acquired in month X, what % purchase again in later months?
WITH first_purchase AS (
    SELECT c.customer_unique_id,
           DATE_TRUNC('month', MIN(o.order_purchase_timestamp)) AS cohort_month
    FROM orders o
    JOIN customers c ON o.customer_id = c.customer_id
    GROUP BY c.customer_unique_id
),
activity AS (
    SELECT c.customer_unique_id,
           DATE_TRUNC('month', o.order_purchase_timestamp) AS activity_month
    FROM orders o
    JOIN customers c ON o.customer_id = c.customer_id
)
SELECT f.cohort_month,
       (EXTRACT(YEAR FROM a.activity_month) - EXTRACT(YEAR FROM f.cohort_month)) * 12
         + (EXTRACT(MONTH FROM a.activity_month) - EXTRACT(MONTH FROM f.cohort_month)) AS month_offset,
       COUNT(DISTINCT a.customer_unique_id) AS active_customers
FROM first_purchase f
JOIN activity a ON f.customer_unique_id = a.customer_unique_id
GROUP BY 1, 2
ORDER BY 1, 2;
```

> Note: Olist is famously low-repeat-rate (~3% of customers reorder), so retention will be thin. That's fine — call it out as a *finding* ("acquisition-heavy, retention-weak business → recommend post-purchase reactivation"). A real insight beats a pretty curve.

### 2b. RFM segmentation with NTILE

```sql
-- Question: which customers are Champions vs At-Risk vs Hibernating?
WITH rfm AS (
    SELECT c.customer_unique_id,
           MAX(o.order_purchase_timestamp) AS last_order,
           COUNT(DISTINCT o.order_id) AS frequency,
           SUM(p.payment_value) AS monetary
    FROM orders o
    JOIN customers c ON o.customer_id = c.customer_id
    JOIN order_payments p ON o.order_id = p.order_id
    WHERE o.order_status = 'delivered'
    GROUP BY c.customer_unique_id
),
scored AS (
    SELECT *,
           NTILE(5) OVER (ORDER BY last_order ASC)  AS r_score,  -- older last_order = lower R
           NTILE(5) OVER (ORDER BY frequency ASC)   AS f_score,
           NTILE(5) OVER (ORDER BY monetary ASC)    AS m_score
    FROM rfm
)
SELECT *,
       CASE
         WHEN r_score >= 4 AND f_score >= 4 THEN 'Champions'
         WHEN r_score >= 3 AND f_score >= 3 THEN 'Loyal'
         WHEN r_score >= 4 AND f_score <= 2 THEN 'New / Promising'
         WHEN r_score <= 2 AND f_score >= 3 THEN 'At Risk'
         ELSE 'Hibernating'
       END AS segment
FROM scored;
```

### 2c. Order funnel (status flow)

```sql
-- Question: where do orders drop off between purchase and delivery?
SELECT order_status,
       COUNT(*) AS orders,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM orders
GROUP BY order_status
ORDER BY orders DESC;
```
Extend it: use timestamps (`order_purchase_timestamp` → `order_approved_at` → `order_delivered_customer_date`) to compute median hours at each stage, and a delivery-vs-estimate analysis (late deliveries vs `order_estimated_delivery_date`) — late delivery correlates with low review scores, which is a strong insight to surface.

### 2d. Month-over-month revenue growth (running totals + LAG)

```sql
-- Question: how is revenue trending month over month?
WITH monthly AS (
    SELECT DATE_TRUNC('month', o.order_purchase_timestamp) AS month,
           SUM(p.payment_value) AS revenue
    FROM orders o
    JOIN order_payments p ON o.order_id = p.order_id
    WHERE o.order_status = 'delivered'
    GROUP BY 1
)
SELECT month,
       revenue,
       SUM(revenue) OVER (ORDER BY month) AS running_total,
       LAG(revenue) OVER (ORDER BY month) AS prev_month,
       ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))
             / LAG(revenue) OVER (ORDER BY month), 2) AS mom_growth_pct
FROM monthly
ORDER BY month;
```

**Window-function coverage to hit** (recruiters screen for this): `NTILE`, `LAG`/`LEAD`, `ROW_NUMBER`, `RANK`/`DENSE_RANK`, running `SUM OVER`. Also throw in one query using each of `RANK` (e.g. top product categories by revenue per state) and `ROW_NUMBER` (e.g. each customer's first vs latest order) so all five appear somewhere in the repo.

## Phase 3 — Dashboard (2–3 days)

- [ ] Either point Tableau/Power BI at Postgres directly, or export query results to CSV and load those.
- [ ] Four views: cohort retention heatmap, RFM segment breakdown (size vs revenue), order/delivery funnel, revenue trend with MoM growth.
- [ ] One executive summary view up top with the headline numbers.
- [ ] If Tableau Public: publish and grab the URL.

## Phase 4 — Repo + recommendations (1 day)

Repo structure:
```
ecommerce-sql-analytics/
├── README.md
├── sql/
│   ├── 00_schema.sql
│   ├── 01_cohort_retention.sql
│   ├── 02_rfm_segmentation.sql
│   ├── 03_order_funnel.sql
│   ├── 04_mom_revenue.sql
│   └── 05_category_rankings.sql
├── dashboard/        (screenshots + link)
└── data/             (or a note on how to download — don't commit 100MB of CSV)
```

README must end with **3 concrete recommendations** tied to numbers, e.g.:
- "Champions = ~X% of customers but ~Y% of revenue → prioritize for loyalty spend."
- "~Z% of low review scores come from late deliveries → fix logistics in [states] first."
- "Repeat rate is only ~3% → the biggest lever is reactivation, not acquisition."

That business-translation step is what makes it consulting-relevant instead of a tech demo.

## Project A deliverables checklist
- [ ] Live Postgres DB (Supabase) loaded with all 9 tables
- [ ] 5–6 documented `.sql` files covering all five window-function types
- [ ] Published dashboard with shareable link
- [ ] GitHub repo with README ending in 3 numbered recommendations

## Project A resume bullets (fill blanks after building)
- Designed a PostgreSQL analytics layer over a 100K-order, 9-table e-commerce dataset, writing window-function queries (NTILE, LAG, running totals) for monthly cohort retention, RFM segmentation, and order/delivery funnels.
- Built an interactive [Tableau/Power BI] dashboard surfacing high-value segments and a late-delivery → low-review link, translating results into 3 targeted retention and logistics recommendations.

---

# PROJECT B — Text-to-SQL Assistant

**What you're proving:** range beyond your NCKU RAG work, production thinking (error handling, security), and rigorous evaluation. Evaluation is the centerpiece — it's where your internship experience becomes a visible edge.

**Time:** ~1 week (the DB already exists).

**Why text-to-SQL over a second RAG app:** it reuses Project A's database, and a second RAG project would look like a repeat of NCKU. Text-to-SQL shows you can do something new while staying in your lane.

## Architecture

```
NL question
   ↓
schema-aware prompt  (table schemas + sample rows + 3–4 few-shot examples)
   ↓
LLM generates SQL    (Claude or GPT)
   ↓
execute on Postgres (READ-ONLY user)
   ├── error?  → feed error back to LLM → retry (self-correction loop, max 2–3 tries)
   └── success → render table + the generated SQL
```

## Stack
- Python + Claude or GPT (direct API, or LangChain if you want the abstraction)
- **Streamlit** frontend (you already know it)
- Connects to the **same Supabase Postgres** from Project A
- Deploy on **Hugging Face Spaces** or **Streamlit Community Cloud** → working public link

## Phase 1 — Core pipeline (2 days)

- [ ] Function to introspect the schema: pull table names, columns, types (query `information_schema.columns`), plus 2–3 sample rows per table.
- [ ] Build the schema-aware prompt: schema text + few-shot examples (NL → correct SQL pairs drawn from your Phase-2 queries) + the user question. Instruct: "Return only a single read-only SQL query, no prose, no markdown fences."
- [ ] Execute the returned SQL, return results as a DataFrame.
- [ ] Minimal Streamlit UI: text box → run → show generated SQL + results table.

## Phase 2 — Self-correction loop (1 day)

The detail that signals production thinking:
- [ ] Wrap execution in try/except.
- [ ] On error, send the model: original question + the SQL it wrote + the exact Postgres error message + "fix it." Retry up to 2–3 times.
- [ ] Show the retry count in the UI (transparency).

## Phase 3 — Guardrails (half day)

Students forget this; engineers care about it. Call it out explicitly in your README.
- [ ] Create a **read-only Postgres role** in Supabase and connect the app with *that* user (defense in depth — even if the LLM emits `DROP TABLE`, the DB rejects it).
- [ ] App-level check: reject any generated SQL whose first keyword isn't `SELECT` / `WITH`; block `DROP`, `DELETE`, `UPDATE`, `INSERT`, `ALTER`, `TRUNCATE`.
- [ ] Add a `LIMIT` cap so a runaway query can't pull millions of rows.

## Phase 4 — Evaluation (the centerpiece, 2 days)

This is your differentiator. You did exactly this kind of rigorous eval at NCKU — doing it again on a different problem proves it wasn't a one-off.

- [ ] Build a benchmark of **80–100 pairs**: natural-language question + hand-written *gold* SQL. Cover easy (single table), medium (one JOIN + GROUP BY), and hard (window functions, multi-JOIN) tiers — label each by difficulty.
- [ ] Primary metric: **execution accuracy** — run both the generated SQL and the gold SQL, compare the returned result sets (order-insensitive). Match = correct. This is more meaningful than string-matching the SQL, since many different queries are equally right.
- [ ] Report accuracy overall **and broken down by difficulty tier** — the breakdown is what makes it look like real evaluation.
- [ ] Optional but strong: compare two models (Claude vs GPT) or with-vs-without the self-correction loop, and show the delta. That mirrors the before/after framing in your NCKU bullet.

Benchmark file format (`eval/benchmark.jsonl`):
```json
{"id": 1, "difficulty": "easy",   "question": "How many orders were delivered?", "gold_sql": "SELECT COUNT(*) FROM orders WHERE order_status='delivered';"}
{"id": 2, "difficulty": "hard",   "question": "Top 3 product categories by revenue in each state", "gold_sql": "..."}
```

## Phase 5 — Deploy & document (1 day)

- [ ] Push to Hugging Face Spaces / Streamlit Cloud with the Supabase connection as a secret (never hardcode keys).
- [ ] README: architecture diagram, the guardrails section, and an **eval results table** (accuracy by tier, model comparison).
- [ ] A short GIF of a question → SQL → results run in the UI.

Repo structure:
```
text-to-sql-assistant/
├── README.md
├── app.py                  (Streamlit)
├── src/
│   ├── schema.py           (introspection)
│   ├── generate.py         (prompt + LLM call)
│   ├── execute.py          (run + self-correction)
│   └── guardrails.py
├── eval/
│   ├── benchmark.jsonl     (80–100 pairs)
│   └── run_eval.py         (execution-accuracy harness)
└── requirements.txt
```

## Project B deliverables checklist
- [ ] Deployed Streamlit app with a public link, querying the live Supabase DB
- [ ] Self-correction retry loop
- [ ] Read-only user + app-level SQL guardrails (documented)
- [ ] 80–100 pair benchmark + execution-accuracy harness
- [ ] README with eval results table broken down by difficulty

## Project B resume bullets (fill blanks after building)
- Built a schema-aware text-to-SQL assistant (Claude/GPT + Streamlit) over a live PostgreSQL DB, with a self-correction loop that retries on execution errors and read-only guardrails blocking destructive queries.
- Evaluated on an __-pair NL→SQL benchmark, reaching __% execution accuracy (__ % on hard/window-function queries); deployed on Hugging Face Spaces.

---

# Suggested order & timeline

| Week | Focus |
|---|---|
| 1 | Project A — Phase 1–2 (setup + write all SQL) |
| 2 | Project A — Phase 3–4 (dashboard, repo, recommendations). **A is done & shippable.** |
| 3 | Project B — Phase 1–3 (pipeline, self-correction, guardrails) |
| 3–4 | Project B — Phase 4–5 (evaluation + deploy) |

Ship Project A fully before starting B — a finished project beats two half-built ones, and B depends on A's database existing.

**One framing rule across both:** lead bullets with the work and a meaningful metric (execution accuracy, % of revenue, retention rate), never "achieved X% accuracy" as the headline. That's the line between a student project and a hire-worthy one.
