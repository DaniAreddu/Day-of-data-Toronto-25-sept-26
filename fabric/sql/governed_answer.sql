-- Act 3: the governed answer. Same question, governed Gold tables, approved metric.
-- Net Revenue CAD is already defined and calculated in gold_fact_sales; this query only sums it.
-- Fail closed in SQL as well: no row is returned unless the data product is READY.
WITH health AS (
    SELECT status, pipeline_run_id, last_successful_refresh_utc, data_contract_version
    FROM gold_data_product_health
    WHERE data_product = 'net_revenue_cad'
      AND status = 'READY'
),
actuals AS (
    SELECT
        SUM(f.gross_revenue_cad) AS gross_revenue_cad,
        SUM(f.returns_cad) AS returns_cad,
        SUM(f.net_revenue_cad) AS net_revenue_cad,
        COUNT(*) AS governed_orders
    FROM gold_fact_sales AS f
    JOIN gold_dim_region AS r ON r.region_key = f.region_key
    JOIN gold_dim_date AS d ON d.date_key = f.date_key
    WHERE r.region_code = 'ON'
      AND d.year_month = '2026-08'
),
targets AS (
    SELECT SUM(t.target_cad) AS target_cad
    FROM gold_fact_targets AS t
    JOIN gold_dim_region AS r ON r.region_key = t.region_key
    JOIN gold_dim_date AS d ON d.date_key = t.date_key
    WHERE r.region_code = 'ON'
      AND d.year_month = '2026-08'
)
SELECT
    a.net_revenue_cad,
    a.gross_revenue_cad,
    a.returns_cad,
    t.target_cad,
    a.net_revenue_cad - t.target_cad AS variance_cad,
    CAST(100.0 * (a.net_revenue_cad - t.target_cad) / NULLIF(t.target_cad, 0) AS DECIMAL(9, 2))
        AS variance_pct,
    a.governed_orders,
    h.status,
    h.pipeline_run_id,
    h.last_successful_refresh_utc,
    h.data_contract_version
FROM health AS h
CROSS JOIN actuals AS a
CROSS JOIN targets AS t;
