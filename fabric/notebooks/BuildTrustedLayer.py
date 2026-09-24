# Fabric notebook source: BuildTrustedLayer
#
# Percent-format notebook source kept for code review. The importable notebook
# (BuildTrustedLayer.ipynb) is generated from this file by scripts/build_fabric_notebook.py.
# Synthetic, production-inspired architecture scenario. It does not represent a real customer
# deployment.

# %% [markdown]
# # BuildTrustedLayer
#
# **AI Reliability Lab** (Day of Data Toronto 2026, Saturday 26 September 2026).
#
# Builds the governed `net_revenue_cad` data product in a Fabric Lakehouse:
# Bronze (as received) → Silver (deduplication, FX, returns reconciliation, quarantine)
# → quality gates → Gold star schema (published only when every blocking check passes)
# → health and pipeline-run records.
#
# *A synthetic, production-inspired architecture scenario. It does not represent a real
# customer deployment.* The CSV files are synthetic extracts representing an Azure SQL orders
# system and an on-premises SQL Server returns system.
#
# **Before running:** attach the `AIPlatform` Lakehouse as the default Lakehouse and upload the
# `data` folder so that `Files/data/azure-sql/orders.csv` exists. No Copilot, Data Agent,
# AI Functions or external API is used.
#
# **Modes:** `broken` resets the demo (clears run history) and is expected to end BLOCKED with
# an error so the pipeline run shows as failed. `repaired` ingests the repaired extracts and
# ends READY. Both are safe to rerun.

# %% tags=["parameters"]
scenario_mode = "broken"  # "broken" or "repaired"
demo_clock_utc = "2026-09-26T18:00:00Z"  # fixed scenario as-of time used for freshness SLAs
data_root = "Files/data"
fail_on_blocked = True  # raise at the end when the data product is not READY

# %%
import time
import uuid
from datetime import UTC, datetime

from pyspark.sql import functions as F

if scenario_mode not in ("broken", "repaired"):
    raise ValueError(f"scenario_mode must be 'broken' or 'repaired', not {scenario_mode!r}")

spark.conf.set("spark.sql.session.timeZone", "UTC")
AS_OF = datetime.fromisoformat(demo_clock_utc.replace("Z", "+00:00"))
DATA_PRODUCT = "net_revenue_cad"
print(f"Mode: {scenario_mode} | scenario as-of (fixed demo clock): {AS_OF.isoformat()}")

# %% [markdown]
# ## Shared definitions
#
# The next two cells are copied verbatim from `src/ai_reliability_lab/medallion.py` and
# `src/ai_reliability_lab/quality.py` in the GitHub repository. The local DuckDB demo runs the
# same statements, and a repository test fails if the copies drift apart.

# %%
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

# %%
# Freshness is measured from the newest ingestion timestamp of each feed.
LATEST_INGESTION_SQL = {
    "ORDERS_FRESHNESS": "SELECT CAST(MAX(ingested_at) AS STRING) AS observed FROM bronze_orders",
    "RETURNS_FRESHNESS": "SELECT CAST(MAX(ingested_at) AS STRING) AS observed FROM bronze_returns",
}

