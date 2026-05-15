# ADR-035: Self-Hosted Code Intelligence MCP — Zero Egress

> **Status**: Accepted
> **Date**: 2026-05-15
> **Author**: Staff SWE (rocand) + Kiro FDE Protocol
> **Supersedes**: ADR-034 Feature 2 (external MCP dependency)
> **Related**: ADR-034, ADR-016 (Data Residency), ADR-015 (Repo Onboarding)

## Context

ADR-034 Feature 2 specified adding a code-intelligence MCP server for FDE
Phase 1 reconnaissance. The initial implementation pointed to an external
tool (npm package). Analysis revealed this creates:

1. **Data egress risk**: Customer source code sent to external process
2. **Supply chain vulnerability**: npm dependency with unknown update cadence
3. **Availability dependency**: External tool availability affects FDE pipeline
4. **Trust boundary violation**: Customer cannot audit what happens to their code

The project already has 80% of the required capability built in:
- Tree-sitter parsing (Repo Onboarding Agent)
- Call graph extraction (incremental_indexer.py)
- Vector embeddings (VectorStore)
- Semantic search (query_code_kb tool with 5 modes)
- Persistence (SQLite catalogs on S3)

## Decision

Build a self-hosted MCP server that wraps the existing `query_code_kb` tool.
Zero external dependencies. Zero data egress. Runs entirely within the
customer's compute boundary (local process or ECS Fargate).

## Security Properties

| Property | Guarantee |
|----------|-----------|
| Data residency | Code never leaves the customer's AWS account or local machine |
| No network calls | MCP server uses stdio transport — no HTTP, no sockets |
| No npm dependencies | Pure Python, uses only stdlib + boto3 (already in environment) |
| Auditable | ~200 LOC, single file, customer can read every line |
| No telemetry | Zero metrics, logs, or callbacks to external services |
| Catalog isolation | Each repo's catalog is scoped to its own S3 prefix |

## WAF Alignment

- **SEC 7** (Data classification): Source code classified as confidential — never egresses
- **SEC 9** (Data protection in transit): stdio transport — no network transit
- **SEC 6** (Protect compute): Runs in same process as Kiro — no additional attack surface
- **REL 2** (Reduce blast radius): Self-contained — failure doesn't affect other systems
- **COST 1** (Practice cloud financial management): Zero additional cost — reuses existing catalog

## Architecture

```
Kiro IDE (stdio) → code_intelligence_mcp.py → query_code_kb() → SQLite catalog
                                                                    ↓
                                                              (local file or S3)
```

No network. No external process. No data leaves the boundary.

## Alternatives Considered

| Option | Rejected Because |
|--------|-----------------|
| External npm tool | Data egress, supply chain risk, availability dependency |
| Centrally-hosted SaaS | Code sent to shared service, customer loses control |
| Browser-based WASM | Limited to small repos, no persistence |

## Consequences

- FDE Phase 1 reconnaissance uses local catalog — fast, offline-capable
- Customer code never leaves their machine or AWS account
- MCP server is a thin wrapper (~200 LOC) — easy to audit and maintain
- Catalog must be refreshed when code changes (handled by staleness hook)
