-- Object: customers_table
-- Author: dev-team
-- Description: Core customer account table with loyalty tier tracking

CREATE TABLE IF NOT EXISTS customers (
    customer_id SERIAL PRIMARY KEY,
    account_code VARCHAR(32) UNIQUE NOT NULL,
    full_name VARCHAR(120) NOT NULL,
    loyalty_tier VARCHAR(20) NOT NULL DEFAULT 'STANDARD',
    annual_spend NUMERIC(12, 2) NOT NULL DEFAULT 0.00,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO customers (account_code, full_name, loyalty_tier, annual_spend)
VALUES
    ('CUST-1001', 'Acme Global Corp', 'GOLD', 48500.00),
    ('CUST-1002', 'Northwind Logistics', 'STANDARD', 9200.00)
ON CONFLICT (account_code) DO UPDATE
SET
    loyalty_tier = EXCLUDED.loyalty_tier,
    annual_spend = EXCLUDED.annual_spend,
    updated_at = CURRENT_TIMESTAMP;
