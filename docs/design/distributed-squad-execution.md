# Tech Design Document: Distributed Squad Execution

> **Status**: Draft
> **Date**: 2026-05-08
> **Author**: Staff SWE (rocand) + Kiro
> **ADR**: ADR-020 (pending)
> **Replaces**: Monolithic `_execute_squad_pipeline()` in orchestrator.py

---

## Goal of This Doc

1. Align on the problem: the current monolithic execution model cannot support parallel agents, large repos, or extended thinking without resource exhaustion
2. Propose a distributed execution architecture where each agent runs as an independent ECS task
3. Define the SCD persistence layer (DynamoDB), shared workspace (EFS), and orchestrator redesign
4. Identify one-way door decisions and de-risk before implementation

---

## Executive Summary

The Code Factory's squad execution currently runs all agents (5-8) sequentially in a single ECS Fargate task (1 vCPU, 2GB RAM). This monolithic design fails when:
- Parallel agent execution is needed (WAF review group)
- Extended thinking produces 100K+ tokens (OOM risk)
- Target repos exceed 500MB (disk + memory exhaustion)
- Any single agent failure kills the entire pipeline

This document proposes a **distributed execution model** where the orchestrator becomes a lightweight dispatcher and each agent runs as an independent ECS task with its own resources, reading/writing shared state via DynamoDB (SCD) and shared filesystem via EFS.

---

## Problem Statement

### Current State (Monolith)

```
1 ECS Task (1 vCPU, 2GB RAM)
  └─ Python process
       └─ for agent in squad:
            agent(prompt)  ← sequential, same memory space
```

### Problems (numbered, granular)

1. **No parallel execution** — `for agent in stages` is sequential. WAF review group (3 agents) cannot run concurrently.
2. **Shared memory risk** — 8 agents × extended thinking (100K tokens × 4 bytes) = potential 3.2GB in a 2GB container.
3. **Blast radius** — if agent #6 OOM-kills, agents #1-5 work is lost (no checkpoint between agents).
4. **Large repos** — git clone of 500MB repo + checkout + workspace = 1GB+ disk/memory. Combined with agent memory = OOM.
5. **No agent-level retry** — if `swe-developer-agent` fails, the entire pipeline restarts from scratch.
6. **No agent-level observability** — all agents share one CloudWatch log stream. Can't isolate latency per agent.
7. **No agent-level scaling** — can't give `swe-developer-agent` (reasoning tier) more resources than `reporting-agent` (fast tier).

### Customer Impact

- PM: sees "ingested" for 15+ minutes with no granular progress
- Staff SWE: can't debug which agent failed without parsing combined logs
- Users with large repos: tasks fail silently with OOM

---

## Glossary

| Term | Definition |
|------|-----------|
| **SCD** | Shared Context Document — structured state passed between agents |
| **Orchestrator** | Lightweight ECS task that dispatches agent tasks and monitors completion |
| **Agent Task** | Independent ECS task running a single squad agent |
| **Stage** | A group of agents that execute together (sequential within stage, parallel across agents in same stage) |
| **EFS** | Elastic File System — shared POSIX filesystem mounted by all tasks |

---

## Long-Term Vision

Each agent is a **microservice** with:
- Its own ECS task definition (CPU/memory sized to its model tier)
- Its own CloudWatch log stream (agent-level observability)
- Its own retry policy (agent-level resilience)
- Shared state via DynamoDB SCD (not in-memory)
- Shared workspace via EFS (not git clone per agent)

The orchestrator is a **state machine** (potentially Step Functions in the future) that:
- Reads the Squad Manifest
- Dispatches agent tasks per stage
- Waits for completion (poll DynamoDB)
- Handles failures with retry + backoff
- Reports progress to the portal in real-time

---

## Requirements

### Functional Requirements

