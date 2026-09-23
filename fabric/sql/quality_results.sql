-- Data-quality evidence for the run that produced the current health status.
SELECT
    q.check_name,
    q.severity,
    q.status,
    q.observed_value,
    q.threshold,
    q.detail
FROM silver_quality_results AS q
JOIN gold_data_product_health AS h
    ON h.pipeline_run_id = q.pipeline_run_id
WHERE h.data_product = 'net_revenue_cad'
ORDER BY
    CASE q.severity WHEN 'BLOCKING' THEN 0 ELSE 1 END,
    CASE q.status WHEN 'PASS' THEN 1 ELSE 0 END,
    q.check_name;
