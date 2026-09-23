"""Bronze, Silver and Gold definitions shared verbatim with the Fabric notebook.

Every transform is a plain SELECT written in the SQL subset that DuckDB and Spark SQL share.
The local DuckDB pipeline and ``fabric/notebooks/BuildTrustedLayer.py`` execute the *same*
statements; ``tests/test_fabric_assets.py`` fails if the two copies drift apart.

Placeholders in braces are filled with ``str.format`` from pipeline-generated values only
(run id, contract parameters), never from user input.
"""

# Source extracts land as Bronze tables exactly as received (duplicates included).
BRONZE_SOURCES = [
    {
        "table": "bronze_orders",
        "path": "azure-sql/orders.csv",
        "source_system": "azure_sql.sales.orders",
        "columns": [
            ("order_id", "STRING"),
            ("event_id", "STRING"),
            ("event_version", "INT"),
            ("order_timestamp_utc", "TIMESTAMP"),
            ("region_code", "STRING"),
            ("category_code", "STRING"),
            ("currency_code", "STRING"),
            ("gross_amount", "DECIMAL(12,2)"),
            ("customer_segment", "STRING"),
            ("source_updated_at", "TIMESTAMP"),
            ("ingested_at", "TIMESTAMP"),
        ],
    },
    {
        "table": "bronze_returns",
        "path": "sql-server/returns.{scenario_mode}.csv",
        "source_system": "sqlserver.dbo.returns",
        "columns": [
            ("return_id", "STRING"),
            ("order_id", "STRING"),
            ("return_timestamp_utc", "TIMESTAMP"),
            ("return_amount", "DECIMAL(12,2)"),
            ("currency_code", "STRING"),
            ("return_reason", "STRING"),
            ("source_updated_at", "TIMESTAMP"),
            ("ingested_at", "TIMESTAMP"),
        ],
    },
    {
        "table": "bronze_fx_rates",
        "path": "reference/fx_rates.{scenario_mode}.csv",
        "source_system": "treasury.reference.fx",
        "columns": [
            ("rate_date", "DATE"),
            ("from_currency", "STRING"),
            ("to_currency", "STRING"),
            ("rate", "DECIMAL(10,6)"),
            ("published_at_utc", "TIMESTAMP"),
            ("ingested_at", "TIMESTAMP"),
        ],
    },
    {
        "table": "bronze_targets",
        "path": "reference/targets.csv",
        "source_system": "finance.planning",
        "columns": [
            ("target_month", "STRING"),
            ("region_code", "STRING"),
            ("category_code", "STRING"),
            ("target_cad", "DECIMAL(18,2)"),
            ("approved_by_role", "STRING"),
            ("approved_at_utc", "TIMESTAMP"),
            ("source_system", "STRING"),
        ],
    },
    {
        "table": "ref_regions",
        "path": "reference/regions.csv",
        "source_system": "reference.master_data",
        "columns": [
            ("region_key", "INT"),
            ("region_code", "STRING"),
            ("region_name", "STRING"),
            ("country_code", "STRING"),
        ],
    },
    {
        "table": "ref_categories",
        "path": "reference/categories.csv",
        "source_system": "reference.master_data",
        "columns": [
            ("category_key", "INT"),
            ("category_code", "STRING"),
            ("category_name", "STRING"),
        ],
    },
    {
        "table": "ref_calendar",
        "path": "reference/calendar.csv",
        "source_system": "reference.master_data",
        "columns": [
            ("date_key", "INT"),
            ("calendar_date", "DATE"),
            ("calendar_year", "INT"),
            ("month_number", "INT"),
            ("day_of_month", "INT"),
            ("year_month", "STRING"),
            ("month_name", "STRING"),
            ("day_name", "STRING"),
        ],
    },
]

