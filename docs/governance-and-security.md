# Governance and security

This page separates **what the free demo implements** from **production patterns it points
to**. The demo does not claim to implement every control listed here.

| Control | In this demo | Production pattern |
| --- | --- | --- |
| Metric ownership and approval | `owner_role`, `status: approved`, version in YAML | Contract changes reviewed by the metric owner (pull request with a required reviewer) |
| Semantic definitions | One metric contract + Gold + DAX | Certified semantic model; endorsement in Fabric |
| Read-only analytics access | Fabric backend accepts only SELECT/WITH, `ApplicationIntent=ReadOnly` | Viewer-only workspace role or SQL endpoint permissions for the app identity |
| Separation of raw and governed access | Raw and governed paths are separate code and SQL | Raw layers not exposed to AI/BI consumers at all; separate workspaces or schemas |
| Least privilege | Source DDL shows a SELECT-only extraction identity (commented) | Managed identities, SELECT on specific objects, no shared accounts |
| Row-level security | Not implemented | RLS in the semantic model or SQL endpoint, enforced by identity, *below* the prompt |
| Data classification | `security_classification` in each contract | Sensitivity labels; Purview classification (optional extension, not configured here) |
| Auditability | Run id on every Gold row and answer; quality results per run | Central log retention; audit of who asked what, and which run answered |
| Dev/prod separation | One Trial workspace named `-Dev` | Separate dev/test/prod workspaces and capacities; deployment pipelines; promoted contracts |
| Secrets | None stored; `.env` gitignored; Entra interactive sign-in | Key Vault, workload identities, no secrets in notebooks |
| Synthetic data | All data generated from a seed | Production data never used in demos or development without approval |

## Why prompt instructions are not a security boundary

A system prompt that says "only show Ontario data to Ontario managers" or "do not answer from
stale data" is text the model may ignore, misread or be talked out of. It cannot be tested
exhaustively, and it runs *after* the data has already been retrieved. Security and
correctness controls must sit where they can be enforced and audited:

* **Access**: identity-based permissions and row-level security in the data platform, so
  the application cannot retrieve rows the user may not see.
* **Correctness**: health gates in data-access code and SQL, so unhealthy data is never
  served.
* **Definition**: metric contracts and semantic models, so the model cannot redefine a metric.

The model's job is language. The platform's job is truth and access.

## Metric ownership workflow (recommended)

1. The metric owner (FP&A) approves the definition and version in `net_revenue.metric.yml`.
2. Data platform engineering implements it once in Gold and in the semantic model.
3. Any change is a new contract version, reviewed, tested, and recorded on every run.
4. Consumers, including AI applications, reference the metric by name and version.
