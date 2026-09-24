# Failure modes: why AI answers go wrong on healthy-looking platforms

Each failure mode below appears in the AI Reliability Lab and has a platform-level control.
None of them is fixed by a better model or a better prompt.

## 1. Valid query over invalid data

The raw query parses, runs and returns a precise number. Its correctness depends on
assumptions (unique keys, one currency, complete feeds) that nobody checks. **Control:** data
contracts that state those assumptions and quality gates that test them on every run.

## 2. Stale pipelines

The returns replication job stopped 60 hours before the question was asked. The table still
exists and still has rows, so every downstream query "works". **Control:** a freshness SLA per
feed (4 hours for returns), measured from ingestion metadata and treated as blocking.

## 3. Duplicate events

A retried CDC batch replayed one large order. At-least-once delivery is normal; treating it as
exactly-once is the bug. **Control:** an explicit, deterministic deduplication policy on the
business key (highest `event_version`, then `source_updated_at`), with discarded rows recorded,
plus a blocking check that no business key survives Silver twice.

## 4. Missing reference data

USD→CAD rates are missing for two days. The naive query sidesteps the problem by never
converting at all. A "helpful" pipeline might use the nearest rate, which silently changes a
financial figure. **Control:** transaction-date FX coverage as a blocking check with no
implicit fallback; the fix belongs to the reference-data owner.

## 5. Semantic ambiguity

"Revenue" could mean gross, net of returns, booked, recognised, in local currency or in CAD.
Leaving the choice to a query author, or to a model, gives different answers to the same
question. **Control:** one approved metric definition (`contracts/net_revenue.metric.yml`),
calculated once in Gold and exposed through a semantic model.

## 6. Absent lineage

Without source identities and run ids, nobody can explain where a number came from, and
nobody can prove it changed after a fix. **Control:** lineage columns on every Gold row and a
run id on every answer.

## 7. No refusal behaviour

A system that must always answer will answer from broken data. **Control:** a deterministic
health gate in data-access code: `if status != "READY": refuse`, with the reasons shown. The
refusal is a product feature with an owner, not an error page.

## 8. Model blame versus platform root cause

When the answer is wrong, the model is the visible component, so it gets the blame. In this
demo the narrator (deterministic *or* LLM) reports exactly what the data said. The root causes
were a replayed event, a stalled job, a reference-data gap, a key-format mismatch and an
undefined metric. **Control:** separate observability for model, data and platform failures
(`narration rejected`, `BLOCKED`, `FAILED`) so incidents are routed to the team that can fix them.

> The model did not hallucinate. The platform gave it the wrong truth.
