# Architecture decisions

Short ADR-style records for the choices behind this repository.

## ADR-1: Use a free Microsoft Fabric Trial workspace

**Context.** The talk is about Microsoft data platforms, and attendees should be able to
reproduce the demo without a budget. **Decision.** Target a Fabric Trial with Lakehouse,
notebooks, pipelines, SQL analytics endpoint, semantic model and Monitor only. **Consequences.**
No paid capacity, Azure subscription or premium-only feature is assumed. Fabric Git integration
is unavailable in the tenant, so assets are portable files imported by hand and GitHub remains
the source of truth.

## ADR-2: Exclude Fabric Data Agent, Copilot and AI Functions

**Context.** These features are not available on every Trial or tenant, and they would make the
talk about a product feature instead of platform design. **Decision.** No Fabric AI feature and no
external model API is required. **Consequences.** The demo works everywhere, and the point stays
clear: reliability is decided before any AI component runs.

## ADR-3: Provide a DuckDB replica as the conference fallback

**Context.** Conference Wi-Fi, tenant sign-in and capacity start-up are live-demo risks.
**Decision.** Reproduce the same transforms locally with DuckDB, executing the same SQL
statements as the Fabric notebook (a test enforces equality). **Consequences.** The whole story
runs offline in seconds. DuckDB is a replica of the logic, not a claim of Fabric parity for
Spark or Delta behaviour.

## ADR-4: The model never calculates metrics

**Context.** Financial figures must be reproducible and auditable. **Decision.** Every number is
computed by SQL in Gold or by deterministic code over query results. A narrator receives
computed JSON facts; Ollama output containing numbers absent from the facts is rejected.
**Consequences.** The answer can be reproduced without any LLM. Removing the model changes the
wording, not the result.

## ADR-5: Quality gating is deterministic code, not a prompt

**Context.** A prompt instruction ("do not answer if data is stale") is advisory and untestable.
**Decision.** Health is computed by contract-driven checks, stored in
`gold_data_product_health`, and enforced in `governed_path` *and* in the governed SQL.
**Consequences.** Refusal is testable (including bypass attempts) and identical across local
and Fabric backends. The model is not consulted when the product is unhealthy.

## ADR-6: Semantic definitions live outside prompts

**Context.** Metric definitions embedded in prompts drift, fork and cannot be governed.
**Decision.** `net_revenue_cad` is defined in `contracts/net_revenue.metric.yml`, calculated in
`gold_fact_sales` and aggregated by DAX measures. **Consequences.** One definition serves BI,
SQL and AI consumers, and changing it is a versioned contract change with an owner.

## ADR-7: The demo is synthetic

**Context.** Real data would be confidential and unverifiable by attendees. **Decision.** A
seeded generator creates a production-inspired scenario and fails if the narrative invariants
do not hold. **Consequences.** Byte-for-byte reproducibility and no confidentiality risk. The
figures are illustrative, not benchmarks, and the scenario does not represent a real customer
deployment.

## ADR-8: Keep the Fabric pipeline deliberately small

**Context.** The architecture, not orchestration complexity, is the subject. **Decision.**
`RefreshEnterpriseData` has one Notebook activity with one parameter. Failure is signalled by
the notebook raising when the product is not READY. **Consequences.** It can be built by hand in
minutes and explained on one slide. Alerting, retries with backoff and multi-stage
orchestration are documented as production extensions.