| Component | No. | Use Case | Priority |
|-----------|-----|----------|----------|
| Orchestrator | F1 | Dispatch N agent tasks per stage (parallel within stage) | P0 |
| Orchestrator | F2 | Wait for all agents in a stage to complete before next stage | P0 |
| Orchestrator | F3 | Retry failed agent tasks with exponential backoff (max 3) | P0 |
| Orchestrator | F4 | Report per-agent progress to DynamoDB (portal visibility) | P0 |
| Agent Task | F5 | Read SCD sections from DynamoDB based on role permissions | P0 |
| Agent Task | F6 | Write output to SCD in DynamoDB after completion | P0 |
| Agent Task | F7 | Access shared workspace via EFS mount (no git clone) | P0 |
| Agent Task | F8 | Use model tier from AGENT_CAPABILITIES (reasoning/standard/fast) | P0 |
| SCD | F9 | DynamoDB table with task_id as PK, section_name as SK | P0 |
| SCD | F10 | Sliding window on read (most recent content, max 12K total input) | P1 |
| Workspace | F11 | EFS filesystem mounted at /workspace in all agent tasks | P0 |
| Workspace | F12 | Orchestrator clones repo to EFS once, agents read/write from it | P0 |
| Portal | F13 | Show per-agent status (pending/running/complete/failed) in real-time | P0 |
| Portal | F14 | Show which model tier each agent is using | P1 |

### Non-Functional Requirements

| Requirement | Target | Rationale |
|-------------|--------|-----------|
| Agent task startup time | <30s | Fargate cold start + EFS mount |
| Parallel agents per stage | Up to 6 (WAF pillar group) | Fargate concurrent task limit per cluster |
| Max repo size supported | 2GB | EFS has no size limit, but clone time matters |
| Agent task timeout | 15min per agent | Extended thinking + tool use |
| Orchestrator memory | 512MB | Only dispatches, no agent execution |
| Agent task memory (reasoning) | 4096MB | Extended thinking with 100K+ tokens |
| Agent task memory (standard) | 2048MB | Standard coding/review |
| Agent task memory (fast) | 1024MB | Structured output only |
| SCD read latency | <50ms | DynamoDB single-digit ms |
| Retry backoff | 30s, 60s, 120s | Exponential with jitter |

---

## Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| Parallel agent execution | 0 (sequential only) | 3-6 agents concurrent |
| Max supported repo size | ~200MB (OOM at 500MB) | 2GB+ |
| Agent failure blast radius | Entire pipeline lost | Only failed agent retried |
| Per-agent observability | Shared log stream | Individual log stream per agent |
| Pipeline latency (8 agents) | ~40min (sequential) | ~15min (parallel stages) |

---

## Assumptions

1. **EFS performance**: EFS General Purpose mode provides sufficient IOPS for git operations (read-heavy after initial clone)
2. **Fargate concurrent tasks**: The cluster can run up to 10 concurrent tasks (current limit, can be increased)
3. **DynamoDB capacity**: On-demand mode handles the SCD read/write pattern without throttling
4. **Agent independence**: Agents within a parallel stage do NOT modify the same files (WAF review agents are read-only)

---

## Out of Scope

- Step Functions orchestration (future evolution — ECS RunTask + DynamoDB polling is sufficient for now)
- Agent-to-agent direct communication (all communication via SCD)
- Multi-region execution
- GPU-based agents

---

## Proposal

### Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  EventBridge                                                         │
│  (webhook → ECS RunTask: orchestrator)                              │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Orchestrator Task (512MB, 0.25 vCPU)                               │
│                                                                     │
│  1. Read Squad Manifest (from task-intake-eval or default)          │
│  2. Clone repo to EFS (once)                                        │
│  3. For each stage in manifest:                                     │
│     a. Dispatch N agent tasks (ECS RunTask)                         │
│     b. Poll DynamoDB for completion (every 10s)                     │
│     c. If agent fails → retry with backoff (max 3)                  │
│     d. If all agents in stage complete → next stage                 │
│  4. Push + Create PR                                                │
│  5. Update portal + ALM                                             │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  Agent Task A    │ │  Agent Task B    │ │  Agent Task C    │
│  (4GB, 1 vCPU)  │ │  (4GB, 1 vCPU)  │ │  (1GB, 0.25 vCPU)│
│                  │ │                  │ │                  │
│  Role: code-sec  │ │  Role: developer │ │  Role: reporting │
│  Model: Sonnet 4 │ │  Model: Sonnet 4 │ │  Model: Haiku    │
│                  │ │                  │ │                  │
│  1. Read SCD     │ │  1. Read SCD     │ │  1. Read SCD     │
│  2. Mount EFS    │ │  2. Mount EFS    │ │  2. Mount EFS    │
│  3. Execute      │ │  3. Execute      │ │  3. Execute      │
│  4. Write SCD    │ │  4. Write SCD    │ │  4. Write SCD    │
│  5. Exit(0)      │ │  5. Exit(0)      │ │  5. Exit(0)      │
└────────┬─────────┘ └────────┬─────────┘ └────────┬─────────┘
         │                    │                    │
         └────────────────────┼────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              │               │               │
              ▼               ▼               ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│  DynamoDB        │ │  EFS             │ │  S3              │
