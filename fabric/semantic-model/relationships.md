# TrustedBusinessMetrics: relationships

Star schema over the Gold tables built by `BuildTrustedLayer`. All relationships are
**many-to-one (\*:1)**, **single cross-filter direction** (dimension filters fact), **active**.

| From (many side)                | To (one side)                    | Notes                                   |
| ------------------------------- | -------------------------------- | --------------------------------------- |
| `gold_fact_sales[date_key]`     | `gold_dim_date[date_key]`        | order transaction date (UTC)            |
| `gold_fact_sales[region_key]`   | `gold_dim_region[region_key]`    |                                         |
| `gold_fact_sales[category_key]` | `gold_dim_category[category_key]`|                                         |
| `gold_fact_targets[date_key]`   | `gold_dim_date[date_key]`        | monthly targets sit on day 1 of the month |
| `gold_fact_targets[region_key]` | `gold_dim_region[region_key]`    |                                         |
| `gold_fact_targets[category_key]` | `gold_dim_category[category_key]` |                                       |

Disconnected tables (no relationships, used by the status measures only):

* `gold_data_product_health`: one row per data product (`net_revenue_cad`).
* `gold_pipeline_runs`: run history for observability visuals.

## Why targets relate on day 1

Targets are approved at month grain (`target_month = '2026-08'`). The pipeline maps each target
to the `date_key` of the first day of that month, so filtering `gold_dim_date[year_month]` to
`2026-08` filters both facts consistently. Do not filter targets by individual days.

## Recommended model settings

* Mark `gold_dim_date` as a date table using `calendar_date`.
* Hide key columns (`*_key`) and the fact tables' technical lineage columns from report view.
* Sort `gold_dim_date[month_name]` by `gold_dim_date[month_number]`.
