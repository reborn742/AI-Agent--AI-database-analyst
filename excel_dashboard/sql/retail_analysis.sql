-- RETAIL SALES ANALYTICS
-- Database: retail_analytics
-- MySQL 8.4
-- All sales metrics below use completed orders only.

USE retail_analytics;

-- 1. Monthly revenue and estimated gross profit
SELECT
    DATE_FORMAT(o.order_date, '%Y-%m') AS sales_month,
    SUM(oi.quantity * oi.unit_price) AS revenue,
    SUM(oi.quantity * (oi.unit_price - p.unit_cost)) AS estimated_gross_profit,
    COUNT(DISTINCT o.order_id) AS completed_orders,
    SUM(oi.quantity) AS units_sold
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p ON p.product_id = oi.product_id
WHERE o.status = 'completed'
GROUP BY DATE_FORMAT(o.order_date, '%Y-%m')
ORDER BY sales_month;


-- 2. Regional and customer-segment performance with subtotals
SELECT
    c.region,
    c.segment,
    SUM(oi.quantity * oi.unit_price) AS revenue,
    SUM(oi.quantity * (oi.unit_price - p.unit_cost)) AS estimated_gross_profit,
    COUNT(DISTINCT o.order_id) AS completed_orders
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p ON p.product_id = oi.product_id
JOIN customers c ON c.customer_id = o.customer_id
WHERE o.status = 'completed'
GROUP BY c.region, c.segment WITH ROLLUP;


-- 3. Sales channel performance
SELECT
    o.sales_channel,
    SUM(oi.quantity * oi.unit_price) AS revenue,
    COUNT(DISTINCT o.order_id) AS completed_orders,
    SUM(oi.quantity) AS units_sold,
    AVG(oi.quantity * oi.unit_price) AS average_line_revenue
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed'
GROUP BY o.sales_channel
ORDER BY revenue DESC;


-- 4. Product revenue ranking using RANK()
WITH product_performance AS (
    SELECT
        p.product_id,
        p.product_name,
        p.category,
        SUM(oi.quantity) AS units_sold,
        SUM(oi.quantity * oi.unit_price) AS revenue,
        SUM(oi.quantity * (oi.unit_price - p.unit_cost)) AS estimated_gross_profit
    FROM orders o
    JOIN order_items oi ON oi.order_id = o.order_id
    JOIN products p ON p.product_id = oi.product_id
    WHERE o.status = 'completed'
    GROUP BY p.product_id, p.product_name, p.category
)
SELECT
    product_id,
    product_name,
    category,
    units_sold,
    revenue,
    estimated_gross_profit,
    RANK() OVER (ORDER BY revenue DESC) AS revenue_rank
FROM product_performance
ORDER BY revenue_rank;


-- 5. Top customers using ROW_NUMBER() and running revenue
WITH customer_sales AS (
    SELECT
        c.customer_id,
        c.customer_name,
        c.region,
        c.segment,
        SUM(oi.quantity * oi.unit_price) AS revenue,
        COUNT(DISTINCT o.order_id) AS completed_orders
    FROM customers c
    JOIN orders o ON o.customer_id = c.customer_id
    JOIN order_items oi ON oi.order_id = o.order_id
    WHERE o.status = 'completed'
    GROUP BY c.customer_id, c.customer_name, c.region, c.segment
),
ranked_customers AS (
    SELECT
        *,
        ROW_NUMBER() OVER (ORDER BY revenue DESC, customer_id) AS customer_rank,
        SUM(revenue) OVER (
            ORDER BY revenue DESC, customer_id
ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS cumulative_revenue
    FROM customer_sales
)
SELECT *
FROM ranked_customers
ORDER BY customer_rank;


-- 6. Order status distribution
SELECT
    status,
    COUNT(*) AS order_count,
    ROUND(
        100.0 * COUNT(*) / SUM(COUNT(*)) OVER (),
        2
    ) AS percentage_of_orders
FROM orders
GROUP BY status
ORDER BY order_count DESC;


-- 7. Category-level revenue and profitability
SELECT
    p.category,
    SUM(oi.quantity) AS units_sold,
    SUM(oi.quantity * oi.unit_price) AS revenue,
    SUM(oi.quantity * (oi.unit_price - p.unit_cost)) AS estimated_gross_profit,
    ROUND(
        100.0 * SUM(oi.quantity * (oi.unit_price - p.unit_cost))
        / NULLIF(SUM(oi.quantity * oi.unit_price), 0),
        2
    ) AS gross_margin_percentage
FROM orders o
JOIN order_items oi ON oi.order_id = o.order_id
JOIN products p ON p.product_id = oi.product_id
WHERE o.status = 'completed'
GROUP BY p.category
ORDER BY revenue DESC;
