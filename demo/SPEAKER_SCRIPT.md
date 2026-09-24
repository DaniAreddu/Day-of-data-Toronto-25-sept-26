# Speaker script: how the demo fits the 50-minute session

*Why AI Projects Fail: Data Platform Lessons Every Architect Should Know*.
Saturday, 26 September 2026, 3:00–3:50 PM EDT, Room B. Intermediate. Speaker: Daniele Mario
Areddu.

The talk is about data platforms, not prompt engineering, RAG or chatbots. The AI application
is deliberately thin; the platform is the subject.

## Timing

```text
00–05  Opening and confidently wrong answer
05–12  Why models get blamed for platform failures
12–20  Failure modes in enterprise data estates
20–28  SQL Server, Azure SQL and Fabric architecture
28–38  Live AI Reliability Lab demonstration
38–45  Governance, observability and semantic contracts
45–50  Practical checklist and Q&A
```

The demo must not run longer than 10–12 minutes. If it runs long, cut the Fabric Monitor hub
visit, not the refusal.

## 00–05 Opening

Show a screenshot of the Act 1 answer on a slide, with no explanation yet. Ask the room: "Would
you send this to your CFO?" Most will say yes; that is the point. State the synthetic-scenario
disclaimer.

## 05–12 Why models get blamed

The visible component takes the blame. Walk through an incident timeline where the post-mortem
says "the AI was wrong" and the root cause is a stalled job. Introduce the thesis:

> The model did not hallucinate. The platform gave it the wrong truth.

## 12–20 Failure modes

Use [docs/failure-modes.md](../docs/failure-modes.md): valid query over invalid data, stale
pipelines, duplicate events, missing reference data, semantic ambiguity, absent lineage, no
refusal behaviour.

**Transition to architecture:** "Every one of these is a property of the platform. So let's
look at the platform."

## 20–28 Architecture

Use [architecture/trusted-platform.md](../architecture/trusted-platform.md): Azure SQL
operational orders, on-premises SQL Server returns, Fabric Lakehouse medallion layers, quality
gates, Gold star schema, semantic model.

**Transition for DBAs:** "Business keys, referential integrity and freshness are things you
already enforce inside one database. The estate spans two systems, so the platform has to
enforce them across systems. That is the orphan return you are about to see."

**Transition for data engineers:** "At-least-once delivery is normal. The question is whether
your Silver layer has an explicit deduplication policy and records what it discarded."

## 28–38 Live demo

Follow [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) exactly.

## 38–45 Governance, observability and semantic contracts

**Transition to semantic models:** "Act 3 did not ask the model to define revenue. The
definition lives in a contract and in Gold; the semantic model and the AI app both consume it.
One definition, many consumers."

**Transition to production operations:** "Every run leaves a record: status, row counts,
freshness, failure reasons, duration. BLOCKED is a data incident, FAILED is a platform
incident, a rejected narration is a model incident. Three different on-call routes."

**Transition to maintainability:** "The transforms are plain SQL that runs on DuckDB and Spark.
The checks are data. The pipeline is one activity. Boring is maintainable."

Security point: prompt instructions are not a security boundary. Access control and RLS belong
below the prompt layer ([docs/governance-and-security.md](../docs/governance-and-security.md)).

## 45–50 Checklist and Q&A

Show [docs/architecture-checklist.md](../docs/architecture-checklist.md) and give the repository
link. Close with:

> Production AI does not begin with a prompt. It begins with a trustworthy data contract.

## Likely questions

* **"Why not let the LLM check data quality?"** Because checks must be deterministic, testable
  and auditable, and a model cannot inspect metadata it was never given.
* **"Is this a real customer system?"** No. It is a synthetic, production-inspired scenario.
* **"Does this need Fabric Copilot or Data Agent?"** No. Nothing in the demo uses them.
* **"What about Purview?"** An optional production extension for catalogue lineage and
  classification; not configured here.
