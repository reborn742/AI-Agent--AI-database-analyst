
from pathlib import Path

import pandas as pd
from openpyxl import Workbook, load_workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import DataBarRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

# ============================================================
# 1. PATHS AND CONFIGURATION
# ============================================================

BASE = Path(__file__).resolve().parent
DATA = BASE / "data"
OUT = BASE / "output"

OUT.mkdir(exist_ok=True)

OUTPUT_FILE = OUT / "retail_sales_dashboard_v2.xlsx"


# ============================================================
# 2. LOAD DATA
# ============================================================

sales = pd.read_csv(
    DATA / "completed_sales.csv",
    parse_dates=["order_date"],
)

orders = pd.read_csv(
    DATA / "orders.csv",
    parse_dates=["order_date"],
)

required_columns = {
    "order_id",
    "order_date",
    "customer_id",
    "customer_name",
    "region",
    "segment",
    "sales_channel",
    "product_id",
    "product_name",
    "category",
    "quantity",
    "unit_price",
    "unit_cost",
    "revenue",
    "estimated_gross_profit",
}

missing_columns = required_columns - set(sales.columns)

if missing_columns:
    raise ValueError(
        f"Missing sales columns: {sorted(missing_columns)}"
    )

if sales.empty:
    raise ValueError("Completed sales dataset is empty.")

if sales["order_date"].isna().any():
    raise ValueError("Sales data contains invalid order dates.")

if sales["order_id"].isna().any():
    raise ValueError("Sales data contains missing order IDs.")

sales["month"] = (
    sales["order_date"]
    .dt.to_period("M")
    .astype(str)
)


# ============================================================
# 3. DATA ANALYSIS
# ============================================================

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
    sales.groupby(
        ["product_id", "product_name", "category"]
    )
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
    sales.groupby(
        ["customer_id", "customer_name", "region", "segment"]
    )
    .agg(
        orders=("order_id", "nunique"),
        revenue=("revenue", "sum"),
        gross_profit=("estimated_gross_profit", "sum"),
    )
    .reset_index()
    .sort_values("revenue", ascending=False)
)


# ============================================================
# 4. KPI CALCULATIONS
# ============================================================

total_revenue = float(sales["revenue"].sum())

total_profit = float(
    sales["estimated_gross_profit"].sum()
)

total_orders = int(
    sales["order_id"].nunique()
)

total_customers = int(
    sales["customer_id"].nunique()
)

average_order_value = (
    total_revenue / total_orders
    if total_orders
    else 0
)

gross_margin = (
    total_profit / total_revenue
    if total_revenue
    else 0
)


# ============================================================
# 5. WORKBOOK AND STYLES
# ============================================================

wb = Workbook()

dashboard = wb.active
dashboard.title = "Dashboard"

# Color palette
navy = "17365D"
blue = "1F4E78"
light_blue = "D9EAF7"
white = "FFFFFF"
grey = "F2F2F2"
green = "70AD47"

thin_grey = "D9E1F2"


# ============================================================
# 6. REUSABLE FUNCTIONS
# ============================================================

def add_title(ws, title, subtitle=None, end_col=8):

    ws.sheet_view.showGridLines = False

    ws.merge_cells(
        start_row=1,
        start_column=1,
        end_row=1,
        end_column=end_col,
    )

    title_cell = ws.cell(1, 1)

    title_cell.value = title

    title_cell.font = Font(
        name="Aptos Display",
        size=20,
        bold=True,
        color=white,
    )

    title_cell.fill = PatternFill(
        "solid",
        fgColor=navy,
    )

    title_cell.alignment = Alignment(
        vertical="center",
    )

    ws.row_dimensions[1].height = 38

    if subtitle:

        ws.merge_cells(
            start_row=2,
            start_column=1,
            end_row=2,
            end_column=end_col,
        )

        subtitle_cell = ws.cell(2, 1)

        subtitle_cell.value = subtitle

        subtitle_cell.font = Font(
            italic=True,
            color="666666",
            size=10,
        )

        subtitle_cell.alignment = Alignment(
            vertical="center",
        )


