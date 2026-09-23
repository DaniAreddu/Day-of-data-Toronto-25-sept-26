-- Act 2: is the data product healthy enough to answer from?
-- The governed path reads this row first and refuses unless status = 'READY'.
SELECT
    data_product,
    status,
    data_contract_version,
    scenario_mode,
    as_of_utc,
    orders_freshness_minutes,
    returns_freshness_minutes,
    freshness_sla_minutes,
    duplicate_count,
    missing_fx_count,
    orphan_return_count,
    missing_key_count,
    unsupported_currency_count,
    quarantined_rows,
    blocking_reasons,
    warning_reasons,
    pipeline_run_id,
    last_successful_refresh_utc,
    evaluated_at_utc
FROM gold_data_product_health
WHERE data_product = 'net_revenue_cad';
