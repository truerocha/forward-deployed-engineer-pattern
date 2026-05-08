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
