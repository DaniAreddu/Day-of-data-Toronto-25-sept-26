"""Data-quality gates for the net_revenue_cad data product.

The SQL and the functions below are stdlib-only and are copied verbatim into the Fabric
notebook; ``tests/test_fabric_assets.py`` checks that both copies stay identical.
Severity (BLOCKING or WARNING) comes from ``contracts/data_product_health.contract.yml``.
"""

from __future__ import annotations

from datetime import UTC, datetime

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