│  (SCD + status)  │ │  (/workspace)    │ │  (full outputs)  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

### Component Details

#### 1. Orchestrator Task Definition

```hcl
resource "aws_ecs_task_definition" "squad_orchestrator" {
  family = "fde-squad-orchestrator"
  cpu    = "256"
  memory = "512"
  # Mounts EFS for git clone
  # Has ECS RunTask permission to dispatch agent tasks
}
```

#### 2. Agent Task Definition (parametrized)

```hcl
resource "aws_ecs_task_definition" "squad_agent" {
  family = "fde-squad-agent"
  cpu    = "1024"   # overridden at RunTask time per tier
  memory = "2048"   # overridden at RunTask time per tier
  # Mounts EFS for workspace access
  # Env vars: AGENT_ROLE, TASK_ID, SCD_TABLE, MODEL_ID
}
```

Resource allocation by model tier:

| Tier | CPU | Memory | Agents |
|------|-----|--------|--------|
| reasoning | 1024 | 4096 | developer, architect, adversarial, redteam, security, code-reasoning |
| standard | 512 | 2048 | intake-eval, issue-reader, code-context, quality, ops, rel, perf, tech-writer |
| fast | 256 | 1024 | reporting, dtl-commiter, cost, sustainability |

#### 3. SCD in DynamoDB

```
Table: fde-dev-squad-scd
  PK: task_id (S)
  SK: section_name (S)
  Attributes:
    - entries: List of {agent, timestamp, content}
    - updated_at: ISO timestamp
    - total_chars: Number
```

#### 4. EFS Workspace

```
/workspaces/{task_id}/{repo_name}/
  ├── .git/
  ├── src/
  └── ...
```

#### 5. Portal Integration

| Event | Portal Shows |
|-------|-------------|
| `▶ Dispatching stage: intake (2 agents)` | Stage badge updates |
| `▶ Agent started: swe-developer-agent (Sonnet 4, 4GB)` | Agent card: "running" |
| `✅ Agent complete: swe-developer-agent (45s, 12K tokens)` | Agent card: "complete" |
| `❌ Agent failed: code-sec-agent (timeout)` | Agent card: "failed" |
| `🔄 Retrying: code-sec-agent (attempt 2/3, backoff 60s)` | Agent card: "retrying" |

---

## Rollout Plan

### Phase A: Infrastructure (Terraform)
1. EFS filesystem + access point + security group
2. DynamoDB SCD table (PK: task_id, SK: section_name)
3. Agent task definition (parametrized, EFS mount)
4. Orchestrator task definition (EFS mount, ECS RunTask IAM)
5. Update EventBridge target to use orchestrator task def

### Phase B: Code (Python)
1. `distributed_orchestrator.py` — dispatches via `ecs.run_task()`
2. `agent_runner.py` — new entrypoint for agent tasks
3. `squad_context_dynamo.py` — DynamoDB-backed SCD (replaces in-memory)
4. Feature flag: `EXECUTION_MODE=monolith|distributed`

### Phase C: Integration + Validation
1. Full squad execution with parallel WAF review
2. Retry testing (kill agent mid-execution)
3. Large repo testing (1GB clone to EFS)
4. Portal per-agent visibility validation

### Phase D: Cutover
1. `EXECUTION_MODE=distributed` in production
2. Monitor 24h
3. Remove monolith code path

---

## Cost Estimation

| Component | Monthly Cost (dev) |
|-----------|-------------------|
| EFS | ~$3 |
| DynamoDB SCD | ~$1 |
| Agent tasks (Fargate) | ~$15 |
| Orchestrator tasks | ~$2 |
| **Total incremental** | **~$21/month** |

---

## References

- ADR-019: Agentic Squad Architecture
- ADR-014: Secret Isolation and DAG Parallelism
- COE-020: ECS failure detection
- `wellarchitected-serverless-applications-lens.md`: REL 5, PERF 1
- `wellarchitected-generative-ai-lens.md`: Inference workload patterns

---

## AI-DLC Strategy Alignment — Gap Analysis & Remediation Plan

> Source: `docs/example/Scaling AI-DLC with Partners - External FCD v1.0.pdf`
> Analysis date: 2026-05-08

### Executive Context

The AI-DLC (AI-Driven Development Lifecycle) is AWS's methodology for AI-native software development. It defines three phases (Inception → Construction → Operation) with human-in-the-loop at every stage. The Code Factory is the **execution platform** for this methodology. This section identifies gaps between the AI-DLC strategy and our current implementation, with concrete remediation tasks.

