-- Object: v_customer_discounts
-- Author: dev-team
-- Description: Calculates discount rate by loyalty tier (v1 baseline: GOLD=10%)

CREATE OR REPLACE VIEW v_customer_discounts AS
SELECT
    customer_id,
    account_code,
    full_name,
    loyalty_tier,
    annual_spend,
    CASE
        WHEN loyalty_tier = 'PLATINUM' THEN 0.15
        WHEN loyalty_tier = 'GOLD' THEN 0.10
        ELSE 0.03
    END AS discount_rate
FROM customers;
