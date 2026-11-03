
# Retail Sales Analytics – Excel Dashboard

An Excel-based retail sales analytics project built with Python, pandas, and openpyxl. It transforms a relational retail dataset into an interactive, multi-sheet Excel workbook with business KPIs, trend analysis, and product, customer, regional, and sales-channel performance.

## Features

- Automated extraction of retail data from MySQL seed SQL.
- Data quality and referential-integrity validation.
- Revenue and estimated gross-profit calculations.
- Excel dashboard with KPI summaries.
- Monthly revenue and profit trend chart.
- Regional revenue comparison chart.
- Formatted Excel tables, filters, and conditional formatting.
- Seven analytical MySQL queries using CTEs, window functions, ranking, and ROLLUP.

## Workbook Structure

| Worksheet | Description |
|---|---|
| Dashboard | Main KPIs and charts |
| Monthly Trends | Monthly revenue and estimated gross profit |
| Regions | Regional and customer-segment performance |
| Channels | Sales-channel performance |
| Products | Product-level performance |
| Customers | Customer-level performance |
| Sales Data | Detailed completed sales records |

## Key Metrics

| Metric | Value |
|---|---:|
| Total Revenue | 197,921.70 |
| Estimated Gross Profit | 109,685.10 |
| Completed Orders | 1,188 |
| Completed Sales Lines | 2,131 |

**Metric definitions**

- Revenue = Quantity × Unit Selling Price.
- Estimated Gross Profit = Quantity × (Unit Selling Price − Unit Cost).
- Gross Margin = Estimated Gross Profit ÷ Revenue × 100.
- Average Order Value = Revenue ÷ Completed Orders.

Gross profit is an estimate based on the available product unit costs. It is not net profit.

## Technology Stack

- Python
- pandas
- openpyxl
- MySQL 8.4
- SQLGlot
- Excel

## Project Structure

```text
excel_dashboard/
├── data/
│   ├── customers.csv
│   ├── products.csv
│   ├── orders.csv
│   ├── order_items.csv
│   └── completed_sales.csv
├── output/
│   └── retail_sales_dashboard.xlsx
├── sql/
│   └── retail_analysis.sql
├── extract_seed_data.py
├── build_dashboard.py
├── quality_check.py
└── README.md


## Excel Dashboard Preview

![Retail Sales Dashboard](images/dashboard-preview.PNG)

## Additional Project: Retail Sales Excel Dashboard

An Excel-based retail sales analytics dashboard built using Python, pandas, and openpyxl. It transforms synthetic retail transaction data into interactive KPI summaries, financial analysis, and business performance reports.

### Dashboard Preview

![Retail Sales Dashboard](excel_dashboard/images/dashboard-preview.PNG)

**Dashboard highlights:**
- 6 KPI cards: Revenue, Estimated Gross Profit, Completed Orders, Average Order Value, Customers, and Gross Margin.
- Monthly revenue and profit trends.
- Regional revenue comparison.
- Product, customer, channel, and sales analysis.
- 7 worksheets with Excel tables, filters, and charts.

**Verified dataset:** 2,131 completed sales records, 1,188 completed orders, and 80 customers.

[📥 Download the Excel Dashboard](excel_dashboard/output/retail_sales_dashboard_v2.xlsx) | [View Project Source](excel_dashboard/)