def add_table(
    ws,
    df,
    start_row=4,
    start_col=1,
    table_name="DataTable",
):

    # Header
    for j, column in enumerate(
        df.columns,
        start_col,
    ):

        cell = ws.cell(
            start_row,
            j,
            column,
        )

        cell.font = Font(
            bold=True,
            color=white,
        )

        cell.fill = PatternFill(
            "solid",
            fgColor=blue,
        )

        cell.alignment = Alignment(
            wrap_text=True,
            vertical="center",
        )

    # Data
    for i, row in enumerate(
        df.itertuples(index=False, name=None),
        start_row + 1,
    ):

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

    # Excel table
    if len(df) > 0:

        table_range = (
            f"{get_column_letter(start_col)}{start_row}:"
            f"{get_column_letter(end_col)}{end_row}"
        )

        table = Table(
            displayName=table_name,
            ref=table_range,
        )

        table.tableStyleInfo = TableStyleInfo(
            name="TableStyleMedium2",
            showFirstColumn=False,
            showLastColumn=False,
            showRowStripes=True,
            showColumnStripes=False,
        )

        ws.add_table(table)

    ws.freeze_panes = f"A{start_row + 1}"

    if len(df) > 0:

        ws.auto_filter.ref = (
            f"A{start_row}:"
            f"{get_column_letter(end_col)}{end_row}"
        )

    # Column widths
    for col_idx, column in enumerate(
        df.columns,
        start_col,
    ):

        values = (
            [str(column)]
            + [
                str(v)
                for v in df[column].dropna().head(100)
            ]
        )

        width = min(
            max(max(map(len, values)) + 3, 13),
            32,
        )

        ws.column_dimensions[
            get_column_letter(col_idx)
        ].width = width


def format_numeric(ws, headers_row=4):

    headers = {
        cell.column: str(cell.value).lower()
        for cell in ws[headers_row]
        if cell.value is not None
    }

    for col, header in headers.items():

        if any(
            term in header
            for term in [
                "revenue",
                "profit",
                "price",
                "value",
            ]
        ):

            number_format = (
                '#,##0.00;[Red]-#,##0.00'
            )

        elif any(
            term in header
            for term in [
                "orders",
                "quantity",
                "units",
                "count",
            ]
        ):

            number_format = "#,##0"

        else:
            continue

        for row in range(
            headers_row + 1,
            ws.max_row + 1,
        ):

            ws.cell(
                row,
                col,
            ).number_format = number_format


def add_kpi(ws, label, value, position, number_format):

    cell = ws[position]

    row = cell.row
    col = cell.column

    # KPI label
    ws.merge_cells(
        start_row=row,
        start_column=col,
        end_row=row,
        end_column=col + 1,
    )

    label_cell = ws.cell(row, col)

    label_cell.value = label

    label_cell.font = Font(
        bold=True,
        color=white,
        size=10,
    )

    label_cell.fill = PatternFill(
        "solid",
        fgColor=blue,
    )

    label_cell.alignment = Alignment(
        horizontal="center",
        vertical="center",
        wrap_text=True,
    )

    # KPI value
    ws.merge_cells(
        start_row=row + 1,
        start_column=col,
        end_row=row + 1,
        end_column=col + 1,
    )

    value_cell = ws.cell(row + 1, col)

    value_cell.value = value

    value_cell.font = Font(
        bold=True,
        size=15,
        color=navy,
    )

    value_cell.fill = PatternFill(
        "solid",
        fgColor=light_blue,
    )

    value_cell.alignment = Alignment(
        horizontal="center",
        vertical="center",
    )

    value_cell.number_format = number_format


# ============================================================
# 7. DASHBOARD TITLE
# ============================================================

add_title(
    dashboard,
    "RETAIL SALES ANALYTICS",
    (
        "Synthetic retail dataset | Completed orders only | "
        "Revenue and estimated gross profit"
    ),
    end_col=12,
)

