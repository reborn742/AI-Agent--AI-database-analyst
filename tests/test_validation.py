import pytest

from ai_database_analyst.config import settings
from ai_database_analyst.errors import QueryValidationError
from ai_database_analyst.validation import validate_sql

ACCEPTED = [
    "SELECT product_name, SUM(quantity) AS units_sold FROM completed_sales GROUP BY product_name ORDER BY units_sold DESC LIMIT 5",
    "SELECT o.order_id, c.customer_name FROM orders o JOIN customers c ON o.customer_id = c.customer_id",
    "WITH t AS (SELECT region, SUM(line_revenue) r FROM completed_sales GROUP BY region) SELECT * FROM t",
    "SELECT region FROM completed_sales UNION SELECT sales_channel FROM orders",
    "SELECT DATE_FORMAT(order_date, '%Y-%m') m, SUM(line_revenue) FROM completed_sales GROUP BY m",
    "SELECT retail_analytics.orders.order_id FROM retail_analytics.orders",
]

REJECTED = {
    "drop": "DROP TABLE orders",
    "delete": "DELETE FROM orders",
    "update": "UPDATE orders SET sales_channel = 'x'",
    "insert": "INSERT INTO orders VALUES (1, 2, 'x')",
    "stacked statements": "SELECT 1; DROP TABLE orders",
    "sleep": "SELECT SLEEP(5)",
    "benchmark": "SELECT BENCHMARK(1000000, MD5('a'))",
    "load_file": "SELECT LOAD_FILE('/etc/passwd')",
    "get_lock": "SELECT GET_LOCK('a', 1)",
    "into outfile": "SELECT * FROM completed_sales INTO OUTFILE '/tmp/x'",
    "for update": "SELECT * FROM orders FOR UPDATE",
    "share mode": "SELECT * FROM orders LOCK IN SHARE MODE",
    "user variable": "SELECT @a := 1",
    "system variable": "SELECT @@version",
    "version()": "SELECT VERSION()",
    "user()": "SELECT USER()",
    "other database": "SELECT * FROM mysql.user",
    "unknown table": "SELECT * FROM nope",
    "unknown column": "SELECT c.nope FROM customers c",
    "recursive cte": "WITH RECURSIVE t AS (SELECT 1 n UNION ALL SELECT n + 1 FROM t WHERE n < 10) SELECT * FROM t",
    "unlisted function": "SELECT FOO(region) FROM completed_sales",
    "table function": "SELECT * FROM JSON_TABLE('[1]', '$[*]' COLUMNS(a INT PATH '$')) j",
    "optimizer hint": "SELECT /*+ MAX_EXECUTION_TIME(1) */ region FROM completed_sales",
    "string limit": "SELECT region FROM completed_sales LIMIT '5'",
    "zero limit": "SELECT region FROM completed_sales LIMIT 0",
    "garbage": "SELEC garbage",
    "empty": "",
}


@pytest.mark.parametrize("sql", ACCEPTED)
def test_accepts_safe_selects(sql, schema):
    validated = validate_sql(sql, schema)
    assert validated.sql.upper().startswith(("SELECT", "WITH"))


@pytest.mark.parametrize("sql", REJECTED.values(), ids=REJECTED.keys())
def test_rejects_unsafe_sql(sql, schema):
    with pytest.raises(QueryValidationError):
        validate_sql(sql, schema)


def test_adds_row_cap_when_no_limit(schema):
    validated = validate_sql("SELECT * FROM completed_sales", schema)
    assert validated.cap_applied is True
    assert validated.original_limit is None
    assert f"LIMIT {settings.max_rows}" in validated.sql


def test_lowers_oversized_limit(schema):
    validated = validate_sql("SELECT * FROM completed_sales LIMIT 100000", schema)
    assert validated.cap_applied is True
    assert validated.original_limit == 100000
    assert f"LIMIT {settings.max_rows}" in validated.sql


def test_keeps_small_limit(schema):
    validated = validate_sql("SELECT * FROM completed_sales LIMIT 3", schema)
    assert validated.cap_applied is False
    assert validated.original_limit == 3


def test_strips_code_fence_and_comments(schema):
    validated = validate_sql("```sql\nSELECT region /* hi */ FROM completed_sales;\n```", schema)
    assert "```" not in validated.sql
    assert "hi" not in validated.sql


def test_rejects_too_many_tables(schema):
    joins = ", ".join(f"completed_sales t{i}" for i in range(settings.max_table_references + 1))
    with pytest.raises(QueryValidationError, match="too many tables"):
        validate_sql(f"SELECT 1 FROM {joins}", schema)


def test_rejects_oversized_sql(schema):
    with pytest.raises(QueryValidationError, match="too long"):
        validate_sql("SELECT " + ",".join(["region"] * 3000) + " FROM completed_sales", schema)


# --- restricted (hidden) columns -----------------------------------------------------------------


@pytest.fixture
def hr_schema():
    from ai_database_analyst.schema import SchemaInfo

    return SchemaInfo.from_columns(
        {
            "employees": [
                ("employee_id", "int"),
                ("department", "varchar"),
                ("salary", "decimal"),
                ("email", "varchar"),
            ],
            "departments": [("name", "varchar"), ("budget", "decimal")],
        },
        hidden_columns=["employees.salary", "employees.email"],
    )


HIDDEN_ACCEPTED = [
    "SELECT department, COUNT(*) AS headcount FROM employees GROUP BY department",
    "SELECT COUNT(*) FROM employees",
    "SELECT e.employee_id, e.department FROM employees e",
    "SELECT * FROM departments",
]

HIDDEN_REJECTED = {
    "star": "SELECT * FROM employees",
    "qualified star": "SELECT e.* FROM employees e",
    "bare hidden column": "SELECT salary FROM employees",
    "qualified hidden column": "SELECT e.salary FROM employees e",
    "aliased hidden column": "SELECT salary AS pay FROM employees",
    "aggregate of hidden column": "SELECT AVG(salary) FROM employees",
    "hidden column in WHERE": "SELECT employee_id FROM employees WHERE salary > 100000",
    "through a subquery": "SELECT t.x FROM (SELECT salary AS x FROM employees) t",
    "star through a CTE": "WITH t AS (SELECT * FROM employees) SELECT department FROM t",
    "through a join": "SELECT d.name FROM departments d JOIN employees e ON e.department = d.name WHERE e.salary > 1",
}


@pytest.mark.parametrize("sql", HIDDEN_ACCEPTED)
def test_queries_not_touching_hidden_columns_still_work(sql, hr_schema):
    assert validate_sql(sql, hr_schema).sql


@pytest.mark.parametrize("sql", HIDDEN_REJECTED.values(), ids=HIDDEN_REJECTED.keys())
def test_every_route_to_a_hidden_column_is_closed(sql, hr_schema):
    with pytest.raises(QueryValidationError):
        validate_sql(sql, hr_schema)


def test_fixable_mistakes_are_flagged_repairable_and_attacks_are_not(schema):
    with pytest.raises(QueryValidationError) as unknown:
        validate_sql("SELECT * FROM nope", schema)
    assert unknown.value.repairable
    with pytest.raises(QueryValidationError) as garbage:
        validate_sql("SELECT * FROM WHERE (", schema)
    assert garbage.value.repairable
    for attack in ("DROP TABLE orders", "SELECT LOAD_FILE('/etc/passwd')", "SELECT 1; DROP TABLE orders", "SELECT SLEEP(5)"):
        with pytest.raises(QueryValidationError) as info:
            validate_sql(attack, schema)
        assert not info.value.repairable, attack
