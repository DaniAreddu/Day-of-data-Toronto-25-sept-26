# RefreshEnterpriseData: manual pipeline setup

Native Fabric Git integration is not available in the target tenant, so no pipeline definition
JSON is shipped (inventing one would mean fabricating Fabric item identifiers). The pipeline is
deliberately tiny, one Notebook activity, and takes about two minutes to create by hand.

UI labels are in English; likely Italian equivalents are in brackets.

## 1. Create the pipeline

1. In workspace `DayOfDataToronto-Dev`, select **New item** [Nuovo elemento] → **Pipeline**
   (older UI: **Data pipeline** [Pipeline di dati]).
2. Name it `RefreshEnterpriseData` and select **Create** [Crea].

## 2. Add a pipeline parameter

1. Click the empty canvas, open the **Parameters** [Parametri] tab below it.
2. **New** [Nuovo]: name `scenario_mode`, type `String`, default value `repaired`.

## 3. Add the Notebook activity

1. On the **Activities** [Attività] tab select **Notebook**.
2. **General** [Generale] tab: name it `BuildTrustedLayer`; set **Timeout** to `0.00:30:00`;
   **Retry** [Nuovo tentativo] `0` (the notebook is idempotent, but a visible failure is the
   point of the demo).
3. **Settings** [Impostazioni] tab: **Workspace** `DayOfDataToronto-Dev`, **Notebook**
   `BuildTrustedLayer`.

## 4. Pass `scenario_mode`

In **Settings** → **Base parameters** [Parametri di base] → **New** [Nuovo]:

| Name            | Type   | Value                                  |
| --------------- | ------ | -------------------------------------- |
| `scenario_mode` | String | `@pipeline().parameters.scenario_mode` |

(Use **Add dynamic content** [Aggiungi contenuto dinamico] for the expression.) The notebook's
first code cell must be marked as the parameters cell; the imported notebook already carries
the `parameters` tag. Verify with **Toggle parameter cell** [Attiva/disattiva cella di
parametri] in the notebook if in doubt.

## 5. Failure behaviour

No extra configuration is required. When the data product is not READY the notebook raises
`RuntimeError: Data product net_revenue_cad is BLOCKED ...` as its last step, so the Notebook
activity, and therefore the pipeline run, is marked **Failed** with the blocking reasons in the
error message. Health and run tables are written *before* the error is raised.

Keep the pipeline to this single activity for the live demo. Alert or email activities on the
failure path are a production extension (see `architecture/trusted-platform.md`).

## 6. Run

1. **Save** [Salva], then **Run** [Esegui].
2. Accept the default `scenario_mode = repaired` (or type `broken` to reset).

## 7. Open run history

* In the pipeline: **Run** → **View run history** [Visualizza cronologia esecuzioni], or the
  **Output** [Output] tab under the canvas for the current run.
* Workspace-wide: the **Monitor** [Monitoraggio] hub lists every pipeline and notebook run.
* Select the Notebook activity's output to open the notebook snapshot with printed summaries.

## 8. Reset the demo

Run `RefreshEnterpriseData` with `scenario_mode = broken`. **The run is expected to fail**:
that failed run is the evidence for Act 2. Afterwards:

* `gold_data_product_health.status` = `BLOCKED`;
* `gold_fact_sales` and `gold_fact_targets` are empty (publication withheld);
* `gold_pipeline_runs` contains only the new broken run (history is reset in broken mode).

## 9. Verify the Gold layer

Open the Lakehouse **SQL analytics endpoint** and run, in order:

1. `fabric/sql/platform_health.sql` → one row, status `READY` after a repaired run;
2. `fabric/sql/governed_answer.sql` → one row with Net Revenue CAD below target;
3. `fabric/sql/category_variance.sql` → Devices first (most negative variance);
4. `fabric/sql/pipeline_evidence.sql` → the broken run (BLOCKED) and repaired run (READY).

Compare with the expected results in [../README.md](../README.md#expected-results).
