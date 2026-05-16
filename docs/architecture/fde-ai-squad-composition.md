# FDE AI Squad Composition — Agent Ecosystem Inventory

> **Version**: 1.0 | **Date**: 2026-05-16 | **Status**: Living Document
> **Scope**: Complete inventory of all AI agents, their capabilities, DynamoDB tables, and inter-agent communication patterns.

---

## Executive Summary

The FDE Code Factory operates a multi-agent system with **15 specialized agents** organized across two execution paths: a monolith pipeline (ECS single-task) and a distributed squad (ECS multi-task with A2A protocol). Agents communicate via DynamoDB Shared Context Documents (SCD), EventBridge events, and the A2A JSON-RPC protocol.

---

## 1. Agent Inventory

### 1.1 Core Pipeline Agents (Monolith Path)

| # | Agent | FDE Phase | Model Tier | Specialization |
|---|-------|-----------|------------|----------------|
| 1 | **Reconnaissance** | Phase 1 | Configurable (default: Sonnet) | Reads spec, maps modules/edges/artifacts, produces Context+Instruction+Constraints contract |
| 2 | **Engineering** | Phases 2-3 | Configurable (default: Sonnet) | Reformulates task, executes engineering recipe (adversarial challenge, pipeline testing, 5W2H, 5 Whys) |
| 3 | **Reporting** | Phase 4 | Configurable (default: Sonnet) | Summarizes execution, writes completion report, updates ALM, flags tech-debt |

### 1.2 Conductor-Managed Squad Agents (Distributed Path)

| # | Agent | Strengths | Model Tier | Cost Weight |
|---|-------|-----------|------------|-------------|
| 4 | **swe-developer-agent** | Implementation, refactoring, debugging | reasoning | 1.0 |
| 5 | **swe-architect-agent** | Design, architecture, decomposition | reasoning | 1.0 |
| 6 | **swe-adversarial-agent** | Review, security, edge-cases | reasoning | 1.0 |
| 7 | **swe-code-context-agent** | Navigation, search, understanding | fast | 0.3 |
| 8 | **fde-tech-lead-agent** | Planning, decomposition, governance | reasoning | 1.0 |
| 9 | **swe-tech-writer-agent** | Documentation, changelog, ADR, readme | standard | 0.5 |
| 10 | **fde-pr-reviewer-agent** | Review, spec-alignment, quality-gate, candid-feedback | reasoning | 1.0 |

### 1.3 Specialized Agents

| # | Agent | Stage | Model Tier | Purpose |
|---|-------|-------|------------|---------|
| 11 | **Fidelity Agent** | Stage 6 (final) | fast (Haiku) | Scores execution quality across 5 dimensions. Classifications: emulation/simulation/degraded |
| 12 | **Onboarding Agent** | Phase 0 | Rule-based (no LLM) | Assesses new repos via git history. Recommends autonomy level, profile, organism level, team archetype |

### 1.4 A2A Protocol Agents (Decoupled Microservices)

| # | Agent | Endpoint | Model | Temperature | Specialization |
|---|-------|----------|-------|-------------|----------------|
| 13 | **Pesquisa** (Research) | `pesquisa.fde.local:9001` | Claude Sonnet | 0.3 | Factual data collection, source attribution, confidence scoring |
| 14 | **Escrita** (Engineering) | `escrita.fde.local:9002` | Claude Sonnet | 0.5 | Technical document/code generation, iterative rework from feedback |
| 15 | **Revisão** (Review) | `revisao.fde.local:9003` | Claude Sonnet | 0.2 | Quality assessment, structured feedback, approval/rejection verdicts |

---

## 2. Agent Tools Matrix

| Tool | Recon | Engineering | Reporting | A2A Pesquisa | A2A Escrita | A2A Revisão |
|------|:-----:|:-----------:|:---------:|:------------:|:-----------:|:-----------:|
| `read_spec` | ✓ | ✓ | — | — | — | — |
| `write_artifact` | — | ✓ | ✓ | — | — | — |
| `run_shell_command` | ✓ | ✓ | — | — | — | — |
| `query_code_kb` | ✓ | ✓ | — | — | — | — |
| `update_github_issue` | — | ✓ | ✓ | — | — | — |
| `update_gitlab_issue` | — | ✓ | ✓ | — | — | — |
| `update_asana_task` | — | ✓ | ✓ | — | — | — |
| `create_github_pull_request` | — | ✓ | — | — | — | — |
| `create_gitlab_merge_request` | — | ✓ | — | — | — | — |
| `read_factory_metrics` | — | — | ✓ | — | — | — |
| `read_factory_health` | — | — | ✓ | — | — | — |
| `http_request` | — | — | — | ✓ | — | — |
| `retrieve` (RAG) | — | — | — | ✓ | — | — |
| `editor` | — | — | — | — | ✓ | — |
| `file_write` | — | — | — | — | ✓ | — |
| *(pure reasoning)* | — | — | — | — | — | ✓ |

