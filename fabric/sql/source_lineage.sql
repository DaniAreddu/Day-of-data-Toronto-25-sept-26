-- Lineage evidence for the governed answer: which source systems contributed Gold rows.
SELECT
    f.order_source_system,
    COALESCE(f.returns_source_system, 'no return') AS returns_source_system,
    f.fx_source_system,
    COUNT(*) AS fact_rows,
    MIN(f.pipeline_run_id) AS pipeline_run_id
FROM gold_fact_sales AS f
JOIN gold_dim_region AS r ON r.region_key = f.region_key
JOIN gold_dim_date AS d ON d.date_key = f.date_key
WHERE r.region_code = 'ON'
  AND d.year_month = '2026-08'
GROUP BY f.order_source_system, COALESCE(f.returns_source_system, 'no return'), f.fx_source_system
ORDER BY fact_rows DESC;