# Silver: technical correctness. Order matters; each statement may read earlier tables.
SILVER_TRANSFORMS = [
    (
        "silver_order_versions",
        """
SELECT
    order_id,
    event_id,
    event_version,
    order_timestamp_utc,
    UPPER(TRIM(region_code)) AS region_code,
    UPPER(TRIM(category_code)) AS category_code,
    UPPER(TRIM(currency_code)) AS currency_code,
    gross_amount,
    customer_segment,
    source_updated_at,
    ingested_at,
    source_system,
    ROW_NUMBER() OVER (
        PARTITION BY order_id
        ORDER BY event_version DESC, source_updated_at DESC, ingested_at DESC, event_id DESC
    ) AS version_rank,
    CASE
        WHEN COALESCE(customer_segment, '') = 'Internal Test' THEN 'TEST_TRANSACTION'
        WHEN gross_amount IS NULL OR gross_amount <= 0 THEN 'INVALID_AMOUNT'
    END AS quarantine_reason
FROM bronze_orders
""",
    ),
    (
        "silver_orders",
        """
SELECT
    order_id,
    event_id,
    event_version,
    order_timestamp_utc,
    CAST(order_timestamp_utc AS DATE) AS order_date,
    region_code,
    category_code,
    currency_code,
    gross_amount,
    customer_segment,
    source_updated_at,
    ingested_at,
    source_system
FROM silver_order_versions
WHERE version_rank = 1
  AND quarantine_reason IS NULL
""",
    ),
    (
        "silver_returns",
        """
WITH ranked AS (
    SELECT
        r.*,
        ROW_NUMBER() OVER (
            PARTITION BY r.return_id
            ORDER BY r.source_updated_at DESC, r.ingested_at DESC
        ) AS version_rank
    FROM bronze_returns r
)
SELECT
    r.return_id,
    r.order_id,
    r.return_timestamp_utc,
    r.return_amount,
    UPPER(TRIM(r.currency_code)) AS currency_code,
    r.return_reason,
    r.source_updated_at,
    r.ingested_at,
    r.source_system,
    CASE
        WHEN o.order_id IS NULL THEN 'ORPHAN'
        WHEN o.quarantine_reason IS NOT NULL THEN 'ORDER_EXCLUDED'
        WHEN r.return_amount IS NULL OR r.return_amount <= 0 THEN 'QUARANTINED'
        WHEN UPPER(TRIM(r.currency_code)) <> o.currency_code THEN 'QUARANTINED'
        ELSE 'ACCEPTED'
    END AS reconciliation_status,
    CASE
        WHEN o.order_id IS NULL THEN NULL
        WHEN r.return_amount IS NULL OR r.return_amount <= 0 THEN 'INVALID_RETURN_AMOUNT'
        WHEN UPPER(TRIM(r.currency_code)) <> o.currency_code THEN 'RETURN_CURRENCY_MISMATCH'
    END AS quarantine_reason
FROM ranked r
LEFT JOIN silver_order_versions o
    ON o.order_id = r.order_id
   AND o.version_rank = 1
WHERE r.version_rank = 1
""",
    ),
    (
        "silver_quarantine",
        """
SELECT
    'orders' AS source_entity,
    order_id AS record_key,
    quarantine_reason,
    source_system,
    ingested_at,
    '{run_id}' AS pipeline_run_id
FROM silver_order_versions
WHERE version_rank = 1
  AND quarantine_reason IS NOT NULL
UNION ALL
SELECT
    'returns' AS source_entity,
    return_id AS record_key,
    quarantine_reason,
    source_system,
    ingested_at,
    '{run_id}' AS pipeline_run_id
FROM silver_returns
WHERE reconciliation_status = 'QUARANTINED'
""",
    ),
    (
        "silver_reconciled_sales",
        """
WITH accepted_returns AS (
    SELECT
        order_id,
        SUM(return_amount) AS accepted_return_amount,
        COUNT(*) AS return_count
    FROM silver_returns
    WHERE reconciliation_status = 'ACCEPTED'
    GROUP BY order_id
),
priced AS (
    SELECT
        o.order_id,
        o.event_id,
        o.order_date,
        o.region_code,
        o.category_code,
        o.currency_code,
        o.gross_amount,
        COALESCE(ar.accepted_return_amount, CAST(0 AS DECIMAL(12,2))) AS accepted_return_amount,
        COALESCE(ar.return_count, 0) AS return_count,
        CASE
            WHEN o.currency_code = 'CAD' THEN CAST(1 AS DECIMAL(10,6))
            ELSE fx.rate
        END AS fx_rate_to_cad,
        o.source_system,
        o.source_updated_at
    FROM silver_orders o
    LEFT JOIN accepted_returns ar
        ON ar.order_id = o.order_id
    LEFT JOIN bronze_fx_rates fx
        ON fx.from_currency = o.currency_code
       AND fx.to_currency = 'CAD'
       AND fx.rate_date = o.order_date
)
SELECT
    order_id,
    event_id,
    order_date,
    region_code,
    category_code,
    currency_code,
    gross_amount,
    accepted_return_amount,
    return_count,
    fx_rate_to_cad,
    CAST(ROUND(gross_amount * fx_rate_to_cad, 2) AS DECIMAL(18,2)) AS gross_revenue_cad,
    CAST(ROUND(accepted_return_amount * fx_rate_to_cad, 2) AS DECIMAL(18,2)) AS returns_cad,
    source_system,
    source_updated_at
FROM priced
""",
    ),
]

