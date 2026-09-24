# The trusted platform (Acts 2 and 3)

```text
Azure SQL Orders ─┐
                  │
SQL Server Returns┼─► Bronze ──► Silver ──────────────────► Quality gates ──► Gold ─────────► Semantic contract ─► AI application
                  │   as-received  dedup (business key)       BLOCKING           star schema    net_revenue_cad       reads health first;
Treasury FX ──────┘   + lineage    FX on transaction date     vs WARNING         + health       (YAML + DAX)          answers or refuses
Reference data        columns      returns reconciliation     (contract-driven)  + run records
                                   quarantine
```

## Layers

**Bronze** (`bronze_orders`, `bronze_returns`, `bronze_fx_rates`, `bronze_targets`, `ref_*`):
extracts exactly as received, duplicates included, with `source_system`, `source_file`,
source timestamps, ingestion timestamps and event/version metadata. Nothing is repaired here.

**Silver** (`silver_order_versions`, `silver_orders`, `silver_returns`, `silver_quarantine`,
`silver_reconciled_sales`, `silver_quality_results`): technical correctness.

* Deterministic deduplication: partition by `order_id`, order by `event_version DESC,
  source_updated_at DESC, ingested_at DESC, event_id DESC`, keep rank 1. Superseded rows stay
  visible in `silver_order_versions` and are counted (`DUPLICATES_RESOLVED`).
* Code normalisation (trim, upper case), UTC timestamps, typed decimals.
* Returns reconciliation: `ACCEPTED`, `ORPHAN`, `QUARANTINED` or `ORDER_EXCLUDED`.
* FX lookup on the order's transaction date, with no nearest-date fallback.
* Quarantine for contract-excluded rows (test transactions, invalid amounts) with a reason.

**Quality gates** (`contracts/data_product_health.contract.yml`): seven blocking checks
(orders and returns freshness, duplicate business keys after Silver, missing FX, orphan
returns, missing or unknown required keys, unsupported currency) and four warnings. Rows that
*may* be excluded are quarantined. Conditions that would silently bias the metric, such as
dropping unconvertible or orphaned rows, block the product instead.

**Gold** (`gold_fact_sales`, `gold_fact_targets`, `gold_dim_date`, `gold_dim_region`,
`gold_dim_category`, `gold_data_product_health`, `gold_pipeline_runs`): a star schema where
`net_revenue_cad = gross_revenue_cad - returns_cad` is calculated once, by the pipeline. Fact
tables are published only when the product is `READY`; otherwise they are withheld (fail closed).

**Semantic contract**: `contracts/net_revenue.metric.yml` and the `TrustedBusinessMetrics` DAX
measures aggregate Gold. They never redefine the metric.

**AI application**: `governed_path.ask_governed()` reads `gold_data_product_health` first.
`status != "READY"` returns a deterministic refusal with reasons; the governed SQL itself
returns no rows unless the product is `READY`. The narrator, deterministic or local LLM,
receives computed JSON facts only.

## Same logic in two engines

| Concern | Local (conference fallback) | Fabric Trial |
| --- | --- | --- |
| Storage | DuckDB file in `.demo-state/` | Lakehouse Delta tables |
| Transforms | `medallion.py` SQL via DuckDB | identical SQL via Spark in `BuildTrustedLayer` |
| Orchestration | Streamlit button / CLI | `RefreshEnterpriseData` pipeline (one Notebook activity) |
| Serving | same `fabric/sql/*.sql` files | SQL analytics endpoint + Direct Lake semantic model |

## Observability and enterprise monitoring

Every run writes one `gold_pipeline_runs` row (`pipeline_run_id`, `scenario_mode`, start and
completion time, `status` in `RUNNING | BLOCKED | FAILED | READY`, Bronze and Silver row counts,
quarantined rows, duplicate count, missing FX count, orphan returns, worst feed freshness,
contract version, failure reasons, duration) and replaces the `gold_data_product_health` row.

In production the same fields would feed existing tooling without changing their meaning:

* **Alerting**: a Fabric pipeline failure path, Data Activator (Reflex) rule or scheduled
  query that alerts when `status IN ('BLOCKED','FAILED')` or `freshness_minutes > SLA`.
* **Dashboards**: a Power BI report on `gold_pipeline_runs` (trend of duration, quarantine
  counts, blocked runs by reason).
* **Central monitoring**: export run rows to Azure Monitor / Log Analytics or a SIEM keyed by
  `pipeline_run_id`, so AI-application logs, data-pipeline logs and model logs correlate.
* **Separate failure domains**: model errors (narration rejected), data errors (BLOCKED) and
  platform errors (FAILED) are distinct statuses, so on-call knows which team to wake.

None of these services is required or configured in the free demo.