dashboard.sheet_view.showGridLines = False


# ============================================================
# 8. REPORTING PERIOD
# ============================================================

dashboard["A4"] = "REPORTING PERIOD"

dashboard["A4"].font = Font(
    bold=True,
    color=navy,
)

dashboard["B4"] = (
    f"{sales['order_date'].min():%d %b %Y} - "
    f"{sales['order_date'].max():%d %b %Y}"
)

dashboard["B4"].font = Font(
    color="333333",
    size=10,
)

dashboard["A4"].alignment = Alignment(
    vertical="center",
)

dashboard.row_dimensions[4].height = 24


# ============================================================
# 9. SIX KPI CARDS
# ============================================================

kpis = [
    (
        "Total Revenue",
        total_revenue,
        "#,##0.00",
    ),
    (
        "Estimated Gross Profit",
        total_profit,
        "#,##0.00",
    ),
    (
        "Completed Orders",
        total_orders,
        "#,##0",
    ),
    (
        "Average Order Value",
        average_order_value,
        "#,##0.00",
    ),
    (
        "Customers",
        total_customers,
        "#,##0",
    ),
    (
        "Gross Margin",
        gross_margin,
        "0.0%",
    ),
]

kpi_positions = [
    "A6",
    "C6",
    "E6",
    "G6",
    "I6",
    "K6",
]

for (
    label,
    value,
    number_format,
), position in zip(
    kpis,
    kpi_positions,
):

    add_kpi(
        dashboard,
        label,
        value,
        position,
        number_format,
    )

dashboard.row_dimensions[6].height = 25
dashboard.row_dimensions[7].height = 32


# ============================================================
# 10. ANALYSIS WORKSHEETS
# ============================================================

sheets = [
    (
        "Monthly Trends",
        monthly,
        "MonthlyTable",
    ),
    (
        "Regions",
        regions,
        "RegionTable",
    ),
    (
        "Channels",
        channels,
        "ChannelTable",
    ),
    (
        "Products",
        products,
        "ProductTable",
    ),
    (
        "Customers",
        customers,
        "CustomerTable",
    ),
    (
        "Sales Data",
        sales,
        "SalesDataTable",
    ),
]

for name, df, table_name in sheets:

    ws = wb.create_sheet(name)

    add_title(
        ws,
        name,
        "Filterable analysis table | Synthetic retail dataset",
    )

    add_table(
        ws,
        df,
        table_name=table_name,
    )

    format_numeric(ws)


# ============================================================
# 11. MONTHLY REVENUE AND PROFIT CHART
# ============================================================

monthly_ws = wb["Monthly Trends"]

if len(monthly) > 0:

    chart = LineChart()

    chart.title = "Monthly Revenue and Gross Profit"

    chart.y_axis.title = "Amount"
    chart.x_axis.title = "Month"

    chart.height = 8.5
    chart.width = 14

    chart.style = 13

    chart.legend.position = "b"

    data = Reference(
        monthly_ws,
        min_col=2,
        max_col=3,
        min_row=4,
        max_row=4 + len(monthly),
    )

    categories = Reference(
        monthly_ws,
        min_col=1,
        min_row=5,
        max_row=4 + len(monthly),
    )

    chart.add_data(
        data,
        titles_from_data=True,
    )

    chart.set_categories(categories)

    chart.y_axis.numFmt = '#,##0'

    dashboard.add_chart(
        chart,
        "A10",
    )


# ============================================================
# 12. REGIONAL REVENUE CHART
# ============================================================

region_ws = wb["Regions"]

if len(regions) > 0:

    chart = BarChart()

    chart.type = "bar"
    chart.style = 10

    chart.title = "Revenue by Region"

    chart.x_axis.title = "Revenue"
    chart.y_axis.title = "Region"

    chart.height = 8.5
    chart.width = 14

    chart.legend = None

    data = Reference(
        region_ws,
        min_col=2,
        min_row=4,
        max_row=4 + len(regions),
    )

    categories = Reference(
        region_ws,
        min_col=1,
        min_row=5,
        max_row=4 + len(regions),
    )

    chart.add_data(
        data,
        titles_from_data=True,
    )

    chart.set_categories(categories)

    chart.x_axis.numFmt = '#,##0'

    dashboard.add_chart(
        chart,
        "G10",
    )


