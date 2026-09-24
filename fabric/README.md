# Microsoft Fabric assets (portable, manually importable)

GitHub is the source of truth; Fabric is the execution environment. The tenant does not have
the GitHub provider enabled for Fabric Git integration, so nothing here depends on native Git
sync: there are no Fabric-managed item folders, no `.platform` files and no workspace,
Lakehouse or item identifiers. Everything is imported or pasted by hand.

Target: a free **Microsoft Fabric Trial** workspace `DayOfDataToronto-Dev` with a Lakehouse
`AIPlatform`. Used capabilities: Lakehouse, notebooks (PySpark), pipelines, SQL analytics
endpoint, semantic model, Power BI, Monitor. **Not** used: Data Agent, Copilot, AI Functions,
AI Services, Azure OpenAI or any external model API.

*A synthetic, production-inspired architecture scenario. It does not represent a real customer
deployment.* The CSV files are synthetic extracts representing an Azure SQL orders system and an
on-premises SQL Server returns system; no database connection is made.

| Path | What it is |
| --- | --- |
| `notebooks/BuildTrustedLayer.ipynb` | Importable notebook (generated from the `.py`) |
| `notebooks/BuildTrustedLayer.py` | Reviewable source of the same notebook |
| `sql/*.sql` | Read-only queries for the SQL analytics endpoint (also used by the local app) |
| `semantic-model/` | `TrustedBusinessMetrics` relationships, DAX measures, setup |
| `pipeline/manual-setup.md` | Exact steps for the `RefreshEnterpriseData` pipeline |

## Quick path

1. `python scripts/package_fabric_upload.py` → `dist/fabric-upload/` (and `.zip`).
2. Lakehouse `AIPlatform` → **Files** → upload the package's `data` folder so that
   `Files/data/azure-sql/orders.csv` exists.
3. Workspace → **Import** → **Notebook** → `BuildTrustedLayer.ipynb`; attach `AIPlatform`
   as the default Lakehouse.
4. Run it with `scenario_mode = "broken"` (ends with an intentional error), then create the
   `RefreshEnterpriseData` pipeline and run it with `repaired`.
5. Run the `sql/` queries on the SQL analytics endpoint; build `TrustedBusinessMetrics`.

The full, click-by-click guide (with Italian UI hints) is
[docs/fabric-setup.md](../docs/fabric-setup.md).

## Upload layout

```text
Files/
└── data/
    ├── azure-sql/orders.csv
    ├── sql-server/returns.broken.csv
    ├── sql-server/returns.repaired.csv
    └── reference/
        ├── fx_rates.broken.csv
        ├── fx_rates.repaired.csv
        ├── targets.csv
        ├── regions.csv
        ├── categories.csv
        ├── calendar.csv
        └── data_contract_metadata.csv
```

## Tables created

Bronze: `bronze_orders`, `bronze_returns`, `bronze_fx_rates`, `bronze_targets`, `ref_regions`,
`ref_categories`, `ref_calendar`.
Silver: `silver_order_versions`, `silver_orders`, `silver_returns`, `silver_quarantine`,
`silver_reconciled_sales`, `silver_quality_results`.
Gold: `gold_dim_date`, `gold_dim_region`, `gold_dim_category`, `gold_fact_sales`,
`gold_fact_targets`, `gold_data_product_health`, `gold_pipeline_runs`.

The notebook's transforms and quality checks are the same statements the local DuckDB demo
runs; `tests/test_fabric_assets.py` fails if the two copies diverge.

## Expected results

Question: *Did Ontario beat its August 2026 revenue target, and which product category drove
the result?* (seed 20260926, scenario as-of 2026-09-26T18:00:00Z)

| | Raw path (`raw_answer.sql`) | Governed path, after `repaired` run |
| --- | --- | --- |
| Figure | "revenue" CAD 337,501.76 | Net Revenue CAD 320,475.66 |
| Target | CAD 328,000.00 | CAD 328,000.00 |
| Variance | +CAD 9,501.76 (+2.90%) | −CAD 7,524.34 (−2.29%) |
| Category | Devices "drove" the beat: +CAD 10,526.85 | Devices largest negative: −CAD 9,696.55 |

After a `broken` run, `platform_health.sql` returns `BLOCKED` with three blocking reasons:
returns feed 3,600 minutes old (SLA 240), 3 orders without a transaction-date FX rate, 1 orphan
return. It also reports 1 resolved duplicate order event and 1 quarantined test order as warnings.

These figures are produced by the data, not by the application: `tests/test_docs.py` checks that
this table matches `sample-data/scenario_summary.json`.

## Known Fabric caveats

* Run timestamps (`started_at_utc`, `completed_at_utc`) are wall-clock UTC; freshness uses the
  fixed scenario clock parameter `demo_clock_utc`.
* The notebook sets `spark.sql.session.timeZone = UTC`. Fabric Spark drivers run in UTC; if a
  custom environment changes the driver time zone, run-history timestamps can shift.
* SQL analytics endpoint metadata sync can lag a few seconds behind a notebook run. If a query
  shows the previous state, wait briefly and rerun it.
