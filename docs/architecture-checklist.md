# Architecture checklist for production AI on enterprise data

A reusable checklist for architects, DBAs and data engineers. Each item names the smallest
evidence that proves it, and where this repository shows an example.

| # | Question | Evidence that it is true | Example here |
| --- | --- | --- | --- |
| 1 | Are business metrics formally defined? | A versioned definition with an owner, grain, formula and currency | `contracts/net_revenue.metric.yml` |
| 2 | Does every AI answer expose freshness? | Answer shows refresh time and source age against an SLA | Governed answer, Platform Health tab |
| 3 | Can the system detect unhealthy data? | Automated checks with blocking vs warning severity | `data_product_health.contract.yml`, `quality.py` |
| 4 | Can it refuse to answer? | A code path that returns a refusal with reasons, tested | `governed_path.py`, `test_governed_path.py` |
| 5 | Is lineage available? | Source systems and run id on every served row | `gold_fact_sales` lineage columns |
| 6 | Are source identities preserved? | Source system, event id and source timestamps kept through Gold | Bronze metadata columns |
| 7 | Are pipeline retries idempotent? | Rerunning a load gives the same result | Reset/repair tests, notebook rerun test |
| 8 | Are duplicates detected? | Business-key uniqueness check and an explicit dedup policy | `DUPLICATES_RESOLVED`, `DUPLICATE_BUSINESS_KEYS` |
| 9 | Are semantic definitions centrally governed? | One definition shared by BI, SQL and AI | Gold + DAX + contract |
| 10 | Is access enforced below the prompt layer? | Permissions/RLS in the platform, read-only app identity | Read-only backend guard; RLS as production pattern |
| 11 | Can the answer be reproduced without the LLM? | Same figures from SQL alone | `governed_answer.sql`, deterministic narrator |
| 12 | Are model, data and application failures separately observable? | Distinct statuses and logs | `BLOCKED` vs `FAILED` vs narration fallback |

## Quick self-assessment

Score 1 point per item you can *demonstrate today* with evidence, not intent.

* **10–12**: the platform is ready to host AI answers; focus on operations.
* **6–9**: pilot only, with a human in the loop and visible freshness.
* **0–5**: fix the data product first. A better model will not help.

> Production AI does not begin with a prompt. It begins with a trustworthy data contract.