---

### Gap 1: Code Knowledge Base (Critical)

#### 5W2H

| Dimension | Analysis |
|-----------|----------|
| **What** | AI-DLC requires a "Code KB" with call graphs + vectorized business descriptions to solve precision/recall in large codebases |
| **Why** | "Context window will never be enough" — models cannot see the entire codebase. Current grep/file-listing produces poor matches (low precision, low recall) |
| **Who** | `swe-code-context-agent` currently does file listing and grep. Needs to query a Code KB instead |
| **When** | Before any agent writes code — the Code KB provides the "big picture" that the context window cannot hold |
| **Where** | New component: `code_knowledge_base/` — call graph extractor + vector store + query API |
| **How** | Static analysis (tree-sitter AST) → call graph extraction → LLM-generated business descriptions per call graph → vectorized in Bedrock Knowledge Base |
| **How much** | Bedrock KB: ~$5/month (dev). Tree-sitter already in requirements.txt. |

#### Adversarial Challenge

- "Isn't grep + file listing sufficient?" → No. The AI-DLC document explicitly states this is "What is available today commonly" and is insufficient for brownfield/large codebases. The Task 5 failure (using wrong API) is a direct consequence of not having a Code KB that maps business intent to actual code symbols.
- "Can't the agent just read the relevant files?" → For a 500MB repo with 2000+ files, the agent cannot read everything. It needs semantic retrieval: "find the function that invokes Bedrock for question evaluation" → returns `bedrock_invoker.py:invoke_agent()` with its exact signature.

#### Implementation Tasks

| # | Task | Deliverable | CW | LOC | Model Tier | Dependencies |
|---|------|-------------|-----|-----|-----------|-------------|
| G1.1 | Call graph extractor using tree-sitter AST | `code_knowledge_base/call_graph_extractor.py` | 1 | ~300 | reasoning | None |
| G1.2 | Business description generator (LLM summarizes each call graph) | `code_knowledge_base/description_generator.py` | 1 | ~200 | reasoning | G1.1 |
| G1.3 | Vector store integration (Bedrock Knowledge Base or OpenSearch) | `code_knowledge_base/vector_store.py` | 1 | ~250 | standard | None |
| G1.4 | Query API for agents (semantic search: business intent → code symbols) | `code_knowledge_base/query_api.py` | 1 | ~150 | standard | G1.3 |
| G1.5 | Integration with `swe-code-context-agent` prompt | Update `squad_prompts.py` | 1 | ~50 | standard | G1.4 |
| G1.6 | Onboarding script: index a repo into Code KB | `scripts/index-code-kb.sh` | 1 | ~80 | fast | G1.1, G1.2, G1.3 |

#### Red Team

- "What if the call graph is stale?" → Re-index on every PR merge (EventBridge trigger). Staleness window: max 1 PR behind.
- "What about polyglot repos?" → Tree-sitter supports 40+ languages. Call graph extraction is language-agnostic at the AST level.
- "What about cross-repo dependencies (microservices)?" → Phase 2: REST/gRPC call detection links call graphs across repos (the "tenuous connections" the AI-DLC document describes).

---

### Gap 2: Persona-Based Portal UX (High)

#### 5W2H

| Dimension | Analysis |
|-----------|----------|
| **What** | AI-DLC Platform shows "User Personas" with differentiated UX per role (PM, BA, QA, Dev, Ops) |
| **Why** | PM needs velocity/status. SRE needs health/alerts. Dev needs reasoning/code. One-size-fits-all confuses everyone. |
| **Who** | Portal users: PM (Flow + Gates), Staff SWE (Reasoning + Catalog), SRE (Health + Alerts) |
| **When** | After distributed execution is live (portal needs real per-agent data to differentiate views) |
| **Where** | `infra/portal-src/` — role-based view routing |
| **How** | URL parameter or Cognito auth → role → filtered views. No new backend needed (same API, different frontend rendering) |
| **How much** | Cognito: ~$0 (free tier). Frontend work: 3 days. |

#### Implementation Tasks

