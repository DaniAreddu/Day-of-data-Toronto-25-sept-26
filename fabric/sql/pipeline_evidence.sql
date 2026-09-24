-- Pipeline evidence: every run of the trusted-layer build, newest first.
SELECT
    pipeline_run_id,
    scenario_mode,
    status,
    started_at_utc,
    completed_at_utc,
    duration_ms,
    bronze_order_rows,
    bronze_return_rows,
    silver_sales_rows,
    quarantined_rows,
    duplicate_count,
    missing_fx_count,
    orphan_return_count,
    freshness_minutes,
    data_contract_version,
    failure_reasons,
    warning_reasons
FROM gold_pipeline_runs
ORDER BY started_at_utc DESC;
