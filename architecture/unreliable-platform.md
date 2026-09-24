# The unreliable platform (Act 1)

What the "confidently wrong" answer is built on. Every step below *works*: no query fails, no
job crashes, no alert fires.

```text
Azure SQL orders (CDC extract) ──┐
                                 ├──► raw landing tables ──► ad-hoc SQL ──► LLM / app ──► "Yes, Ontario beat target"
SQL Server returns (stale)  ─ ─ ─┘         (bronze_*)        SUM(gross)       no checks
FX rates (gap)              ─ ─ ─ ─ ─ ─ ─ (never joined)
```

## What is wrong, and why nothing notices

| Defect in the estate | Effect on the answer | Why it is invisible |
| --- | --- | --- |
| A retried CDC batch replayed one large Devices order | Revenue counted twice | Same `order_id`; nothing enforces a business key on landing tables |
| Returns replication stopped 60 hours ago | Returns are missing (and ignored anyway) | The table exists and has rows; only freshness metadata would reveal it |
| One return uses a legacy order-key format | Orphan return | Returns and orders live in different systems; no cross-system foreign key |
| USD→CAD rates missing for two days | USD amounts summed as if CAD | The raw query never joins FX at all |
| `revenue` has no approved definition | Gross, net, booked or recognised? | The column name *sounds* authoritative |
| No health gate | The system answers from any state | Nothing asks "should I answer?" |

## The raw query

`fabric/sql/raw_answer.sql`: valid SQL, valid arithmetic. It reads `bronze_orders` directly,
calls `SUM(gross_amount)` "revenue", and compares it with the approved target. The model (or
the deterministic narrator) then faithfully reports a precise, confident, wrong number.

> The SQL is valid. The arithmetic is valid. The answer is wrong because the data contract is
> wrong.

## Why "better prompting" cannot fix this

A prompt cannot deduplicate events it never sees, cannot convert currency without rates, cannot
know a feed is stale without freshness metadata, and cannot decide what "revenue" means. These
are platform properties. See [trusted-platform.md](trusted-platform.md).