---

## 3. DynamoDB Tables Inventory

### 3.1 Core Tables (`infra/terraform/dynamodb.tf`)

| Table | Name Pattern | PK | SK/Range | GSIs | Purpose | Accessed By |
|-------|-------------|----|----|------|---------|-------------|
| Prompt Registry | `fde-{env}-prompt-registry` | `prompt_name` (S) | `version` (N) | — | Versioned prompt storage with integrity hashes | Agent Builder, Conductor |
| Task Queue | `fde-{env}-task-queue` | `task_id` (S) | — | `status-created-index` | Task lifecycle, DAG fan-out (streams), CONFIG items, TTL 90d | Orchestrator, Router, Reaper |
| Agent Lifecycle | `fde-{env}-agent-lifecycle` | `agent_instance_id` (S) | — | `status-created-index` | Agent instance tracking | Orchestrator, Portal |
| DORA Metrics | `fde-{env}-dora-metrics` | `metric_id` (S) | — | `task-index`, `type-index` | Append-only DORA + factory metrics | Reporting Agent, Portal |

### 3.2 Distributed Tables (`infra/terraform/modules/dynamodb/`)

| Table | Name Pattern | PK | SK/Range | GSIs | Purpose | Accessed By |
|-------|-------------|----|----|------|---------|-------------|
| SCD | `fde-{env}-scd` | `task_id` (S) | `section_key` (S) | — | Shared Context Document (inter-agent state) | All squad agents, Orchestrator |
| Metrics | `fde-{env}-metrics` | `project_id` (S) | `metric_key` (S) | — | Unified metrics (cognitive autonomy, trust, ICRL) | Orchestrator, Portal, Entrypoint |
| Memory | `fde-{env}-memory` | `project_id` (S) | `memory_key` (S) | — | Past decisions and outcomes | Orchestrator, Conductor |
| Knowledge | `fde-{env}-knowledge` | `project_id` (S) | `knowledge_key` (S) | `type-index`, `freshness-index` | Call graphs, descriptions, vectors, annotations, quality scores | All agents (via `query_code_kb`), Incremental Indexer |
| Context Hierarchy | `fde-{env}-context-hierarchy` | `project_id` (S) | `level_item_key` (S) | — | L1-L5 project context layers | Orchestrator |
| Organism | `fde-{env}-organism` | `project_id` (S) | `organism_key` (S) | — | Complexity classification per repo | Orchestrator, Onboarding Agent |

### 3.3 A2A Tables (`infra/terraform/a2a-ecs.tf`)

| Table | Name Pattern | PK | SK/Range | TTL | Purpose | Accessed By |
|-------|-------------|----|----|-----|---------|-------------|
| A2A Workflow State | `fde-{env}-a2a-workflow-state` | `workflow_id` (S) | `checkpoint_key` (S) | ✓ (7d) | Workflow graph checkpointing (Saga pattern) | A2A Orchestrator, ResilientStateManager |

### 3.4 Resilience Queues (`infra/terraform/a2a-resilience.tf`)

| Queue | Name Pattern | Retention | Purpose | Accessed By |
|-------|-------------|-----------|---------|-------------|
| A2A DLQ | `fde-{env}-a2a-workflow-dlq` | 14 days | Failed workflow isolation | ResilientStateManager |
| A2A Retry | `fde-{env}-a2a-workflow-retry` | 1 day | Retry buffer (redrive to DLQ after 3) | ResilientStateManager |

---

## 4. Orchestration Patterns

### 4.1 Monolith Pipeline (Default)

```
EventBridge → ECS Task (single container)
  └─ Router → Constraint Extractor → DoR Gate → Agent Builder
       └─ Reconnaissance Agent → Engineering Agent → Reporting Agent
```

### 4.2 Distributed Squad (O3+ tasks)

```
EventBridge → Cognitive Router Lambda → ECS Orchestrator Task
  └─ Conductor generates WorkflowPlan (topology: sequential|parallel|tree|debate|recursive)
       └─ DistributedOrchestrator dispatches ECS RunTask per agent
            └─ Stage 1: [planner] → Stage 2: [implementer, tester] → Stage 3: [reviewer]
```

### 4.3 A2A Protocol (Decoupled Microservices)

```
A2A Orchestrator → HTTP/JSON-RPC → Cloud Map DNS
  └─ pesquisa.fde.local:9001 → escrita.fde.local:9002 → revisao.fde.local:9003
       └─ Feedback loop: revisao → escrita (max 3 cycles)
       └─ DynamoDB checkpointing at each node transition
       └─ SQS DLQ after 3 failed retries
```

---

