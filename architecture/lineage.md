# Lineage

```text
Azure SQL Orders
        \
         → Bronze → Silver → Gold → Semantic Contract → AI Application
        /
SQL Server Returns
```

(FX and reference data join at Silver; targets join at Gold.)

## Column-level lineage of the governed answer

| Gold column (`gold_fact_sales`) | Derived from | Transformation |
| --- | --- | --- |
| `order_key` | `sales.orders.order_id` | business key after deduplication |
| `date_key` | `order_timestamp_utc` | UTC calendar date → `gold_dim_date` |
| `region_key`, `category_key` | `region_code`, `category_code` | normalised, validated against `ref_*` |
| `gross_revenue_cad` | `gross_amount` × `bronze_fx_rates.rate` | rate of the transaction date; CAD rate = 1; rounded to cents |
| `returns_cad` | Σ accepted `dbo.returns.return_amount` × same rate | only `ACCEPTED` returns |
| `net_revenue_cad` | `gross_revenue_cad − returns_cad` | defined once, in Gold |
| `original_currency`, `applied_fx_rate` | source currency, applied rate | kept for audit |
| `order_source_system`, `order_source_event_id`, `order_source_updated_at` | Bronze metadata | source identity preserved |
| `returns_source_system`, `fx_source_system` | Silver joins | which systems contributed |
| `pipeline_run_id` | pipeline | links every row to `gold_pipeline_runs` |

## Answer-level lineage

Every governed answer carries the pipeline run id, last successful refresh time, contract
version, quality status and the set of source systems (`source_lineage.sql`). The same run id
appears in `silver_quality_results`, `silver_quarantine`, `gold_pipeline_runs` and the health
record, so an answer can be traced to the exact checks and extracts that produced it.

## Production extension

Microsoft Purview can scan Fabric items and SQL sources to build catalogue-level lineage. It is
an optional extension and is **not** configured in this demo; the lineage shown here comes from
columns the pipeline writes itself, which works without any catalogue.
