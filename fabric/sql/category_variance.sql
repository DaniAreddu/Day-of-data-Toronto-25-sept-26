-- Which category drove the result? Governed Net Revenue CAD versus target, by category.
-- Most negative variance first. Returns no rows unless the data product is READY.
WITH health AS (
    SELECT status
    FROM gold_data_product_health
    WHERE data_product = 'net_revenue_cad'
      AND status = 'READY'
),
actuals AS (
    SELECT f.category_key, SUM(f.net_revenue_cad) AS net_revenue_cad
    FROM gold_fact_sales AS f
    JOIN gold_dim_region AS r ON r.region_key = f.region_key
    JOIN gold_dim_date AS d ON d.date_key = f.date_key
    WHERE r.region_code = 'ON'
      AND d.year_month = '2026-08'
    GROUP BY f.category_key
),
targets AS (
    SELECT t.category_key, SUM(t.target_cad) AS target_cad
    FROM gold_fact_targets AS t
    JOIN gold_dim_region AS r ON r.region_key = t.region_key
    JOIN gold_dim_date AS d ON d.date_key = t.date_key
    WHERE r.region_code = 'ON'
      AND d.year_month = '2026-08'
    GROUP BY t.category_key
)
SELECT
    c.category_code,
    c.category_name,
    COALESCE(a.net_revenue_cad, 0) AS net_revenue_cad,
    t.target_cad,
    COALESCE(a.net_revenue_cad, 0) - t.target_cad AS variance_cad
FROM targets AS t
CROSS JOIN health AS h
JOIN gold_dim_category AS c ON c.category_key = t.category_key
LEFT JOIN actuals AS a ON a.category_key = t.category_key
ORDER BY variance_cad, c.category_code;
