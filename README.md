# Why AI Projects Fail: Data Platform Lessons Every Architect Should Know

Companion repository and executable demonstration for the Day of Data Toronto 2026 session.

Many AI initiatives fail long before the language model becomes the problem. Poor data quality,
weak governance, fragmented estates and unreliable pipelines make enterprise AI unreliable,
expensive and hard to maintain. This repository shows that relationship with a small, runnable
data platform: SQL Server and Azure SQL sources, a Microsoft Fabric-style medallion Lakehouse,
data contracts, quality gates, observability, a semantic model and an AI application that is
**allowed to refuse**.

> **The model did not hallucinate. The platform gave it the wrong truth.**
>
> A trustworthy AI system must be allowed to refuse an answer when its data product is unhealthy.
>
> Production AI does not begin with a prompt. It begins with a trustworthy data contract.

## Session

| | |
| --- | --- |
| Event | Day of Data Toronto 2026 |
| Date | Saturday, 26 September 2026 |
| Time | 3:00 PM–3:50 PM Eastern Daylight Time (50 minutes) |
| Room | Room B |
| Level | Intermediate |
| Audience | Data architects, DBAs, data engineers, backend and analytics engineers, technical decision-makers |
| Speaker | Daniele Mario Areddu, Backend & AI Developer at Global Technologies Italia and Computer Science student at the University of Calabria |

> **Synthetic data.** A synthetic, production-inspired architecture scenario. It does not
> represent a real customer deployment. All data is generated from a fixed seed; the CSV files
> are synthetic extracts that *represent* an Azure SQL orders system and an on-premises SQL
> Server returns system. No real customer, employer or personal data is used, and no figure
> here is a production benchmark.

## The demo: AI Reliability Lab

One business question, asked three times:

> *Did Ontario beat its August 2026 revenue target, and which product category drove the result?*

| Act | What happens | Outcome (computed from the records) |
| --- | --- | --- |
| 1. Confidently wrong | The raw path sums raw rows: the replayed duplicate, USD summed as CAD, no returns, no health check | "Yes, Ontario beat the target; Devices drove it" |
| 2. Fail closed | The governed path checks data-product health first: stale returns feed, missing FX rates, an orphan return | **Refusal**, enforced in data-access code |
| 3. Trusted answer | The governed pipeline ingests repaired extracts, deduplicates, converts FX on the transaction date, reconciles returns and publishes Gold | "No, Ontario missed the target; Devices was the largest negative contributor" |

Same question. Same presentation layer. Different data contract. Nothing in the application
hardcodes an amount, a percentage, a category or a conclusion. The generator makes the narrative
mathematically true (`naive raw > target > governed`), and both paths recompute it from the data.

## Architecture overview

```text
Azure SQL Orders (synthetic CDC extract) ─┐
SQL Server Returns (synthetic extract)  ──┼─► Bronze ─► Silver ─► Quality gates ─► Gold ─► Semantic contract ─► AI application
Treasury FX + reference data            ──┘  as        dedup,     BLOCKING /        star     Net Revenue CAD       answers only
                                             received   FX, recon, WARNING           schema   (YAML + DAX)          when READY
                                                        quarantine                   + health + run records
```

* **Contracts** (`contracts/*.yml`) define sources, the `net_revenue_cad` metric, freshness
  SLAs (4 hours for returns) and blocking versus warning checks.
* **Medallion transforms** (`src/ai_reliability_lab/medallion.py`) are plain SQL that runs
  unchanged on DuckDB locally and on Spark in the Fabric notebook.
* **Quality gates** (`quality.py`) decide `READY` or `BLOCKED`. Gold facts are published only
  when every blocking check passes.
* **Observability**: every run writes `gold_pipeline_runs` and `gold_data_product_health`.
* **Governed path** (`governed_path.py`): `if health.status != "READY": refuse`. The governed SQL
  enforces the same gate, so application code cannot bypass it.
* **Narration**: deterministic templates by default; optional local Ollama restates validated
  JSON facts only and never calculates, queries or decides.

Details: [architecture/](architecture/) and [docs/architecture-decisions.md](docs/architecture-decisions.md).

## Quickstart (offline)

Requires Python 3.12. No internet connection is needed after installation, and no Fabric,
Azure or LLM account is required.

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
python scripts/generate_demo_data.py --check
python scripts/verify_demo.py
streamlit run app/streamlit_app.py
```

Bash:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python scripts/generate_demo_data.py --check
python scripts/verify_demo.py
streamlit run app/streamlit_app.py
```

`python scripts/generate_demo_data.py` (without `--check`) regenerates `sample-data/` byte for
byte (seed `20260926`, fixed demo clock `2026-09-26T18:00:00Z`). A command-line rehearsal is
available as `ai-reliability-lab demo`.

