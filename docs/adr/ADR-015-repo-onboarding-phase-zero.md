# ADR-015: Repo Onboarding Agent — Phase 0 Codebase Reasoning

## Status
Accepted

## Date
2026-05-06

## Context

Deploying the FDE into a new project requires manual customization of the steering file: pipeline chain, module boundaries, quality artifacts, tech stack tags, and engineering level patterns. This manual process is:

1. **Time-consuming** — 30+ minutes per project to map module boundaries and pipeline chains
2. **Error-prone** — humans miss import relationships and misclassify module types
3. **Static** — steering doesn't update as the codebase evolves
4. **Not scalable** — each new project needs a human to configure before the FDE can operate

The factory needs to self-configure from the codebase itself. This is the "Phase 0" that runs before the existing FDE intake pipeline (Phase 2) for any project.

### Design Space Explored

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| Full LLM analysis (send source code) | High accuracy | Expensive ($1-5/run), slow, token limits | Rejected |
| Static analysis only (no LLM) | Cheap, fast | Cannot infer pipeline chains or boundaries | Rejected |
| Hybrid: deterministic scan + lightweight LLM | Cost-controlled ($0.01/run), accurate structure | Requires two-pass architecture | **Selected** |
| Language server protocol (LSP) | Rich type info | Requires running language servers, heavy | Rejected |

### Key Constraints

- **Cost ceiling**: $0.01 per onboarding run (Haiku pricing: $0.25/MTok input, $1.25/MTok output)
- **Time budget**: 5 minutes for repos up to 100K files on 1 vCPU / 2GB Fargate
- **Security**: ADR-014 fetch-use-discard pattern for all credentials
- **Human gate**: Generated steering is never auto-applied; Staff Engineer approves

## Decision

### Architecture: Sequential Pipeline with Hybrid Analysis

The Repo Onboarding Agent is a 9-stage sequential pipeline:

```
Trigger Handler → Repo Cloner → File Scanner (Magika) → AST Extractor (tree-sitter)
  → Convention Detector → Pattern Inferrer (Haiku) → Catalog Writer (SQLite)
    → Steering Generator → S3 Persister
```

### Key Technology Choices

| Component | Choice | Rationale |
|-----------|--------|-----------|
| File type detection | Google Magika | Content-based (not extension-based), handles polyglot/generated files, no LLM needed, Apache 2.0 |
| AST extraction | tree-sitter | Language-agnostic, fast native parsing, supports 6 target languages (Python, JS/TS, Go, Java, Rust, HCL) |
| Pattern inference | Claude Haiku via Bedrock | Cheapest model ($0.25/MTok), structured input only (never raw code), 8K token limit |
| Catalog format | SQLite | Lightweight, portable, queryable, single-file artifact, no server needed |
| Persistence | S3 (versioned bucket) | Existing infrastructure, versioning via bucket policy, no new services |

### Execution Modes

1. **Cloud mode** (REPO_URL provided): EventBridge trigger → ECS Fargate task → clone → scan → S3 artifacts
2. **Local mode** (no REPO_URL): Kiro hook trigger → scan cwd → local catalog.db + steering draft
3. **Incremental re-scan**: Compare commit SHA → delta scan only changed files → update catalog

### Catalog Schema (9 tables)

`repos`, `files`, `modules`, `dependencies`, `conventions`, `pipeline_chain`, `module_boundaries`, `tech_stack`, `level_patterns`

### Integration with FDE Intake (Phase 2)

The catalog provides three query functions consumed by the existing intake pipeline:
- `get_tech_stack()` → populates data contract `tech_stack` field
- `get_suggested_level()` → dynamic engineering level from task labels
- `get_module_context()` → module boundaries for constraint extractor

### Human Approval Gate

Generated steering is written to a staging location:
- Cloud: `s3://bucket/catalogs/{owner}/{repo}/steering-draft.md`
- Local: `.kiro/steering/fde-draft.md`

The Staff Engineer reviews and copies to `.kiro/steering/fde.md` to activate. No auto-apply.

## Consequences

### Positive
- New projects can be onboarded in under 5 minutes (vs 30+ minutes manual)
- Steering stays current via incremental re-scan on code changes
- Dynamic engineering level assignment reduces mis-classification
- Cost is negligible ($0.01/run vs $3-5 for full LLM analysis)
- Existing infrastructure reused (ECS cluster, S3 bucket, Secrets Manager)

### Negative
- New ECS task definition and ECR repository to maintain
- tree-sitter grammar coverage limited to 6 languages (exotic languages unsupported)
- Pattern inference quality depends on Haiku's ability to reason about dependency graphs
- SQLite catalog adds a new artifact to manage (versioning, cleanup)

### Risks
- Haiku may produce inaccurate pipeline chains for complex architectures → mitigated by human approval gate
- Large monorepos (>500K files) require sampling → acceptable per requirements
- tree-sitter parse errors for non-standard syntax → graceful degradation (skip unparseable files)

## Related

- **ADR-009** — AWS Cloud Infrastructure (ECS cluster, S3 bucket reused)
- **ADR-010** — Data Contract Task Input (catalog populates data contract fields)
- **ADR-013** — Enterprise-Grade Autonomy (dynamic level assignment from catalog)
- **ADR-014** — Secret Isolation (fetch-use-discard for clone credentials)
- **Requirements** — `.kiro/specs/repo-onboarding-agent/requirements.md`
- **Design** — `.kiro/specs/repo-onboarding-agent/design.md`
- **Implementation** — `infra/docker/agents/onboarding/` (13 modules)
