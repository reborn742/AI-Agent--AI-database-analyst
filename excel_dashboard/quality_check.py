from pathlib import Path
import pandas as pd
from openpyxl import load_workbook

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
FILE = BASE / "output" / "retail_sales_dashboard.xlsx"

customers = pd.read_csv(DATA / "customers.csv")
products = pd.read_csv(DATA / "products.csv")
orders = pd.read_csv(DATA / "orders.csv")
items = pd.read_csv(DATA / "order_items.csv")
sales = pd.read_csv(DATA / "completed_sales.csv", parse_dates=["order_date"])

checks = []

def check(name, condition):
    checks.append((name, bool(condition)))

check("Customer IDs unique", customers.customer_id.is_unique)
check("Product IDs unique", products.product_id.is_unique)
check("Order IDs unique", orders.order_id.is_unique)
check("Order-item IDs unique", items.order_item_id.is_unique)

check("Order customer references valid",
      orders.customer_id.isin(customers.customer_id).all())
check("Order-item order references valid",
      items.order_id.isin(orders.order_id).all())
check("Order-item product references valid",
      items.product_id.isin(products.product_id).all())

check("Completed sales contain only completed orders",
      (sales.status == "completed").all())

revenue = (sales.quantity * sales.unit_price).sum()
profit = sales.estimated_gross_profit.sum()

expected_revenue = (
    sales.quantity * sales.unit_price
).sum()

expected_profit = (
    sales.quantity * (sales.unit_price - sales.unit_cost)
).sum()

check("Revenue calculation correct",
      abs(revenue - expected_revenue) < 0.01)
check("Gross profit calculation correct",
      abs(profit - expected_profit) < 0.01)

# Verify the aggregated reports reconcile to transaction detail.
monthly = sales.groupby(sales.order_date.dt.to_period("M"))["revenue"].sum()
regional = sales.groupby("region")["revenue"].sum()
channels = sales.groupby("sales_channel")["revenue"].sum()
products_total = sales.groupby("product_id")["revenue"].sum()
customers_total = sales.groupby("customer_id")["revenue"].sum()

for name, values in [
    ("Monthly", monthly),
    ("Regional", regional),
    ("Channel", channels),
    ("Product", products_total),
    ("Customer", customers_total),
]:
    check(f"{name} revenue reconciles",
          abs(values.sum() - revenue) < 0.01)

# Inspect generated workbook.
wb = load_workbook(FILE, data_only=False)

expected_sheets = {
    "Dashboard", "Monthly Trends", "Regions", "Channels",
    "Products", "Customers", "Sales Data"
}
check("All seven worksheets exist",
      expected_sheets.issubset(set(wb.sheetnames)))

check("Dashboard contains two charts",
      len(wb["Dashboard"]._charts) == 2)

check("Sales Data row count matches CSV",
      wb["Sales Data"].max_row == len(sales) + 4)

check("Sales Data has an Excel table",
      len(wb["Sales Data"].tables) == 1)

print("\nDATA QUALITY REPORT")
print("-" * 45)

for name, passed in checks:
    print(f"{'PASS' if passed else 'FAIL'} | {name}")

print("-" * 45)
print(f"Revenue: {revenue:,.2f}")
print(f"Estimated gross profit: {profit:,.2f}")
print(f"Completed orders: {sales.order_id.nunique():,}")
print(f"Completed sales lines: {len(sales):,}")
print(f"Checks passed: {sum(v for _, v in checks)}/{len(checks)}")

if not all(v for _, v in checks):
    raise SystemExit("QUALITY CHECK FAILED")

print("\nAll quality checks passed.")
