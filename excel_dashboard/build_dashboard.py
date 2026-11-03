from pathlib import Path
import pandas as pd

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Border, Side, Alignment
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.formatting.rule import DataBarRule
from openpyxl.utils import get_column_letter

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
OUT = BASE / "output"
OUT.mkdir(exist_ok=True)

sales = pd.read_csv(DATA / "completed_sales.csv", parse_dates=["order_date"])
orders = pd.read_csv(DATA / "orders.csv", parse_dates=["order_date"])

# Validate source data before workbook generation.
required = {
    "order_id", "order_date", "customer_id", "customer_name",
    "region", "segment", "sales_channel", "product_id",
    "product_name", "category", "quantity", "unit_price",
    "unit_cost", "revenue", "estimated_gross_profit"
}
missing = required - set(sales.columns)
if missing:
    raise ValueError(f"Missing sales columns: {sorted(missing)}")

if sales.empty:
    raise ValueError("Completed sales dataset is empty.")

sales["month"] = sales["order_date"].dt.to_period("M").astype(str)

monthly = (
    sales.groupby("month")
    .agg(
        revenue=("revenue", "sum"),
        gross_profit=("estimated_gross_profit", "sum"),
        order_count=("order_id", "nunique"),
        units_sold=("quantity", "sum"),
    )
    .reset_index()
)

regions = (
    sales.groupby("region")
    .agg(
        revenue=("revenue", "sum"),
        gross_profit=("estimated_gross_profit", "sum"),
        orders=("order_id", "nunique"),
        units_sold=("quantity", "sum"),
    )
    .reset_index()
    .sort_values("revenue", ascending=False)
)

channels = (
    sales.groupby("sales_channel")
    .agg(
        revenue=("revenue", "sum"),
        gross_profit=("estimated_gross_profit", "sum"),
        orders=("order_id", "nunique"),
    )
    .reset_index()
    .sort_values("revenue", ascending=False)
)

products = (
    sales.groupby(["product_id", "product_name", "category"])
    .agg(
        units_sold=("quantity", "sum"),
        revenue=("revenue", "sum"),
        gross_profit=("estimated_gross_profit", "sum"),
        order_count=("order_id", "nunique"),
    )
    .reset_index()
    .sort_values("revenue", ascending=False)
)

customers = (
    sales.groupby(["customer_id", "customer_name", "region", "segment"])
    .agg(
        orders=("order_id", "nunique"),
        revenue=("revenue", "sum"),
        gross_profit=("estimated_gross_profit", "sum"),
    )
    .reset_index()
    .sort_values("revenue", ascending=False)
)

total_revenue = float(sales["revenue"].sum())
total_profit = float(sales["estimated_gross_profit"].sum())
total_orders = int(sales["order_id"].nunique())
total_customers = int(sales["customer_id"].nunique())
average_order_value = total_revenue / total_orders

wb = Workbook()
dashboard = wb.active
dashboard.title = "Dashboard"

# Consistent formatting.
navy = "17365D"
blue = "1F4E78"
light_blue = "D9EAF7"
white = "FFFFFF"
grey = "F2F2F2"
green = "70AD47"

def add_title(ws, title, subtitle=None):
    ws.sheet_view.showGridLines = False
    ws.merge_cells("A1:H1")
    cell = ws["A1"]
    cell.value = title
    cell.font = Font(name="Aptos Display", size=20, bold=True, color=white)
    cell.fill = PatternFill("solid", fgColor=navy)
    cell.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 38
    if subtitle:
        ws.merge_cells("A2:H2")
        ws["A2"] = subtitle
        ws["A2"].font = Font(italic=True, color="666666", size=10)

def add_table(ws, df, start_row=4, start_col=1, table_name="DataTable"):
    for j, column in enumerate(df.columns, start_col):
        cell = ws.cell(start_row, j, column)
        cell.font = Font(bold=True, color=white)
        cell.fill = PatternFill("solid", fgColor=blue)
        cell.alignment = Alignment(wrap_text=True)

    for i, row in enumerate(df.itertuples(index=False, name=None), start_row + 1):
        for j, value in enumerate(row, start_col):
            if pd.isna(value):
                value = None
            elif hasattr(value, "to_pydatetime"):
                value = value.to_pydatetime()
            elif hasattr(value, "item"):
                value = value.item()
            ws.cell(i, j, value)

    end_row = start_row + len(df)
    end_col = start_col + len(df.columns) - 1

    if len(df) > 0:
        ref = f"{get_column_letter(start_col)}{start_row}:{get_column_letter(end_col)}{end_row}"
        table = Table(displayName=table_name, ref=ref)
        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )
        ws.add_table(table)

    ws.freeze_panes = f"A{start_row + 1}"
    ws.auto_filter.ref = (
        f"A{start_row}:{get_column_letter(end_col)}{end_row}"
    ) if len(df) else None

    for col_idx, column in enumerate(df.columns, start_col):
        values = [str(column)] + [str(v) for v in df[column].dropna().head(100)]
        width = min(max(max(map(len, values)) + 3, 13), 32)
        ws.column_dimensions[get_column_letter(col_idx)].width = width

def format_numeric(ws, headers_row=4):
    headers = {
        cell.column: str(cell.value).lower()
        for cell in ws[headers_row]
        if cell.value is not None
    }
    for col, header in headers.items():
        if any(x in header for x in ["revenue", "profit", "price", "value"]):
            fmt = '#,##0.00;[Red]-#,##0.00'
        elif any(x in header for x in ["orders", "quantity", "units", "count"]):
            fmt = '#,##0'
        else:
            continue
        for row in range(headers_row + 1, ws.max_row + 1):
            ws.cell(row, col).number_format = fmt

