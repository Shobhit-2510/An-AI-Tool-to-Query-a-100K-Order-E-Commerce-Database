"""Schema-aware prompt construction for text-to-SQL.

Few-shot examples are drawn from Project A's analytical queries (sql/01..06) so
the model sees the window-function patterns it is expected to reproduce.
"""

SYSTEM_INSTRUCTION = (
    "You are a PostgreSQL expert. Given a database schema and a question, return "
    "exactly ONE read-only SQL query that answers it. Rules:\n"
    "- Output SQL only. No prose, no explanation, no markdown code fences.\n"
    "- The query must be a single SELECT or WITH statement. Never write to the DB.\n"
    "- Use only the tables and columns in the schema. Prefer ANSI/PostgreSQL syntax.\n"
    "- When counting distinct customers/people, aggregate on customer_unique_id.\n"
)

# (question, gold_sql) pairs that showcase the target SQL idioms.
FEW_SHOTS = [
    (
        "How many orders were delivered?",
        "SELECT COUNT(*) FROM orders WHERE order_status = 'delivered';",
    ),
    (
        "What is the monthly revenue and month-over-month growth for delivered orders?",
        "WITH monthly AS (\n"
        "    SELECT DATE_TRUNC('month', o.order_purchase_timestamp) AS month,\n"
        "           SUM(p.payment_value) AS revenue\n"
        "    FROM orders o JOIN order_payments p ON o.order_id = p.order_id\n"
        "    WHERE o.order_status = 'delivered'\n"
        "    GROUP BY 1\n"
        ")\n"
        "SELECT month, revenue,\n"
        "       ROUND(100.0 * (revenue - LAG(revenue) OVER (ORDER BY month))\n"
        "             / NULLIF(LAG(revenue) OVER (ORDER BY month), 0), 2) AS mom_growth_pct\n"
        "FROM monthly ORDER BY month;",
    ),
    (
        "What are the top 3 product categories by revenue in each state?",
        "WITH csr AS (\n"
        "    SELECT c.customer_state,\n"
        "           COALESCE(t.product_category_name_english, p.product_category_name) AS category,\n"
        "           SUM(oi.price) AS revenue\n"
        "    FROM order_items oi\n"
        "    JOIN orders o    ON oi.order_id = o.order_id\n"
        "    JOIN customers c ON o.customer_id = c.customer_id\n"
        "    JOIN products p  ON oi.product_id = p.product_id\n"
        "    LEFT JOIN product_category_name_translation t\n"
        "           ON p.product_category_name = t.product_category_name\n"
        "    WHERE o.order_status = 'delivered'\n"
        "    GROUP BY c.customer_state, category\n"
        ")\n"
        "SELECT customer_state, category, revenue\n"
        "FROM (SELECT *, RANK() OVER (PARTITION BY customer_state ORDER BY revenue DESC) AS rnk\n"
        "      FROM csr) ranked\n"
        "WHERE rnk <= 3 ORDER BY customer_state, rnk;",
    ),
    (
        "How does late delivery affect average review score?",
        "SELECT CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date\n"
        "            THEN 'late' ELSE 'on_time' END AS delivery_bucket,\n"
        "       ROUND(AVG(r.review_score), 2) AS avg_review_score,\n"
        "       COUNT(*) AS reviews\n"
        "FROM orders o JOIN order_reviews r ON o.order_id = r.order_id\n"
        "WHERE o.order_status = 'delivered'\n"
        "  AND o.order_delivered_customer_date IS NOT NULL\n"
        "  AND o.order_estimated_delivery_date IS NOT NULL\n"
        "GROUP BY delivery_bucket;",
    ),
]


def build_prompt(schema_text, question, few_shots=FEW_SHOTS):
    """Assemble the full text prompt (system + schema + few-shots + question)."""
    parts = [SYSTEM_INSTRUCTION, "\n# Database schema\n", schema_text, "\n# Examples\n"]
    for q, sql in few_shots:
        parts.append(f"Question: {q}\nSQL: {sql}\n")
    parts.append(f"\n# Now answer this\nQuestion: {question}\nSQL:")
    return "\n".join(parts)


def build_fix_prompt(schema_text, question, bad_sql, error):
    """Prompt for the self-correction retry: same task + the failed SQL + error."""
    return (
        SYSTEM_INSTRUCTION
        + "\n# Database schema\n"
        + schema_text
        + "\n# A previous attempt failed. Fix it.\n"
        + f"Question: {question}\n"
        + f"Previous SQL:\n{bad_sql}\n"
        + f"PostgreSQL error:\n{error}\n"
        + "Return a corrected single read-only SQL query. SQL only.\nSQL:"
    )