In the app, press in order: **Reset Broken Scenario** → **Ask Raw System** → **Inspect Platform
Health** → **Ask Governed System** (refusal) → **Run Governed Pipeline** → **Ask Governed System**
(trusted answer). The full stage sequence is in [demo/DEMO_RUNBOOK.md](demo/DEMO_RUNBOOK.md).

Configuration is environment-only; copy `.env.example` to `.env` if you need to change it.
`.env` is gitignored.

| Variable | Default | Options |
| --- | --- | --- |
| `DEMO_BACKEND` | `duckdb` | `duckdb` (offline), `fabric` (read-only SQL analytics endpoint) |
| `NARRATOR` | `deterministic` | `deterministic` (no LLM), `ollama` (local, optional) |
| `DEMO_STATE_DIR` | `.demo-state` | runtime DuckDB location (gitignored) |

## Microsoft Fabric (free Trial, manual import)

GitHub is the source of truth; Fabric is the execution environment. Native Fabric Git
integration is not used, and no Fabric item IDs or `.platform` files exist in this repository.

1. `python scripts/package_fabric_upload.py` → `dist/fabric-upload/`.
2. Upload `data/` to Lakehouse `AIPlatform` under `Files/data`.
3. Import `BuildTrustedLayer.ipynb`, attach the Lakehouse and run it in `broken` mode (ends with
   an intentional error).
4. Create pipeline `RefreshEnterpriseData` (one Notebook activity) and run it in `repaired` mode.
5. Query the SQL analytics endpoint with `fabric/sql/*.sql` and build the
   `TrustedBusinessMetrics` semantic model from `fabric/semantic-model/`.

Full guide: [docs/fabric-setup.md](docs/fabric-setup.md). Asset overview and expected results:
[fabric/README.md](fabric/README.md).

## Repository structure

```text
app/streamlit_app.py            conference UI (displays results; no business logic)
src/ai_reliability_lab/         generator, contracts, medallion SQL, quality gates, pipeline,
                                raw and governed paths, observability, narration, backends, CLI
sample-data/                    committed synthetic extracts (azure-sql, sql-server, reference)
source-contracts/               T-SQL DDL for the represented Azure SQL and SQL Server sources
contracts/                      YAML data contracts and the Net Revenue metric definition
fabric/                         notebook, SQL endpoint queries, semantic model, pipeline guide
architecture/                   unreliable vs trusted platform, lineage
docs/                           failure modes, ADRs, governance, checklist, setup guides
demo/                           runbook, speaker script, reset checklist, failure fallback
scripts/                        generate data, verify demo, build notebook, package, repo scan
tests/                          pytest suite (data, paths, contracts, app, Fabric assets, docs)
slides/                         where the final deck belongs
```

## Testing and quality gates

```bash
ruff format --check .
ruff check .
pytest
python scripts/verify_demo.py
python scripts/build_fabric_notebook.py --check
python scripts/scan_repository.py
```

The suite covers dataset invariants, raw-path flaws, fail-closed behaviour (including attempts
to bypass the gate), deterministic deduplication, transaction-date FX, contract enforcement,
run records, the Streamlit app (via `streamlit.testing`), and Fabric assets. The real notebook
source is executed end to end against a DuckDB-backed Spark stand-in and must match the local
pipeline row for row. GitHub Actions runs all of it on pushes and pull requests to `develop`
and `main` ([.github/workflows/ci.yml](.github/workflows/ci.yml)).

## Limitations

* Synthetic data only. Sources are CSV extracts *representing* Azure SQL and SQL Server; there
  are no live database connections, CDC or replication jobs.
* DuckDB mode is a local replica of the Lakehouse logic, not Fabric. Spark- and Delta-specific
  behaviour is validated only by running the notebook in Fabric; CI runs the notebook against a
  stand-in that checks control flow and SQL, not Spark semantics.
* The deterministic narrator is string templates, not AI. Ollama narration is optional, local
  and restricted to rewording validated facts.
* Governance controls such as row-level security, Purview, alerting and environment separation
  are *described* as production patterns ([docs/governance-and-security.md](docs/governance-and-security.md)),
  not implemented in the free demo.
* Reporting months use UTC calendar dates; a production platform would use a governed business
  calendar and time zone.
* The optional Fabric backend needs the Microsoft ODBC Driver 18, `pyodbc` and interactive
  Microsoft Entra sign-in; it has been designed and unit-tested for failure handling only.

## Speaker

**Daniele Mario Areddu**: Backend & AI Developer at Global Technologies Italia and Computer
Science student at the University of Calabria. The scenario is a teaching construct inspired by
common enterprise patterns; it is not a description of any system operated by the speaker or
the speaker's employer.
