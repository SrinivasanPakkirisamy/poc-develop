-- Object: v_customer_discounts
-- Author: SrinivasanPakkirisamy
-- Description: Calculates discount rate by loyalty tier (v2.0 release: GOLD=12%, PLATINUM=18%)

CREATE OR REPLACE VIEW v_customer_discounts AS
SELECT
    customer_id,
    account_code,
    full_name,
    loyalty_tier,
    annual_spend,
    CASE
        WHEN loyalty_tier = 'PLATINUM' THEN 0.18
        WHEN loyalty_tier = 'GOLD' THEN 0.12
        ELSE 0.05
    END AS discount_rate
FROM customers;
