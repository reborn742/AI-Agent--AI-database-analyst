import re
from pathlib import Path
from datetime import date, timedelta

import pandas as pd
import sqlglot
from sqlglot import exp

ROOT = Path(__file__).resolve().parent.parent
SEED_FILE = ROOT / "docker" / "mysql-init" / "02_seed.sql"
OUTPUT = Path(__file__).resolve().parent / "data"

def convert_value(value):
    if isinstance(value, exp.Literal):
        if value.is_string:
            return value.this
        number = value.this
        return float(number) if "." in number else int(number)

    if isinstance(value, exp.Null):
        return None

    sql = value.sql(dialect="mysql")

    match = re.search(
        r"DATE_SUB\s*\(\s*(?:CURDATE\s*\(\s*\)|CURRENT_DATE(?:\s*\(\s*\))?)\s*,\s*INTERVAL\s+'?(\d+)'?\s+DAY",
        sql,
        re.IGNORECASE,
    )

    if match:
        return date.today() - timedelta(days=int(match.group(1)))

    raise ValueError(f"Unsupported SQL value: {sql}")

def main():
    statements = sqlglot.parse(
        SEED_FILE.read_text(encoding="utf-8"),
        read="mysql",
    )

    tables = {}

    for statement in statements:
        if not isinstance(statement, exp.Insert):
            continue

        target = statement.this

        if isinstance(target, exp.Schema):
            table = target.this.name
            columns = [column.name for column in target.expressions]
        else:
            raise ValueError(
                f"Unexpected INSERT target structure: {target}"
            )

        values = statement.expression

        if not isinstance(values, exp.Values):
            raise ValueError(f"Unexpected VALUES structure for {table}")

        rows = [
            [convert_value(value) for value in row.expressions]
            for row in values.expressions
        ]

        tables[table] = pd.DataFrame(rows, columns=columns)

    required = {"customers", "products", "orders", "order_items"}
    missing = required - tables.keys()

    if missing:
        raise ValueError(f"Missing seed tables: {sorted(missing)}")

    expected = {
        "customers": 80,
        "products": 20,
        "orders": 1400,
    }

    for table, count in expected.items():
        actual = len(tables[table])
        if actual != count:
            raise ValueError(
                f"{table}: expected {count} rows, found {actual}"
            )

    # Export only after source-table validation.
    OUTPUT.mkdir(parents=True, exist_ok=True)

    for name, frame in tables.items():
        frame.to_csv(OUTPUT / f"{name}.csv", index=False)

    sales = (
        tables["order_items"]
        .merge(tables["orders"], on="order_id")
        .merge(tables["customers"], on="customer_id")
        .merge(tables["products"], on="product_id")
    )

    sales = sales[sales["status"] == "completed"].copy()

    sales["revenue"] = sales["quantity"] * sales["unit_price_x"]
    sales["estimated_gross_profit"] = (
        sales["quantity"] *
        (sales["unit_price_x"] - sales["unit_cost"])
    )

    sales = sales.rename(columns={"unit_price_x": "unit_price"})
    sales.to_csv(OUTPUT / "completed_sales.csv", index=False)

    print("Extraction successful.")
    for name, frame in tables.items():
        print(f"{name}: {len(frame):,} rows")

    print(f"completed_sales: {len(sales):,} rows")
    print(f"Output: {OUTPUT}")

if __name__ == "__main__":
    main()