# Gold dimensions are always rebuilt from governed reference data.
GOLD_DIMENSION_TRANSFORMS = [
    (
        "gold_dim_date",
        """
SELECT
    date_key,
    calendar_date,
    calendar_year,
    month_number,
    day_of_month,
    year_month,
    month_name,
    day_name
FROM ref_calendar
""",
    ),
    (
        "gold_dim_region",
        """
SELECT region_key, region_code, region_name, country_code
FROM ref_regions
""",
    ),
    (
        "gold_dim_category",
        """
SELECT category_key, category_code, category_name
FROM ref_categories
""",
    ),
]

# Gold facts are published only when every blocking check passes (fail closed).
GOLD_FACT_TRANSFORMS = [
    (
        "gold_fact_sales",
        """
SELECT
    s.order_id AS order_key,
    d.date_key,
    r.region_key,
    c.category_key,
    s.gross_revenue_cad,
    s.returns_cad,
    CAST(s.gross_revenue_cad - s.returns_cad AS DECIMAL(18,2)) AS net_revenue_cad,
    s.currency_code AS original_currency,
    s.gross_amount AS gross_amount_original_currency,
    s.fx_rate_to_cad AS applied_fx_rate,
    s.return_count,
    '{run_id}' AS pipeline_run_id,
    s.source_system AS order_source_system,
    s.event_id AS order_source_event_id,
    s.source_updated_at AS order_source_updated_at,
    CASE WHEN s.return_count > 0 THEN 'sqlserver.dbo.returns' END AS returns_source_system,
    CASE WHEN s.currency_code = 'CAD' THEN 'none (CAD)' ELSE 'treasury.reference.fx' END
        AS fx_source_system
FROM silver_reconciled_sales s
JOIN gold_dim_date d ON d.calendar_date = s.order_date
JOIN gold_dim_region r ON r.region_code = s.region_code
JOIN gold_dim_category c ON c.category_code = s.category_code
""",
    ),
    (
        "gold_fact_targets",
        """
SELECT
    d.date_key,
    r.region_key,
    c.category_key,
    t.target_month,
    t.target_cad,
    t.approved_by_role,
    t.approved_at_utc,
    t.source_system,
    '{run_id}' AS pipeline_run_id
FROM bronze_targets t
JOIN gold_dim_date d ON d.year_month = t.target_month AND d.day_of_month = 1
JOIN gold_dim_region r ON r.region_code = t.region_code
JOIN gold_dim_category c ON c.category_code = t.category_code
""",
    ),
]

# Observability tables are written from Python records with these explicit schemas.
OBSERVABILITY_SCHEMAS = {
    "silver_quality_results": [
        ("pipeline_run_id", "STRING"),
        ("check_name", "STRING"),
        ("severity", "STRING"),
        ("observed_value", "BIGINT"),
        ("threshold", "STRING"),
        ("status", "STRING"),
        ("detail", "STRING"),
        ("evaluated_at_utc", "TIMESTAMP"),
    ],
    "gold_data_product_health": [
        ("data_product", "STRING"),
        ("status", "STRING"),
        ("data_contract_version", "STRING"),
        ("scenario_mode", "STRING"),
        ("as_of_utc", "TIMESTAMP"),
        ("orders_freshness_minutes", "BIGINT"),
        ("returns_freshness_minutes", "BIGINT"),
        ("freshness_sla_minutes", "BIGINT"),
        ("duplicate_count", "BIGINT"),
        ("missing_fx_count", "BIGINT"),
        ("orphan_return_count", "BIGINT"),
        ("missing_key_count", "BIGINT"),
        ("unsupported_currency_count", "BIGINT"),
        ("quarantined_rows", "BIGINT"),
        ("blocking_reasons", "STRING"),
        ("warning_reasons", "STRING"),
        ("pipeline_run_id", "STRING"),
        ("last_successful_refresh_utc", "TIMESTAMP"),
        ("evaluated_at_utc", "TIMESTAMP"),
    ],
    "gold_pipeline_runs": [
        ("pipeline_run_id", "STRING"),
        ("scenario_mode", "STRING"),
        ("started_at_utc", "TIMESTAMP"),
        ("completed_at_utc", "TIMESTAMP"),
        ("status", "STRING"),
        ("bronze_order_rows", "BIGINT"),
        ("bronze_return_rows", "BIGINT"),
        ("silver_sales_rows", "BIGINT"),
        ("quarantined_rows", "BIGINT"),
        ("duplicate_count", "BIGINT"),
        ("missing_fx_count", "BIGINT"),
        ("orphan_return_count", "BIGINT"),
        ("freshness_minutes", "BIGINT"),
        ("data_contract_version", "STRING"),
        ("failure_reasons", "STRING"),
        ("warning_reasons", "STRING"),
        ("duration_ms", "BIGINT"),
    ],
}