QUALITY_CHECK_SQL = {
    "DUPLICATE_BUSINESS_KEYS": """
SELECT
    (SELECT COUNT(*) FROM (
        SELECT order_id FROM silver_reconciled_sales GROUP BY order_id HAVING COUNT(*) > 1
    ) d)
    +
    (SELECT COUNT(*) FROM (
        SELECT return_id FROM silver_returns GROUP BY return_id HAVING COUNT(*) > 1
    ) d) AS observed
""",
    "MISSING_FX": """
SELECT COUNT(*) AS observed
FROM silver_reconciled_sales
WHERE fx_rate_to_cad IS NULL
  AND currency_code IN ({accepted_currencies})
""",
    "ORPHAN_RETURNS": """
SELECT COUNT(*) AS observed
FROM silver_returns
WHERE reconciliation_status = 'ORPHAN'
""",
    "MISSING_REQUIRED_KEYS": """
SELECT COUNT(*) AS observed
FROM silver_order_versions v
LEFT JOIN ref_regions r ON r.region_code = v.region_code
LEFT JOIN ref_categories c ON c.category_code = v.category_code
WHERE v.version_rank = 1
  AND (v.order_id IS NULL OR r.region_code IS NULL OR c.category_code IS NULL)
""",
    "UNSUPPORTED_CURRENCY": """
SELECT
    (SELECT COUNT(*) FROM silver_order_versions
     WHERE version_rank = 1
       AND (currency_code IS NULL OR currency_code NOT IN ({accepted_currencies})))
    +
    (SELECT COUNT(*) FROM silver_returns
     WHERE currency_code IS NULL OR currency_code NOT IN ({accepted_currencies})) AS observed
""",
    "DUPLICATES_RESOLVED": """
SELECT COUNT(*) AS observed
FROM silver_order_versions
WHERE version_rank > 1
""",
    "QUARANTINED_ROWS": """
SELECT COUNT(*) AS observed
FROM silver_quarantine
""",
    "HIGH_RETURN_RATE": """
SELECT COALESCE(MAX(return_rate_pct), 0) AS observed
FROM (
    SELECT
        category_code,
        CAST(ROUND(100 * SUM(returns_cad) / NULLIF(SUM(gross_revenue_cad), 0), 0) AS INT)
            AS return_rate_pct
    FROM silver_reconciled_sales
    WHERE gross_revenue_cad IS NOT NULL
    GROUP BY category_code
) rates
""",
    "VOLUME_ANOMALY": """
SELECT COUNT(*) AS observed
FROM (
    SELECT
        category_code,
        order_date,
        COUNT(*) AS daily_orders,
        AVG(COUNT(*)) OVER (PARTITION BY category_code) AS average_daily_orders
    FROM silver_orders
    GROUP BY category_code, order_date
) volumes
WHERE daily_orders > {volume_anomaly_factor} * average_daily_orders
""",
}


def format_sql(sql, params):
    values = dict(params)
    values["accepted_currencies"] = ", ".join(f"'{c}'" for c in params["accepted_currencies"])
    return sql.format(**values)