# ============================================================
# 13. CONDITIONAL FORMATTING
# ============================================================

for sheet_name in [
    "Regions",
    "Products",
    "Customers",
]:

    ws = wb[sheet_name]

    for col in range(
        1,
        ws.max_column + 1,
    ):

        header = str(
            ws.cell(4, col).value
        ).lower()

        if (
            "revenue" in header
            or "profit" in header
        ):

            letter = get_column_letter(col)

            ws.conditional_formatting.add(
                f"{letter}5:{letter}{ws.max_row}",
                DataBarRule(
                    start_type="min",
                    end_type="max",
                    color=green,
                ),
            )


# ============================================================
# 14. DASHBOARD FORMATTING
# ============================================================

# Twelve equal-width columns for six KPI cards
for col in range(1, 13):

    dashboard.column_dimensions[
        get_column_letter(col)
    ].width = 14

# Dashboard layout
dashboard.freeze_panes = "A4"

dashboard.sheet_properties.pageSetUpPr.fitToPage = True

dashboard.page_setup.fitToWidth = 1
dashboard.page_setup.fitToHeight = 1

dashboard.page_setup.orientation = "landscape"

dashboard.page_margins.left = 0.25
dashboard.page_margins.right = 0.25
dashboard.page_margins.top = 0.5
dashboard.page_margins.bottom = 0.5

dashboard.sheet_view.zoomScale = 85

# Print area
dashboard.print_area = "A1:L27"


# ============================================================
# 15. EXCEL CALCULATION SETTINGS
# ============================================================

wb.calculation.fullCalcOnLoad = True
wb.calculation.forceFullCalc = True
wb.calculation.calcMode = "auto"


# ============================================================
# 16. SAVE WORKBOOK
# ============================================================

wb.save(OUTPUT_FILE)

print("Workbook saved.")
print(f"File: {OUTPUT_FILE}")


# ============================================================
# 17. REOPEN AND VERIFY WORKBOOK
# ============================================================

check = load_workbook(
    OUTPUT_FILE,
    read_only=False,
    data_only=False,
)

expected_sheets = [
    "Dashboard",
    "Monthly Trends",
    "Regions",
    "Channels",
    "Products",
    "Customers",
    "Sales Data",
]

if check.sheetnames != expected_sheets:

    raise RuntimeError(
        f"Unexpected workbook sheets: {check.sheetnames}"
    )

if check["Sales Data"].max_row != len(sales) + 4:

    raise RuntimeError(
        "Sales Data row count verification failed."
    )

if len(check["Dashboard"]._charts) != 2:

    raise RuntimeError(
        "Dashboard chart verification failed."
    )

if len(check["Dashboard"].merged_cells.ranges) < 12:

    raise RuntimeError(
        "Dashboard KPI layout verification failed."
    )

check.close()


# ============================================================
# 18. FINAL OUTPUT
# ============================================================

print()
print("=" * 55)
print("RETAIL SALES DASHBOARD GENERATED SUCCESSFULLY")
print("=" * 55)

print(f"Worksheets: {len(expected_sheets)}")
print("Dashboard charts: 2")
print("KPI cards: 6")
print(f"Sales data rows: {len(sales):,}")
print(f"Total revenue: {total_revenue:,.2f}")
print(f"Estimated gross profit: {total_profit:,.2f}")
print(f"Completed orders: {total_orders:,}")
print(f"Average order value: {average_order_value:,.2f}")
print(f"Customers: {total_customers:,}")
print(f"Gross margin: {gross_margin:.1%}")

print("=" * 55)
print("Workbook reopened and structural checks passed.")