| # | Task | Deliverable | CW | LOC | Model Tier | Dependencies |
|---|------|-------------|-----|-----|-----------|-------------|
| G2.1 | Role selector in portal header (PM / SWE / SRE) | `App.tsx` role state | 1 | ~30 | standard | None |
| G2.2 | PM view: Flow + Gates + DORA metrics | Conditional rendering | 1 | ~80 | standard | G2.1 |
| G2.3 | SRE view: Health + Alerts + Agent lifecycle | New HealthDetail component | 1 | ~150 | standard | G2.1 |
| G2.4 | Dev view: Reasoning + Catalog + Code KB results | New CodeKBPanel component | 1 | ~150 | standard | G2.1, G1.4 |
| G2.5 | Cognito auth with role claims | Terraform + portal auth | 1 | ~100 (HCL+TSX) | standard | G2.1 |

---

### Gap 3: Brownfield & Large Codebase Support (Critical)

#### 5W2H

| Dimension | Analysis |
|-----------|----------|
| **What** | AI-DLC identifies "Brownfield & Large Codebases" as a unique challenge requiring specialized solutions |
| **Why** | "Changes span multiple systems", "expressed in business terms", "tribal knowledge impacts planning" |
| **Who** | Users with repos >500MB, microservice architectures, legacy codebases |
| **When** | Now — the distributed execution (EFS) enables large repos, but the agents still need Code KB to navigate them |
| **Where** | Intersection of Gap 1 (Code KB) + distributed execution (EFS) + SCD (DynamoDB) |
| **How** | EFS holds the repo. Code KB provides semantic navigation. SCD passes relevant context between agents. |
| **How much** | Covered by distributed execution cost + Code KB cost. No additional infra. |

#### Implementation Tasks

| # | Task | Deliverable | CW | LOC | Model Tier | Dependencies |
|---|------|-------------|-----|-----|-----------|-------------|
| G3.1 | EFS workspace with large repo support (2GB+) | Part of Phase A | — | — | — | Phase A |
| G3.2 | Code KB indexing for large repos (incremental) | `code_knowledge_base/incremental_indexer.py` | 1 | ~200 | reasoning | G1.1 |
| G3.3 | Cross-system call graph linking (REST/gRPC) | `code_knowledge_base/cross_system_linker.py` | 1 | ~250 | reasoning | G1.1 |
| G3.4 | Agent prompt: "Query Code KB before reading files" | Update `squad_prompts.py` | 1 | ~30 | fast | G1.4 |

---

### Gap 4: Linguistic Impedance Mismatch (High)

#### 5W2H

| Dimension | Analysis |
|-----------|----------|
| **What** | "Code does not reflect business domain vocabulary. Searches through the code base produce poor matches." |
| **Why** | The issue says "implement question enricher" but the code has `_invoke_converse()`, `bedrock_invoker.py`, `AgentInvocationResult`. Business terms ≠ code symbols. |
| **Who** | `task-intake-eval-agent` and `swe-issue-code-reader-agent` — they read business language and need to find code |
| **When** | At intake time — before any implementation starts |
| **Where** | Code KB vector store with business descriptions |
| **How** | Each call graph gets an LLM-generated business description. Query: "function that evaluates WAF questions using Bedrock" → returns `bedrock_invoker.invoke_agent()` with signature |
| **How much** | Part of Code KB (Gap 1). No additional cost. |

#### Implementation Tasks

| # | Task | Deliverable | CW | LOC | Model Tier | Dependencies |
|---|------|-------------|-----|-----|-----------|-------------|
| G4.1 | Business description generation per call graph | Part of G1.2 | — | — | — | G1.2 |
| G4.2 | Semantic query tool (`query_code_kb` Strands tool) | `tools.py` new @tool function | 1 | ~60 | standard | G1.4 |
| G4.3 | Integration in `swe-issue-code-reader-agent` prompt | Update prompt | 1 | ~30 | fast | G4.2 |
| G4.4 | Validation: Task 5 scenario (find `invoke_agent()`) | Test case | 1 | ~50 | standard | G4.2, G4.3 |

---

### Gap 5: Mob Elaboration (Medium-High)

#### 5W2H

| Dimension | Analysis |
|-----------|----------|
| **What** | AI-DLC Phase 1 (Inception) includes "Mob Elaboration" — collaborative context building with multiple humans + AI |
| **Why** | Complex features need multiple perspectives (PM, BA, Dev, QA) before construction starts |
| **Who** | Human team (PM + Dev + QA) + AI (task-intake-eval-agent) |
| **When** | Before the squad executes — during issue creation / spec writing |
| **Where** | GitHub issue + Kiro specs + collaborative refinement |
| **How** | Multi-turn collaborative spec refinement: humans provide intent, AI decomposes into units of work, humans validate |
| **How much** | No infra cost — this is a workflow/methodology change, not a platform change |