## 5. Cognitive Autonomy Model (ADR-029)

### Capability Depth (HOW — never decreases on failure)

| Depth Range | Squad Size | Model Tier | Verification | Topology | Includes |
|-------------|-----------|------------|--------------|----------|----------|
| < 0.3 | 2 | fast | minimal | sequential | — |
| 0.3 – 0.5 | 4 | standard | standard | sequential | adversarial |
| 0.5 – 0.7 | 6 | reasoning | full | tree | adversarial, PR reviewer, architect |
| ≥ 0.85 | 8 | deep | full_mcts | debate | all agents |

### Delivery Authority (TRUST — can decrease on failure)

| Level | Condition | Behavior |
|-------|-----------|----------|
| `blocked` | CFR > 30% or staff override | Manual review required |
| `ready_for_review` | Default | Human review before merge |
| `auto_merge` | CFR < 10% + trust ≥ 80% + 3 successes | Autonomous merge |

---

## 6. Knowledge Plane (Code Intelligence)

### 6.1 Components

| Module | Purpose | DynamoDB Key Pattern |
|--------|---------|---------------------|
| `CallGraphExtractor` | Function/class/import relationships | `callgraph#{module_path}` |
| `DescriptionGenerator` | LLM-generated module descriptions | `description#{module_path}` |
| `VectorStore` | Bedrock Titan Embeddings (1024-dim) for semantic search | `vector#{entry_id}` |
| `KnowledgeAnnotationStore` | What governs each module | `annotation#{module_path}` |
| `DataQualityScorer` | Freshness/completeness/consistency/accuracy | `quality#{artifact_name}` |
| `QueryAPI` | Unified search (semantic + call graph + vector) | Reads all above |
| `IncrementalIndexer` | Re-indexes only changed files on PR merge | Writes all above |

### 6.2 Embedding Model

- **Model**: Amazon Titan Embed Text v2 (`amazon.titan-embed-text-v2:0`)
- **Dimension**: 1024
- **Max text**: 8192 characters
- **Storage**: DynamoDB (cosine similarity at query time)

### 6.3 MCP Server (`code-intelligence`)

Exposes Knowledge Plane to IDE agents via MCP protocol:
- `search_semantic` — Natural language code search
- `search_function` — Find function by name
- `trace_callers` — Upstream dependency tree
- `trace_callees` — Downstream dependency tree
- `search_module` — Module knowledge lookup
- `impact_analysis` — Blast radius assessment

---

## 7. A2A Protocol Data Contracts

| Contract | Producer | Consumer | Key Fields |
|----------|----------|----------|------------|
| `ConteudoBruto` | Pesquisa | Escrita | topico, fatos_encontrados, fontes, confianca |
| `RelatorioFinal` | Escrita | Revisão | titulo, introducao, corpo_analise, conclusao, artefatos, aprovado |
| `FeedbackRevisao` | Revisão | Escrita (rework) | veredicto, score_qualidade, criticas, pontos_positivos, aprovado |
| `ContextoWorkflow` | Orchestrator | DynamoDB | workflow_id, no_atual, dados_pesquisa, relatorio, feedback, tentativas |

---

## 8. Fidelity Scoring Dimensions

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| Spec Adherence | 0.30 | Were all acceptance criteria addressed? Tests written? Scope respected? |
| Reasoning Quality | 0.20 | Are decisions justified? Trade-offs acknowledged? |
| Context Utilization | 0.15 | Was available context (ADRs, memory, hierarchy) actually used? |
| Governance Compliance | 0.20 | Did all gates pass? Test immutability respected? |
| User Value Delivery | 0.15 | Does implementation serve the stated user need? |

**Classifications**: emulation (≥0.85) | simulation (≥0.55) | degraded (<0.55)

---

## 9. Model Tier Mapping

| Tier | Bedrock Model ID | Use Cases | Approx Cost (input/output per 1M tokens) |
|------|-----------------|-----------|------------------------------------------|
| **fast** | `us.anthropic.claude-haiku-4-5-20251001-v1:0` | Fidelity scoring, code context, reporting | $0.25 / $1.25 |
| **standard** | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | Tech writing, standard engineering | $3 / $15 |
| **reasoning** | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | Architecture, adversarial review, planning | $3 / $15 |
| **deep** | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | System-wide transformations (O5) | $3 / $15 |

---

## 10. Infrastructure Summary

