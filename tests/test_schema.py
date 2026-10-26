from ai_database_analyst.schema import SENSITIVE_COLUMN_PATTERNS, SchemaInfo

COLUMNS = {
    "customers": [("customer_id", "int"), ("customer_name", "varchar"), ("email", "varchar")],
    "orders": [("order_id", "int"), ("customer_id", "int"), ("status", "varchar")],
}


def test_plain_format_is_unchanged():
    schema = SchemaInfo.from_columns({"orders": [("id", "int"), ("total", "decimal")]})
    assert schema.prompt_text == "orders: id (int), total (decimal)"
    assert schema.tables == {"orders": frozenset({"id", "total"})}
    assert schema.restricted_tables == frozenset()


def test_keys_comments_and_descriptions_reach_the_prompt():
    schema = SchemaInfo.from_columns(
        COLUMNS,
        primary_keys={"orders": ["order_id"]},
        foreign_keys={("orders", "customer_id"): ("customers", "customer_id")},
        table_comments={"orders": "One row per order"},
        column_comments={("orders", "status"): 'completed or "cancelled"'},
    )
    line = [ln for ln in schema.prompt_text.splitlines() if ln.startswith("orders")][0]
    assert line.startswith("orders [One row per order]:")
    assert "order_id (int, PK)" in line
    assert "customer_id (int, FK->customers.customer_id)" in line
    assert "status (varchar) \"completed or 'cancelled'\"" in line


def test_hidden_table_disappears_entirely():
    schema = SchemaInfo.from_columns(COLUMNS, hidden_tables=["cust*"])
    assert "customers" not in schema.tables
    assert "customers" not in schema.prompt_text
    assert "orders" in schema.tables


def test_hidden_column_is_removed_but_remembered():
    schema = SchemaInfo.from_columns(COLUMNS, hidden_columns=["customers.email"])
    assert "email" not in schema.tables["customers"]
    assert "email" not in schema.prompt_text
    assert schema.hidden == {"customers": frozenset({"email"})}
    assert schema.restricted_tables == frozenset({"customers"})
    assert schema.hidden_names_for(["customers", "orders"]) == frozenset({"email"})


def test_wildcard_column_patterns():
    schema = SchemaInfo.from_columns(
        {"a": [("id", "int"), ("email", "varchar")], "b": [("id", "int"), ("email", "varchar")]},
        hidden_columns=["*.email"],
    )
    assert schema.tables["a"] == schema.tables["b"] == frozenset({"id"})


def test_table_with_every_column_hidden_is_dropped():
    schema = SchemaInfo.from_columns({"secrets": [("k", "varchar")], "t": [("id", "int")]}, hidden_columns=["secrets.*"])
    assert "secrets" not in schema.tables


def test_foreign_key_to_hidden_column_is_not_advertised():
    schema = SchemaInfo.from_columns(
        COLUMNS,
        foreign_keys={("orders", "customer_id"): ("customers", "customer_id")},
        hidden_columns=["customers.customer_id"],
    )
    assert "FK->" not in schema.prompt_text


def test_sensitive_defaults_hide_secrets_but_not_lookalikes():
    schema = SchemaInfo.from_columns(
        {
            "users": [("id", "int"), ("password_hash", "varchar"), ("api_key", "varchar"), ("ssn", "varchar")],
            "people": [("id", "int"), ("ssn_last4", "varchar"), ("credit_card_number", "varchar")],
            "classes": [("id", "int"), ("classname", "varchar"), ("passenger_count", "int")],
        },
        hidden_columns=SENSITIVE_COLUMN_PATTERNS,
    )
    assert schema.tables["users"] == frozenset({"id"})
    assert schema.tables["people"] == frozenset({"id"})
    assert schema.tables["classes"] == frozenset({"id", "classname", "passenger_count"})
