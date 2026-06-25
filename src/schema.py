"""Introspect the live database and render a compact, prompt-friendly schema.

The schema string is the most important part of the prompt: it grounds the LLM
in the real tables, columns, types and foreign keys, plus the two Olist quirks
that trip up naive queries.
"""

# Domain notes that introspection cannot infer but that the model must know.
SCHEMA_NOTES = """\
Important notes about this database (Olist Brazilian e-commerce):
- orders.customer_id is a PER-ORDER key (a new value for every order). To identify
  a real person across multiple orders, join orders -> customers and aggregate on
  customers.customer_unique_id, NOT customer_id.
- Product column names are misspelled in the source: use product_name_lenght and
  product_description_lenght (with the "lenght" typo).
- For readable English category names, LEFT JOIN products.product_category_name to
  product_category_name_translation.product_category_name.
- Money lives in order_payments.payment_value (what the customer paid) and in
  order_items.price / order_items.freight_value (item + shipping). Pick the one the
  question implies; revenue analyses in Project A use payment_value.
- order_status values include: delivered, shipped, canceled, unavailable, invoiced,
  processing, created, approved. Most analyses filter order_status = 'delivered'.
"""

# Public tables we expose. geolocation is excluded: ~1M messy rows, no PK, no FK,
# and it bloats the prompt without helping typical questions.
INCLUDE_TABLES = (
    "customers",
    "sellers",
    "products",
    "product_category_name_translation",
    "orders",
    "order_items",
    "order_payments",
    "order_reviews",
)

_COLUMNS_SQL = """
    SELECT table_name, column_name, data_type, ordinal_position
    FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = ANY(%s)
    ORDER BY table_name, ordinal_position;
"""

_FK_SQL = """
    SELECT tc.table_name        AS from_table,
           kcu.column_name      AS from_column,
           ccu.table_name       AS to_table,
           ccu.column_name      AS to_column
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
      ON tc.constraint_name = kcu.constraint_name
     AND tc.table_schema    = kcu.table_schema
    JOIN information_schema.constraint_column_usage ccu
      ON tc.constraint_name = ccu.constraint_name
     AND tc.table_schema    = ccu.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
      AND tc.table_schema = 'public'
      AND tc.table_name = ANY(%s)
    ORDER BY from_table, from_column;
"""


def get_schema_text(conn, include_tables=INCLUDE_TABLES):
    """Build a compact schema description (tables, columns, types, FKs) + notes."""
    tables = list(include_tables)
    with conn.cursor() as cur:
        cur.execute(_COLUMNS_SQL, (tables,))
        columns = cur.fetchall()
        cur.execute(_FK_SQL, (tables,))
        fks = cur.fetchall()

    cols_by_table = {}
    for table_name, column_name, data_type, _pos in columns:
        cols_by_table.setdefault(table_name, []).append(f"{column_name} {data_type}")

    fks_by_table = {}
    for from_table, from_column, to_table, to_column in fks:
        fks_by_table.setdefault(from_table, []).append(
            f"{from_column} -> {to_table}.{to_column}"
        )

    lines = ["Tables (PostgreSQL):"]
    for table in tables:
        cols = cols_by_table.get(table)
        if not cols:
            continue
        lines.append(f"\n{table}(")
        lines.append("  " + ",\n  ".join(cols))
        lines.append(")")
        if table in fks_by_table:
            lines.append("  foreign keys: " + "; ".join(fks_by_table[table]))

    return "\n".join(lines) + "\n\n" + SCHEMA_NOTES


def get_sample_rows(conn, table, n=3):
    """Return up to n sample rows for grounding (list of column-keyed dicts)."""
    if table not in INCLUDE_TABLES:
        raise ValueError(f"Refusing to sample unknown table: {table!r}")
    with conn.cursor() as cur:
        cur.execute(f"SELECT * FROM {table} LIMIT %s;", (n,))
        col_names = [d[0] for d in cur.description]
        return [dict(zip(col_names, row)) for row in cur.fetchall()]


if __name__ == "__main__":
    from db import get_connection

    conn = get_connection()
    try:
        print(get_schema_text(conn))
    finally:
        conn.close()
