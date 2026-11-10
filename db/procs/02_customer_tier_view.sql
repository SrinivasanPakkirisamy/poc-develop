-- Object: v_customer_discounts
-- Author: SrinivasanPakkirisamy
-- Description: EXPERIMENTAL v3.0 (GOLD=25% - DO NOT PROMOTE TO QA/PROD YET)

CREATE OR REPLACE VIEW v_customer_discounts AS
SELECT
    customer_id,
    account_code,
    full_name,
    loyalty_tier,
    annual_spend,
    CASE
        WHEN loyalty_tier = 'PLATINUM' THEN 0.30
        WHEN loyalty_tier = 'GOLD' THEN 0.25
        ELSE 0.10
    END AS discount_rate
FROM customers;
