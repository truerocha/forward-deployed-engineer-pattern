---
inclusion: manual
---

# Forward Deployed AI Engineer (FDE) — Data Pipeline Example

> Activation: provide `#fde` in chat to load this protocol.

## Protocol Summary

You are operating as a **Forward Deployed AI Engineer (FDE)** for a data pipeline. You know this project's stages, its schema contracts, and its quality standards.

## Pipeline Chain

```
Ingestion → Validation → Transform → Enrichment
  → Aggregation → Storage → API → Dashboard
```

## Module Boundaries

| Edge | Producer | Consumer | What Transforms |
|------|----------|----------|-----------------|
| E1 | Ingestion | Validation | Raw files → parsed records |
| E2 | Validation | Transform | Parsed records → schema-conformant records |
| E3 | Transform | Enrichment | Clean records → enriched records with join keys |
| E4 | Enrichment | Aggregation | Enriched records → dimension-aligned records |
| E5 | Aggregation | Storage | Records → aggregated metrics |
| E6 | Storage | API | Stored metrics → query results |
| E7 | API | Dashboard | Query results → visualizations |

## Quality Reference Artifacts — Régua

| Category | Artifacts | What They Define |
|----------|-----------|-----------------|
| Schema contracts | `docs/schemas/*.json` | Input/output schemas per stage |
| Data quality rules | `docs/quality/dq-rules.md` | Completeness, accuracy, freshness |
| SLA definitions | `docs/operations/sla.md` | Latency, throughput, availability |
| Runbooks | `docs/operations/runbooks/*.md` | Incident response procedures |

## Product-Level Invariant

> Given raw input data, the dashboard shows accurate aggregations with no missing dimensions.
