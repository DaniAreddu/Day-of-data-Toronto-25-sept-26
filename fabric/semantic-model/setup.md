# TrustedBusinessMetrics: semantic model setup

Creates a Direct Lake semantic model named **TrustedBusinessMetrics** over the Gold tables.
No Copilot, Data Agent or AI feature is required. UI labels are in English; likely Italian
equivalents are given in brackets and may vary slightly between Fabric releases.

## Prerequisites

`BuildTrustedLayer` has run in `repaired` mode, so the Gold fact tables are published and
`gold_data_product_health.status` is `READY`.

## Steps

1. Open the **AIPlatform** Lakehouse (or its **SQL analytics endpoint**
   [Endpoint di analisi SQL]).
2. Select **New semantic model** [Nuovo modello semantico].
3. Name it `TrustedBusinessMetrics` and select these tables:
   `gold_fact_sales`, `gold_fact_targets`, `gold_dim_date`, `gold_dim_region`,
   `gold_dim_category`, `gold_data_product_health`, `gold_pipeline_runs`. Select **Confirm**
   [Conferma].
4. Open the model (**Open data model** [Apri modello di dati]) and create the relationships in
   [relationships.md](relationships.md), via drag and drop or **Manage relationships**
   [Gestisci relazioni].
5. Select `gold_fact_sales`, choose **New measure** [Nuova misura] and paste each measure from
   [measures.dax](measures.dax), one at a time (the text before `=` is the measure name).
6. Apply the formats noted above each measure (Properties pane → **Format** [Formato]).
7. Mark `gold_dim_date` as a date table (**Mark as date table** [Segna come tabella di date])
   using `calendar_date`.

## Validate

Create a quick report (or use the model's **Explore** view) with:

* slicers: `gold_dim_region[region_name]` = Ontario, `gold_dim_date[year_month]` = 2026-08;
* cards: `Net Revenue CAD`, `Revenue Target CAD`, `Variance to Target CAD`,
  `Variance to Target %`, `Largest Negative Category`, `Data Product Status`,
  `Latest Refresh UTC`;
* a table of `gold_dim_category[category_name]` with `Net Revenue CAD`, `Revenue Target CAD`
  and `Variance to Target CAD`.

Expected values are listed in [../README.md](../README.md#expected-results). They must match
the application's governed answer and `fabric/sql/governed_answer.sql`.

## Metric formats

| Measure                  | Format                          |
| ------------------------ | ------------------------------- |
| Gross Revenue CAD        | Currency, 2 decimals            |
| Returns CAD              | Currency, 2 decimals            |
| Net Revenue CAD          | Currency, 2 decimals            |
| Revenue Target CAD       | Currency, 2 decimals            |
| Variance to Target CAD   | Currency, 2 decimals            |
| Variance to Target %     | Percentage, 2 decimals          |
| Largest Negative Category| Text                            |
| Latest Refresh UTC       | Date/time (UTC)                 |
| Data Product Status      | Text                            |
| Data Is Trusted          | True/False                      |

## Reset behaviour

After running the notebook in `broken` mode the Gold fact tables are empty (publication is
withheld) and `Data Product Status` shows `BLOCKED`. That is intended: the model fails closed.
If a visual shows stale values, refresh the report; Direct Lake picks up the new Delta version.