| Resource | Count | Purpose |
|----------|-------|---------|
| ECS Cluster | 1 | `fde-dev-cluster` — all agent tasks |
| ECS Task Definitions | 5+ | strands-agent, orchestrator, a2a-pesquisa, a2a-escrita, a2a-revisao |
| ECS Services | 3 | A2A agents (Cloud Map registered) |
| DynamoDB Tables | 11 | State, metrics, knowledge, checkpointing |
| SQS Queues | 2 | A2A retry + DLQ |
| ECR Repository | 1 | Shared, tag-based image selection |
| Cloud Map Namespace | 1 | `fde.local` (A2A service discovery) |
| CloudWatch Alarms | 1+ | DLQ message count |
| S3 Bucket | 1 | Artifacts, specs, reports |
| Secrets Manager | 1 | ALM tokens (GitHub, GitLab, Asana) |

---

## 11. A2A Squad Wire — Intentional Protocol Integration

> **Status**: Implemented (2026-05-16)
> **Modules**: `src/core/a2a/` (agent_cards, orchestrator, squad_bridge)

### 11.1 Problem Statement

The A2A protocol was implemented generically — three servers (Pesquisa, Escrita, Revisão) exposed via Strands `A2AServer`, but no agent used the protocol intentionally. The Conductor's squad composition had no bridge to the A2A microservice layer.

### 11.2 Solution: Four-Layer Wire

| Layer | Module | Purpose |
|-------|--------|---------|
| **Agent Cards** | `agent_cards.py` | Explicit JSON Schema manifests derived from Pydantic contracts. Enables service discovery and contract-first validation. |
| **Squad Orchestrator** | `orchestrator.py` | Production entrypoint wiring `GrafoResiliente` + `ResilientStateManager` + OTel tracing. CLI + EventBridge compatible. |
| **Squad Bridge** | `squad_bridge.py` | Translates between Conductor's WorkflowPlan/SCD and A2A's ContextoWorkflow. Routes tasks to A2A when topology requires decoupled execution. |
| **Server Tracing** | `servers/*.py` | Each server now initializes OTel tracing and references its Agent Card for identity. |

### 11.3 Squad Role → A2A Agent Mapping

| Conductor Role | A2A Agent | Endpoint |
|---------------|-----------|----------|
| `reconnaissance`, `researcher`, `swe-code-context-agent` | fde-research-agent | pesquisa.fde.local:9001 |
| `engineering`, `implementer`, `swe-developer-agent`, `swe-architect-agent`, `swe-tech-writer-agent` | fde-engineering-agent | escrita.fde.local:9002 |
| `reviewer`, `adversarial`, `swe-adversarial-agent`, `fde-pr-reviewer-agent` | fde-review-agent | revisao.fde.local:9003 |

### 11.4 Execution Flow (Wired)

```
Conductor WorkflowPlan
  │
  ├─ SquadBridge.should_use_a2a(stage) → True?
  │     │
  │     ├─ translate_scd_to_a2a_context(scd, task)
  │     │
  │     ├─ SquadOrchestrator.executar(prompt, workflow_id)
  │     │     │
  │     │     ├─ [PESQUISA] → trace_workflow_node → A2AAgent.invoke → ConteudoBruto ✓
  │     │     ├─ [ESCRITA]  → trace_workflow_node → A2AAgent.invoke → RelatorioFinal ✓
  │     │     ├─ [REVISAO]  → trace_workflow_node → A2AAgent.invoke → FeedbackRevisao ✓
  │     │     │     └─ feedback_loop (max 3) → ESCRITA rework → REVISAO
  │     │     ├─ DynamoDB checkpoint at each node transition
  │     │     └─ ResilientStateManager: retry 3x → SQS DLQ
  │     │
  │     └─ translate_a2a_result_to_scd(result, task_id)
  │
  └─ Conductor-direct (fast in-process tasks)
```

### 11.5 CLI Usage

```bash
# Execute a workflow
python -m src.core.a2a.orchestrator --prompt "Implement pagination for /users API"

# Recover a failed workflow
python -m src.core.a2a.orchestrator --workflow-id wf-abc123

# List available A2A agents
python -m src.core.a2a.orchestrator --list-agents

# Check workflow status
python -m src.core.a2a.orchestrator --status wf-abc123

# EventBridge trigger (stdin JSON)
echo '{"prompt": "...", "workflow_id": "wf-xyz"}' | python -m src.core.a2a.orchestrator
```

### 11.6 Observability Chain

```
Agent Container → OTel SDK → OTLP/gRPC → ADOT Sidecar → AWS X-Ray
                                                              │
Spans: a2a.node.pesquisa → a2a.invoke.pesquisa → http.request
       a2a.node.escrita  → a2a.invoke.escrita  → http.request
       a2a.node.revisao  → a2a.invoke.revisao  → http.request
```

---

## References

- ADR-019: Agentic Squad Architecture
- ADR-020: Conductor Orchestration Pattern
- ADR-029: Cognitive Autonomy Model
- ADR-030: Cognitive Router Dual-Path
- ADR-034: A2A Protocol Integration with Strands SDK
- `docs/design/fde-core-brain-development.md`
- `fde-design-swe-sinapses.md`
