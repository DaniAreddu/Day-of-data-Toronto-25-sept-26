# Microsoft Fabric setup guide (Fabric Trial, manual import)

Step-by-step guide for running the AI Reliability Lab in a free **Microsoft Fabric Trial**.
GitHub stays the source of truth; nothing relies on Fabric Git integration (the tenant does not
have the GitHub provider enabled). No Azure subscription, paid capacity, Copilot, Data Agent,
AI Functions or external model API is needed.

* Workspace: `DayOfDataToronto-Dev`
* Lakehouse: `AIPlatform`
* Notebook: `BuildTrustedLayer`
* Pipeline: `RefreshEnterpriseData`
* Semantic model: `TrustedBusinessMetrics`

UI labels are in English. Likely Italian equivalents are in brackets; Fabric wording changes
between releases, so treat them as hints.

*A synthetic, production-inspired architecture scenario. It does not represent a real customer
deployment.*

## 0. Prepare the upload package (local)

```bash
python scripts/package_fabric_upload.py
```

This creates `dist/fabric-upload/` and `dist/fabric-upload.zip` with the synthetic CSVs, the
notebook, SQL, DAX and these guides. It contains no secrets and no application code.

## 1. Create the Lakehouse

1. Open the workspace `DayOfDataToronto-Dev` (create it first if needed: **Workspaces**
   [Aree di lavoro] → **New workspace** [Nuova area di lavoro], assign the Trial capacity).
2. **New item** [Nuovo elemento] → **Lakehouse** → name `AIPlatform` → **Create** [Crea].
   Leave "Lakehouse schemas" at its default; the notebook writes to the default schema.

## 2. Upload the source files into `Files/data`

1. In the Lakehouse explorer, open **Files** [File] → **…** → **Upload** [Carica] →
   **Upload folder** [Carica cartella].
2. Select `dist/fabric-upload/data`. The result must be `Files/data/azure-sql/orders.csv`,
   `Files/data/sql-server/...` and `Files/data/reference/...` (see
   [fabric/README.md](../fabric/README.md#upload-layout)).
3. If your browser uploads only files, create the folders `data`, `data/azure-sql`,
   `data/sql-server` and `data/reference` with **New subfolder** [Nuova sottocartella] and
   upload the files into each.

## 3. Import `BuildTrustedLayer.ipynb`

1. Go back to the workspace → **Import** [Importa] → **Notebook** → **From this computer**
   [Da questo computer].
2. Choose `dist/fabric-upload/notebooks/BuildTrustedLayer.ipynb`.

## 4. Attach the Lakehouse

1. Open the notebook. In the **Explorer** pane select **Add data items** [Aggiungi elementi
   dati] (or **Lakehouses** → **Add** [Aggiungi]) → **Existing data source**
   [Origine dati esistente] → `AIPlatform`.
2. Make sure it is the **default** Lakehouse (pin icon). Relative paths such as
   `Files/data/...` and table names resolve against it.

## 5. Run in broken mode

1. In the parameters cell keep `scenario_mode = "broken"`.
2. **Run all** [Esegui tutto]. The session starts in about a minute on a Trial capacity.
3. The last cell raises `RuntimeError: Data product net_revenue_cad is BLOCKED ...`.
   **This is intended.** The health and run tables were written before the error.

## 6. Inspect Bronze and health tables

In the Lakehouse explorer (**Tables** [Tabelle], refresh if needed):

* `bronze_orders`: 1,122 rows, including the replayed duplicate `SO-202608-00490`;
* `bronze_returns`: the stale broken extract (ingested 2026-09-24 06:00 UTC);
* `gold_data_product_health`: status `BLOCKED` and the blocking reasons;
* `silver_quality_results`: one row per check with PASS / FAIL / WARN;
* `gold_fact_sales`: empty. Publication is withheld while the product is unhealthy.

## 7. Create the `RefreshEnterpriseData` pipeline

Follow [fabric/pipeline/manual-setup.md](../fabric/pipeline/manual-setup.md): one Notebook
activity calling `BuildTrustedLayer` with base parameter
`scenario_mode = @pipeline().parameters.scenario_mode`.

## 8. Run in repaired mode

Run the pipeline with `scenario_mode = repaired`. It succeeds. The notebook prints the governed
answer, and `gold_data_product_health.status` becomes `READY`.

## 9. Inspect the Gold tables

`gold_fact_sales` (governed orders with `net_revenue_cad`, `applied_fx_rate`,
`pipeline_run_id`, source-lineage columns), `gold_fact_targets`, `gold_dim_*`,
`gold_pipeline_runs` (the BLOCKED run and the READY run).

## 10. Open the SQL analytics endpoint

In the Lakehouse, switch the top-right selector from **Lakehouse** to **SQL analytics
endpoint** [Endpoint di analisi SQL] (or open the `AIPlatform` SQL analytics endpoint item).

## 11. Execute the provided SQL

**New SQL query** [Nuova query SQL], paste and run each file from `fabric/sql/`:

1. `raw_answer.sql`: the confidently wrong answer (Act 1);
2. `platform_health.sql`: health status and reasons (Act 2);
3. `governed_answer.sql`: governed total, target and variance (Act 3);
4. `category_variance.sql`: Devices is the most negative category;
5. `source_lineage.sql`, `pipeline_evidence.sql`, `quality_results.sql`: evidence.

The endpoint is read-only. These queries run unchanged on DuckDB locally.

## 12. Create the semantic model

Follow [fabric/semantic-model/setup.md](../fabric/semantic-model/setup.md) to create
`TrustedBusinessMetrics` from the Gold tables.

## 13. Add relationships

As listed in [relationships.md](../fabric/semantic-model/relationships.md): both facts join
`gold_dim_date`, `gold_dim_region` and `gold_dim_category` many-to-one, single direction.

## 14. Add DAX measures

Paste each measure from [measures.dax](../fabric/semantic-model/measures.dax) with **New
measure** [Nuova misura] and apply the documented formats.

## 15. Validate the final answer

Filter Ontario and `2026-08`. The measures must match the table in
[fabric/README.md](../fabric/README.md#expected-results) and the local application. The
`Largest Negative Category` measure returns `Devices`, and `Data Product Status` returns `READY`.

## 16. Reset before the talk

Run `RefreshEnterpriseData` with `scenario_mode = broken` (the failed run is expected). Confirm
`platform_health.sql` shows `BLOCKED` and `governed_answer.sql` returns no rows. Refresh any
open report. During the live demo, run the pipeline with `repaired`.

## Optional: read Fabric from the local app

The local app can read the SQL analytics endpoint read-only:

1. Install the ODBC Driver 18 for SQL Server and `pip install -e ".[fabric]"`.
2. Copy the endpoint's **SQL connection string** (server name) from its settings.
3. Set `DEMO_BACKEND=fabric`, `FABRIC_SQL_SERVER=<server>`, `FABRIC_SQL_DATABASE=AIPlatform`,
   `FABRIC_USER=<your Entra sign-in>` in `.env` (never committed). No password is stored;
   Microsoft Entra interactive sign-in opens a browser window.
4. In Fabric mode, the reset and pipeline buttons are disabled: run the pipeline in Fabric.
   If the connection fails, the app shows the error and offers **Switch to DuckDB**.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Path does not exist: Files/data/...` | Default Lakehouse not attached, or files not under `Files/data/` |
| `Table or view not found: bronze_orders` in SQL endpoint | Wait for metadata sync, refresh the explorer |
| Pipeline does not pass the mode | The notebook's first code cell must be the parameters cell |
| Old numbers in a report | Refresh the report after the notebook run |