#### Implementation Tasks

| # | Task | Deliverable | CW | LOC | Model Tier | Dependencies |
|---|------|-------------|-----|-----|-----------|-------------|
| G5.1 | "Mob Elaboration" Kiro hook | `.kiro/hooks/fde-mob-elaboration.kiro.hook` | 1 | ~20 (JSON) | fast | None |
| G5.2 | Spec template with "Units of Work" | `docs/templates/unit-of-work-template.md` | 1 | ~60 (MD) | fast | None |
| G5.3 | `task-intake-eval-agent` prompt: Units of Work | Update prompt | 1 | ~40 | fast | G5.2 |
| G5.4 | Portal: Units of Work breakdown in Flow view | Frontend component | 1 | ~120 (TSX) | standard | G5.3 |

---

### Gap 6: Measurement Framework (Medium)

#### 5W2H

| Dimension | Analysis |
|-----------|----------|
| **What** | AI-DLC prescribes "Measure End-to-End Delivery Timelines" — same project estimated traditionally vs AI-DLC |
| **Why** | "Take the same project estimated with story points and implement it end-to-end with AI-DLC to measure velocity improvement" |
| **Who** | PM and leadership — need quantifiable ROI |
| **When** | After each task completes — compare actual vs estimated |
| **Where** | DORA metrics + new velocity tracking in DynamoDB |
| **How** | Track: estimated story points (from issue), actual duration, quality score (branch eval), tokens consumed |
| **How much** | DynamoDB writes: negligible. Portal component: 2 days. |

#### Implementation Tasks

| # | Task | Deliverable | CW | LOC | Model Tier | Dependencies |
|---|------|-------------|-----|-----|-----------|-------------|
| G6.1 | Add `estimated_points` to canonical task schema | Update `canonical-task-schema.yaml` | 1 | ~10 (YAML) | fast | None |
| G6.2 | Velocity calculator | `dora_metrics.py` extension | 1 | ~80 | standard | G6.1 |
| G6.3 | Portal: velocity comparison chart | New MetricsCard section | 1 | ~100 (TSX) | standard | G6.2 |
| G6.4 | Per-project velocity tracking | DynamoDB + Lambda | 1 | ~120 | standard | G6.2 |

---

### Consolidated Task Plan (Factory Metrics)

| Wave | Tasks | Context Windows | Total LOC | Dependencies |
|------|-------|----------------|-----------|-------------|
| **Wave 1: Distributed Execution** | Phase A-D (EFS, DynamoDB SCD, orchestrator rewrite) | 8 CW | ~1200 LOC | None |
| **Wave 2: Code Knowledge Base** | G1.1-G1.6 + G3.2-G3.3 + G4.1-G4.4 | 10 CW | ~1370 LOC | Wave 1 (EFS) |
| **Wave 3: Portal Persona UX** | G2.1-G2.5 + G5.4 + G6.3 | 6 CW | ~630 LOC (TSX) | Wave 1 (per-agent data) |
| **Wave 4: Methodology Integration** | G5.1-G5.3 + G6.1-G6.2 + G6.4 | 5 CW | ~330 LOC | None (parallel with Wave 2) |

### Total Effort: 29 Context Windows (~3530 LOC)
### Estimated Factory Execution Time: 4-6 hours (parallel waves) to 12 hours (sequential)

### Cost Impact

| Component | Monthly Cost |
|-----------|-------------|
| Distributed execution (EFS + Fargate) | ~$21 |
| Code KB (Bedrock KB or OpenSearch Serverless) | ~$15 |
| Cognito (future, persona auth) | ~$0 (free tier) |
| **Total platform cost** | **~$36/month (dev)** |

---

### AI-DLC Alignment Score (Post-Remediation)

| Principle | Current | After Wave 1-4 |
|-----------|---------|----------------|
| AI orchestrates, Human validates | ✅ 100% | ✅ 100% |
| Code KB for large codebases | ❌ 0% | ✅ 90% |
| Persona-based UX | ❌ 10% | ✅ 80% |
| Mob Elaboration (Inception) | ❌ 0% | ⚠️ 60% |
| Linguistic Impedance resolution | ❌ 0% | ✅ 85% |
| Measurement framework | ⚠️ 30% | ✅ 80% |
| Distributed/parallel execution | ❌ 0% | ✅ 95% |
| **Overall alignment** | **~35%** | **~85%** |