# Dashboard
add_title(
    dashboard,
    "RETAIL SALES ANALYTICS",
    "Synthetic retail dataset | Completed orders only | Revenue and estimated gross profit",
)

dashboard["A4"] = "REPORTING PERIOD"
dashboard["A4"].font = Font(bold=True, color=navy)
dashboard["B4"] = (
    f"{sales['order_date'].min():%d %b %Y} - "
    f"{sales['order_date'].max():%d %b %Y}"
)

kpis = [
    ("Total Revenue", total_revenue),
    ("Estimated Gross Profit", total_profit),
    ("Completed Orders", total_orders),
    ("Average Order Value", average_order_value),
    ("Customers", total_customers),
]
positions = ["A6", "C6", "E6", "G6", "A10"]

for (label, value), position in zip(kpis, positions):
    cell = dashboard[position]
    row, col = cell.row, cell.column
    dashboard.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + 1)
    dashboard.cell(row, col, label)
    dashboard.cell(row, col).font = Font(bold=True, color=white, size=11)
    dashboard.cell(row, col).fill = PatternFill("solid", fgColor=blue)
    dashboard.cell(row, col).alignment = Alignment(horizontal="center")
    dashboard.merge_cells(start_row=row + 1, start_column=col, end_row=row + 1, end_column=col + 1)
    dashboard.cell(row + 1, col, value)
    dashboard.cell(row + 1, col).font = Font(bold=True, size=17, color=navy)
    dashboard.cell(row + 1, col).fill = PatternFill("solid", fgColor=light_blue)
    dashboard.cell(row + 1, col).alignment = Alignment(horizontal="center")
    dashboard.cell(row + 1, col).number_format = (
        '#,##0' if isinstance(value, int) else '#,##0.00'
    )

dashboard["A13"] = "Gross margin"
dashboard["A13"].font = Font(bold=True, color=navy)
dashboard["B13"] = total_profit / total_revenue if total_revenue else 0
dashboard["B13"].number_format = "0.0%"

# Analysis sheets
sheets = [
    ("Monthly Trends", monthly, "MonthlyTable"),
    ("Regions", regions, "RegionTable"),
    ("Channels", channels, "ChannelTable"),
    ("Products", products, "ProductTable"),
    ("Customers", customers, "CustomerTable"),
    ("Sales Data", sales, "SalesDataTable"),
]

for name, df, table_name in sheets:
    ws = wb.create_sheet(name)
    add_title(ws, name, "Filterable analysis table | Synthetic retail dataset")
    add_table(ws, df, table_name=table_name)
    format_numeric(ws)

# Charts on dashboard.
monthly_ws = wb["Monthly Trends"]
if len(monthly) > 0:
    chart = LineChart()
    chart.title = "Monthly Revenue and Gross Profit"
    chart.y_axis.title = "Amount"
    chart.x_axis.title = "Month"
    chart.height = 8
    chart.width = 17
    data = Reference(monthly_ws, min_col=2, max_col=3, min_row=4, max_row=4 + len(monthly))
    cats = Reference(monthly_ws, min_col=1, min_row=5, max_row=4 + len(monthly))
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    dashboard.add_chart(chart, "A16")

region_ws = wb["Regions"]
if len(regions) > 0:
    chart = BarChart()
    chart.type = "bar"
    chart.style = 10
    chart.title = "Revenue by Region"
    chart.x_axis.title = "Revenue"
    chart.y_axis.title = "Region"
    chart.height = 8
    chart.width = 14
    data = Reference(region_ws, min_col=2, min_row=4, max_row=4 + len(regions))
    cats = Reference(region_ws, min_col=1, min_row=5, max_row=4 + len(regions))
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    dashboard.add_chart(chart, "J16")

# Conditional formatting for key analysis columns.
for sheet_name in ["Regions", "Products", "Customers"]:
    ws = wb[sheet_name]
    for col in range(1, ws.max_column + 1):
        header = str(ws.cell(4, col).value).lower()
        if "revenue" in header or "profit" in header:
            letter = get_column_letter(col)
            ws.conditional_formatting.add(
                f"{letter}5:{letter}{ws.max_row}",
                DataBarRule(start_type="min", end_type="max", color=green),
            )

dashboard.freeze_panes = "A4"
dashboard.column_dimensions["A"].width = 23
dashboard.column_dimensions["B"].width = 19
for col in ["C", "D", "E", "F", "G", "H", "I"]:
    dashboard.column_dimensions[col].width = 17
dashboard.sheet_properties.pageSetUpPr.fitToPage = True
dashboard.page_setup.fitToWidth = 1
dashboard.sheet_view.zoomScale = 85

# Ask Excel to recalculate formulas if any are added later.
wb.calculation.fullCalcOnLoad = True
wb.calculation.forceFullCalc = True
wb.calculation.calcMode = "auto"

output_file = OUT / "retail_sales_dashboard.xlsx"
wb.save(output_file)

# Verify that the saved workbook can be reopened and contains expected sheets.
check = Workbook()
from openpyxl import load_workbook
check = load_workbook(output_file, read_only=False, data_only=False)

expected_sheets = [
    "Dashboard", "Monthly Trends", "Regions", "Channels",
    "Products", "Customers", "Sales Data"
]
if check.sheetnames != expected_sheets:
    raise RuntimeError(f"Unexpected workbook sheets: {check.sheetnames}")

if check["Sales Data"].max_row != len(sales) + 4:
    raise RuntimeError("Sales Data row count verification failed.")

print("Workbook created and reopened successfully.")
print(f"File: {output_file}")
print(f"Sheets: {', '.join(check.sheetnames)}")
print(f"Sales data rows: {len(sales):,}")
print(f"Revenue: {total_revenue:,.2f}")
print(f"Estimated gross profit: {total_profit:,.2f}")
