import pytest

from ai_database_analyst.schema import SchemaInfo


@pytest.fixture
def schema() -> SchemaInfo:
    return SchemaInfo.from_columns(
        {
            "completed_sales": [
                ("product_name", "varchar"),
                ("quantity", "int"),
                ("line_revenue", "decimal"),
                ("estimated_gross_profit", "decimal"),
                ("region", "varchar"),
                ("sales_channel", "varchar"),
                ("order_date", "date"),
            ],
            "orders": [("order_id", "int"), ("customer_id", "int"), ("sales_channel", "varchar")],
            "customers": [("customer_id", "int"), ("customer_name", "varchar")],
        }
    )
