-- Demo retail schema. Runs once, when the MySQL data volume is first created.
SET NAMES utf8mb4;

CREATE TABLE customers (
    customer_id   INT          NOT NULL PRIMARY KEY,
    customer_name VARCHAR(120) NOT NULL,
    region        VARCHAR(40)  NOT NULL,
    segment       VARCHAR(40)  NOT NULL
) ENGINE=InnoDB;

CREATE TABLE products (
    product_id   INT           NOT NULL PRIMARY KEY,
    product_name VARCHAR(120)  NOT NULL,
    category     VARCHAR(60)   NOT NULL,
    unit_price   DECIMAL(10,2) NOT NULL,
    unit_cost    DECIMAL(10,2) NOT NULL
) ENGINE=InnoDB;

CREATE TABLE orders (
    order_id      INT         NOT NULL PRIMARY KEY,
    customer_id   INT         NOT NULL,
    order_date    DATE        NOT NULL,
    sales_channel VARCHAR(40) NOT NULL,
    status        VARCHAR(20) NOT NULL,
    KEY idx_orders_date (order_date),
    CONSTRAINT fk_orders_customer FOREIGN KEY (customer_id) REFERENCES customers (customer_id)
) ENGINE=InnoDB;

CREATE TABLE order_items (
    order_item_id INT           NOT NULL PRIMARY KEY,
    order_id      INT           NOT NULL,
    product_id    INT           NOT NULL,
    quantity      INT           NOT NULL,
    unit_price    DECIMAL(10,2) NOT NULL,
    KEY idx_items_order (order_id),
    CONSTRAINT fk_items_order   FOREIGN KEY (order_id)   REFERENCES orders (order_id),
    CONSTRAINT fk_items_product FOREIGN KEY (product_id) REFERENCES products (product_id)
) ENGINE=InnoDB;

-- The analyst prefers this view for sales questions (see prompts.py): one row per
-- completed order line, with revenue and an estimated gross profit.
CREATE VIEW completed_sales AS
SELECT
    oi.order_item_id,
    o.order_id,
    o.order_date,
    o.sales_channel,
    c.customer_id,
    c.customer_name,
    c.region,
    c.segment,
    p.product_id,
    p.product_name,
    p.category,
    oi.quantity,
    oi.unit_price,
    oi.quantity * oi.unit_price                    AS line_revenue,
    oi.quantity * (oi.unit_price - p.unit_cost)    AS estimated_gross_profit
FROM order_items oi
JOIN orders    o ON o.order_id    = oi.order_id
JOIN customers c ON c.customer_id = o.customer_id
JOIN products p  ON p.product_id  = oi.product_id
WHERE o.status = 'completed';