def freshness_minutes(latest, as_of):
    if latest is None:
        return None
    ingested = datetime.fromisoformat(str(latest).replace("Z", "+00:00"))
    if ingested.tzinfo is None:
        ingested = ingested.replace(tzinfo=UTC)
    return int((as_of - ingested).total_seconds() // 60)


def describe_check(name, observed, params, breached):
    def count(n, singular, plural):
        return f"{n:,} {singular if n == 1 else plural}"

    if name in ("ORDERS_FRESHNESS", "RETURNS_FRESHNESS"):
        feed = "orders" if name == "ORDERS_FRESHNESS" else "returns"
        sla = params[f"{feed}_freshness_sla_minutes"]
        if observed is None:
            return f"no {feed} extract has been ingested"
        if breached:
            return (
                f"the {feed} feed is stale (last extract {observed:,} minutes old; "
                f"SLA {sla} minutes)"
            )
        return f"the {feed} extract is {observed:,} minutes old (SLA {sla} minutes)"
    if name == "DUPLICATE_BUSINESS_KEYS":
        if breached:
            keys = count(observed, "business key remains", "business keys remain")
            return f"{keys} duplicated after Silver processing"
        return "no duplicate business keys after Silver processing"
    if name == "MISSING_FX":
        if breached:
            return (
                "currency conversion coverage is incomplete "
                f"({count(observed, 'order has', 'orders have')} no transaction-date FX rate)"
            )
        return "every non-CAD order has a transaction-date FX rate"
    if name == "ORPHAN_RETURNS":
        if breached:
            return (
                f"{count(observed, 'return references', 'returns reference')} an unknown order "
                "(referential integrity violation)"
            )
        return "every return references a known order"
    if name == "MISSING_REQUIRED_KEYS":
        if breached:
            return f"{count(observed, 'row has', 'rows have')} missing or unknown required keys"
        return "all required keys are present and known"
    if name == "UNSUPPORTED_CURRENCY":
        accepted = ", ".join(params["accepted_currencies"])
        if breached:
            return f"{count(observed, 'row uses', 'rows use')} a currency outside {accepted}"
        return f"all rows use an accepted currency ({accepted})"
    if name == "DUPLICATES_RESOLVED":
        if breached:
            return (
                f"{count(observed, 'duplicate order event was', 'duplicate order events were')} "
                "detected and discarded by the deduplication policy"
            )
        return "no duplicate order events detected"
    if name == "QUARANTINED_ROWS":
        if breached:
            return f"{count(observed, 'row was', 'rows were')} quarantined by contract rules"
        return "no rows quarantined"
    if name == "HIGH_RETURN_RATE":
        limit = params["max_category_return_rate_pct"]
        return f"the highest category return rate is {observed}% (warning above {limit}%)"
    if name == "VOLUME_ANOMALY":
        factor = params["volume_anomaly_factor"]
        if breached:
            days = count(observed, "category day exceeds", "category days exceed")
            return f"{days} {factor}x the average daily volume"
        return f"no category day exceeds {factor}x the average daily volume"
    return f"{name}: observed {observed}"


def evaluate_check(name, severity, observed, params):
    if name in ("ORDERS_FRESHNESS", "RETURNS_FRESHNESS"):
        feed = "orders" if name == "ORDERS_FRESHNESS" else "returns"
        limit = params[f"{feed}_freshness_sla_minutes"]
        threshold = f"<= {limit} minutes"
        breached = observed is None or observed > limit
    elif name == "HIGH_RETURN_RATE":
        limit = params["max_category_return_rate_pct"]
        threshold = f"<= {limit} percent"
        breached = observed > limit
    else:
        threshold = "= 0"
        breached = observed > 0
    if not breached:
        status = "PASS"
    elif severity == "BLOCKING":
        status = "FAIL"
    else:
        status = "WARN"
    return {
        "check_name": name,
        "severity": severity,
        "observed_value": observed,
        "threshold": threshold,
        "status": status,
        "detail": describe_check(name, observed, params, breached),
    }


def run_quality_checks(scalar, params, severities, as_of):
    """Evaluate every contract check. ``scalar(sql)`` returns the first column of row one."""
    results = []
    for name, severity in severities.items():
        if name in LATEST_INGESTION_SQL:
            latest = scalar(format_sql(LATEST_INGESTION_SQL[name], params))
            observed = freshness_minutes(latest, as_of)
        else:
            observed = int(scalar(format_sql(QUALITY_CHECK_SQL[name], params)) or 0)
        results.append(evaluate_check(name, severity, observed, params))
    return results


def summarise_health(results):
    observed = {r["check_name"]: r["observed_value"] for r in results}
    blocking = [f"{r['check_name']}: {r['detail']}" for r in results if r["status"] == "FAIL"]
    warnings = [f"{r['check_name']}: {r['detail']}" for r in results if r["status"] == "WARN"]
    return {
        "status": "BLOCKED" if blocking else "READY",
        "blocking_reasons": " | ".join(blocking),
        "warning_reasons": " | ".join(warnings),
        "orders_freshness_minutes": observed.get("ORDERS_FRESHNESS"),
        "returns_freshness_minutes": observed.get("RETURNS_FRESHNESS"),
        "duplicate_count": (observed.get("DUPLICATES_RESOLVED") or 0)
        + (observed.get("DUPLICATE_BUSINESS_KEYS") or 0),
        "missing_fx_count": observed.get("MISSING_FX") or 0,
        "orphan_return_count": observed.get("ORPHAN_RETURNS") or 0,
        "missing_key_count": observed.get("MISSING_REQUIRED_KEYS") or 0,
        "unsupported_currency_count": observed.get("UNSUPPORTED_CURRENCY") or 0,
        "quarantined_rows": observed.get("QUARANTINED_ROWS") or 0,
    }


# %% [markdown]
# ## Contract parameters
#
# Read from `reference/data_contract_metadata.csv`, which is generated from the YAML contracts
# in the repository (`contracts/`).

# %%
metadata = {
    row["key"]: row["value"]
    for row in spark.read.option("header", True)
    .csv(f"{data_root}/reference/data_contract_metadata.csv")
    .collect()
}
CONTRACT_VERSION = metadata["data_contract_version"]
SEVERITIES = {
    key.split(".", 1)[1]: value for key, value in metadata.items() if key.startswith("severity.")
}
STARTED = datetime.now(UTC)
RUN_ID = f"run-{STARTED:%Y%m%dT%H%M%SZ}-{scenario_mode}-{uuid.uuid4().hex[:6]}"
PARAMS = {
    "run_id": RUN_ID,
    "scenario_mode": scenario_mode,
    "accepted_currencies": metadata["accepted_currencies"].split("|"),
    "orders_freshness_sla_minutes": int(metadata["orders_freshness_sla_minutes"]),
    "returns_freshness_sla_minutes": int(metadata["returns_freshness_sla_minutes"]),
    "max_category_return_rate_pct": int(metadata["max_category_return_rate_pct"]),
    "volume_anomaly_factor": int(metadata["volume_anomaly_factor"]),
}
print(f"Run {RUN_ID} | contract {CONTRACT_VERSION} | checks: {', '.join(SEVERITIES)}")

# %% [markdown]
# ## Helpers


# %%
def ddl(columns):
    return ", ".join(f"{name} {kind}" for name, kind in columns)


def save(df, table):
    df.write.mode("overwrite").option("overwriteSchema", "true").format("delta").saveAsTable(table)


def scalar(sql):
    row = spark.sql(sql).first()
    return None if row is None else row[0]


def create(table, sql, publish=True):
    df = spark.sql(sql)
    save(df if publish else df.limit(0), table)


def record_rows(table, records):
    names = [name for name, _ in OBSERVABILITY_SCHEMAS[table]]
    rows = [tuple(record.get(name) for name in names) for record in records]
    return spark.createDataFrame(rows, ddl(OBSERVABILITY_SCHEMAS[table]))


def read_records(table):
    return [row.asDict() for row in spark.table(table).collect()]


def ensure_observability_tables():
    for table, columns in OBSERVABILITY_SCHEMAS.items():
        spark.sql(f"CREATE TABLE IF NOT EXISTS {table} ({ddl(columns)}) USING DELTA")


def write_run(record, reset_history=False):
    existing = [] if reset_history else read_records("gold_pipeline_runs")
    runs = [r for r in existing if r["pipeline_run_id"] != record["pipeline_run_id"]]
    save(record_rows("gold_pipeline_runs", [*runs, record]), "gold_pipeline_runs")


def write_health(record):
    save(record_rows("gold_data_product_health", [record]), "gold_data_product_health")


def last_success():
    value = scalar(
        "SELECT CAST(MAX(completed_at_utc) AS STRING) FROM gold_pipeline_runs "
        "WHERE status = 'READY'"
    )
    return None if value is None else datetime.fromisoformat(value).replace(tzinfo=UTC)


# %% [markdown]
# ## Pipeline steps


# %%
def load_bronze():
    for source in BRONZE_SOURCES:
        relative = source["path"].format(scenario_mode=scenario_mode)
        df = (
            spark.read.option("header", True)
            .schema(ddl(source["columns"]))
            .csv(f"{data_root}/{relative}")
        )
        if "source_system" not in df.columns:
            df = df.withColumn("source_system", F.lit(source["source_system"]))
        df = df.withColumn("source_file", F.lit(relative))
        save(df, source["table"])
        print(f"Bronze {source['table']:<18} {df.count():>6} rows  <- {relative}")


def build_silver_and_dimensions():
    for table, sql in SILVER_TRANSFORMS + GOLD_DIMENSION_TRANSFORMS:
        create(table, format_sql(sql, PARAMS))
        print(f"Built  {table}")


def evaluate_quality():
    results = run_quality_checks(scalar, PARAMS, SEVERITIES, AS_OF)
    evaluated = datetime.now(UTC)
    rows = [{**r, "pipeline_run_id": RUN_ID, "evaluated_at_utc": evaluated} for r in results]
    df = record_rows("silver_quality_results", rows)
    if scenario_mode == "broken":
        save(df, "silver_quality_results")
    else:
        df.write.mode("append").format("delta").saveAsTable("silver_quality_results")
    display(df.select("check_name", "severity", "status", "observed_value", "threshold", "detail"))
    return results


def publish_gold(health):
    publish = health["status"] == "READY"
    for table, sql in GOLD_FACT_TRANSFORMS:
        create(table, format_sql(sql, PARAMS), publish=publish)
        print(f"Gold   {table:<18} {'published' if publish else 'withheld (fail closed)'}")
    return publish


# %% [markdown]
# ## Run
#
# Records a `RUNNING` run and health status first, so no answer is served from partial data.

# %%
ensure_observability_tables()
previous_success = None if scenario_mode == "broken" else last_success()
clock_start = time.perf_counter()
run_record = {
    "pipeline_run_id": RUN_ID,
    "scenario_mode": scenario_mode,
    "started_at_utc": STARTED,
    "status": "RUNNING",
    "data_contract_version": CONTRACT_VERSION,
}
health_base = {
    "data_product": DATA_PRODUCT,
    "data_contract_version": CONTRACT_VERSION,
    "scenario_mode": scenario_mode,
    "as_of_utc": AS_OF,
    "freshness_sla_minutes": PARAMS["returns_freshness_sla_minutes"],
    "pipeline_run_id": RUN_ID,
}
write_run(run_record, reset_history=scenario_mode == "broken")
write_health(
    {
        **health_base,
        "status": "RUNNING",
        "last_successful_refresh_utc": previous_success,
        "evaluated_at_utc": STARTED,
    }
)

try:
    load_bronze()
    build_silver_and_dimensions()
    results = evaluate_quality()
    health = summarise_health(results)
    published = publish_gold(health)
    counts = {
        "bronze_order_rows": scalar("SELECT COUNT(*) FROM bronze_orders"),
        "bronze_return_rows": scalar("SELECT COUNT(*) FROM bronze_returns"),
        "silver_sales_rows": scalar("SELECT COUNT(*) FROM silver_reconciled_sales"),
    }
except Exception as exc:
    failed_at = datetime.now(UTC)
    reason = f"PIPELINE_ERROR: {type(exc).__name__}: {exc}"
    write_run(
        {
            **run_record,
            "status": "FAILED",
            "completed_at_utc": failed_at,
            "failure_reasons": reason,
            "duration_ms": int((time.perf_counter() - clock_start) * 1000),
        }
    )
    write_health(
        {
            **health_base,
            "status": "FAILED",
            "blocking_reasons": reason,
            "last_successful_refresh_utc": previous_success,
            "evaluated_at_utc": failed_at,
        }
    )
    raise

completed = datetime.now(UTC)
freshness = [
    m
    for m in (health["orders_freshness_minutes"], health["returns_freshness_minutes"])
    if m is not None
]
write_run(
    {
        **run_record,
        **counts,
        "status": health["status"],
        "completed_at_utc": completed,
        "quarantined_rows": health["quarantined_rows"],
        "duplicate_count": health["duplicate_count"],
        "missing_fx_count": health["missing_fx_count"],
        "orphan_return_count": health["orphan_return_count"],
        "freshness_minutes": max(freshness) if freshness else None,
        "failure_reasons": health["blocking_reasons"],
        "warning_reasons": health["warning_reasons"],
        "duration_ms": int((time.perf_counter() - clock_start) * 1000),
    }
)
write_health(
    {
        **health_base,
        **health,
        "last_successful_refresh_utc": completed if published else previous_success,
        "evaluated_at_utc": completed,
    }
)
print(f"Run {RUN_ID} finished: {health['status']}")

# %% [markdown]
# ## Validation summary and business outcome
#
# The same question the application asks. These queries are copies of `fabric/sql/*.sql`.

# %%
RAW_ANSWER_SQL = """
-- Act 1: the naive raw answer ("confidently wrong").
-- Valid SQL, valid arithmetic, wrong data contract:
--   * reads raw landing rows directly, so the replayed duplicate order is counted twice
--   * calls SUM(gross_amount) "revenue" and treats USD amounts as if they were CAD
--   * ignores returns entirely
--   * checks no freshness, no quality gate and no approved metric definition
SELECT
    o.category_code,
    c.category_name,
    COUNT(*) AS order_rows,
    SUM(CASE WHEN o.currency_code <> 'CAD' THEN 1 ELSE 0 END) AS non_cad_rows,
    SUM(o.gross_amount) AS revenue,
    t.target_cad,
    MAX(o.ingested_at) AS latest_ingested_at
FROM bronze_orders AS o
JOIN ref_categories AS c
    ON c.category_code = o.category_code
JOIN bronze_targets AS t
    ON t.region_code = o.region_code
   AND t.category_code = o.category_code
   AND t.target_month = '2026-08'
WHERE o.region_code = 'ON'
  AND o.order_timestamp_utc >= '2026-08-01'
  AND o.order_timestamp_utc < '2026-09-01'
GROUP BY o.category_code, c.category_name, t.target_cad
ORDER BY o.category_code
"""

GOVERNED_ANSWER_SQL = """
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
CROSS JOIN targets AS t
"""

CATEGORY_VARIANCE_SQL = """
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
ORDER BY variance_cad, c.category_code
"""

display(spark.table("gold_data_product_health"))
display(spark.sql("SELECT * FROM gold_pipeline_runs ORDER BY started_at_utc DESC"))

raw = spark.sql(RAW_ANSWER_SQL).collect()
raw_revenue = sum(r["revenue"] for r in raw)
raw_target = sum(r["target_cad"] for r in raw)
print(
    f"Raw (ungoverned) path: 'revenue' {raw_revenue:,.2f} vs target {raw_target:,.2f} "
    f"-> {'beat' if raw_revenue > raw_target else 'missed'} (wrong data contract)"
)

if health["status"] == "READY":
    governed = spark.sql(GOVERNED_ANSWER_SQL).first()
    display(spark.sql(CATEGORY_VARIANCE_SQL))
    worst = spark.sql(CATEGORY_VARIANCE_SQL).first()
    print(
        f"Governed Net Revenue CAD {governed['net_revenue_cad']:,.2f} vs target "
        f"{governed['target_cad']:,.2f}: variance {governed['variance_cad']:,.2f} "
        f"({governed['variance_pct']}%). Largest negative category: {worst['category_name']} "
        f"({worst['variance_cad']:,.2f}). Run {governed['pipeline_run_id']}."
    )
else:
    print("Governed path: refused. The data product is not READY:")
    for reason in health["blocking_reasons"].split(" | "):
        print(f"  - {reason}")

# %%
if health["status"] != "READY" and fail_on_blocked:
    raise RuntimeError(
        f"Data product {DATA_PRODUCT} is {health['status']} (run {RUN_ID}): "
        f"{health['blocking_reasons']}"
    )
