"""Show the SQL safety layer working, with no database, LLM or network needed.

Feeds a mix of legitimate and hostile SQL (the kind a model can be tricked into
producing) through the same validator the app uses, and prints the verdicts.

Run:  python scripts/demo_validation.py
"""

from __future__ import annotations

from ai_database_analyst.errors import QueryValidationError
from ai_database_analyst.schema import SchemaInfo
from ai_database_analyst.validation import validate_sql

SCHEMA = SchemaInfo.from_columns(
    {
        "customers": [
            ("customer_id", "int"),
            ("customer_name", "varchar"),
            ("region", "varchar"),
            ("segment", "varchar"),
        ],
        "products": [
            ("product_id", "int"),
            ("product_name", "varchar"),
            ("category", "varchar"),
            ("unit_cost", "decimal"),
        ],
        "orders": [("order_id", "int"), ("customer_id", "int"), ("order_date", "date"), ("status", "varchar")],
        "order_items": [("order_id", "int"), ("product_id", "int"), ("quantity", "int"), ("unit_price", "decimal")],
        "completed_sales": [
            ("product_name", "varchar"),
            ("quantity", "int"),
            ("line_revenue", "decimal"),
            ("region", "varchar"),
            ("order_date", "date"),
        ],
    }
)

CASES = [
    (
        "Top products (legitimate)",
        "SELECT product_name, SUM(quantity) AS units FROM completed_sales "
        "GROUP BY product_name ORDER BY units DESC LIMIT 5",
    ),
    ("No LIMIT: row cap is added", "SELECT product_name FROM completed_sales"),
    ("Huge LIMIT: lowered to the cap", "SELECT product_name FROM completed_sales LIMIT 9999999"),
    ("Markdown fence from the model", "```sql\nSELECT region FROM completed_sales\n```"),
    ("DROP TABLE", "DROP TABLE orders"),
    ("DELETE", "DELETE FROM orders WHERE 1=1"),
    ("UPDATE", "UPDATE customers SET segment = 'Enterprise'"),
    ("Stacked statements", "SELECT 1 FROM orders; DROP TABLE orders"),
    ("Write a file", "SELECT * FROM completed_sales INTO OUTFILE '/tmp/dump.csv'"),
    ("Read a file", "SELECT LOAD_FILE('/etc/passwd')"),
    ("Denial of service", "SELECT SLEEP(600) FROM orders"),
    ("Table outside the schema", "SELECT user, authentication_string FROM mysql.user"),
    ("information_schema probing", "SELECT table_name FROM information_schema.tables"),
    ("Unknown column", "SELECT c.credit_card_number FROM customers c"),
    ("Server fingerprinting", "SELECT VERSION(), CURRENT_USER()"),
    ("Optimizer hint", "SELECT /*+ MAX_EXECUTION_TIME(1) */ region FROM completed_sales"),
]


def main() -> int:
    width = max(len(label) for label, _ in CASES)
    unexpected = 0
    for label, sql in CASES:
        legitimate = "(legitimate)" in label or label.startswith(("No LIMIT", "Huge LIMIT", "Markdown"))
        try:
            result = validate_sql(sql, SCHEMA)
            verdict, detail = "ALLOWED", " ".join(result.sql.split())
            ok = legitimate
        except QueryValidationError as exc:
            verdict, detail = "BLOCKED", str(exc)
            ok = not legitimate
        unexpected += 0 if ok else 1
        print(f"{verdict:<8} {label:<{width}}  {detail[:90]}")
    print()
    print("All verdicts as expected." if not unexpected else f"{unexpected} unexpected verdict(s)!")
    return 1 if unexpected else 0


if __name__ == "__main__":
    raise SystemExit(main())
