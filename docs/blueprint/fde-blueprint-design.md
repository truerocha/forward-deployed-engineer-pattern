# FDE V4.0 — Autonomous Code Factory Blueprint

> Status: **design document — active**
> Date: 2026-05-15
> Previous: V3.0 (2026-05-03)
> Role: Staff Engineer as **Factory Operator** managing a squad of AI agents
> Pattern: Autonomous Code Factory (Level 4 — AI-generated with automated review, human approves outcomes)
> Scope: End-to-end — from ALM intake through agent execution to ship-ready code
> Stack: GitHub Issues + Asana | GitHub Actions + GitLab CI Ultimate (mirror) | Playwright + Docker + pytest + BDD
> Research: IBM Agent Factories (arXiv:2603.25719), Meta CCA (arXiv:2512.10398), StrongDM Attractor (NLSpec), Shapiro 5 Levels, Nielsen RL Conductor (arXiv:2512.04388v5), ICRL (arXiv:2602.17084)

---

## 0. Design Philosophy — Neuro-Inspired Engineering Principles

The Autonomous Code Factory operates on four design principles inspired by how biological neural networks process information, plus a cognitive design intelligence layer grounded in peer-reviewed software engineering theory.

### 0.1 Neurons — Encapsulated Modules with Rigid Interfaces

Every unit in the factory is a **neuron**: an encapsulated processing unit with strictly defined inputs and outputs.

| Factory Element | Input Signal | Output Signal |
|----------------|--------------|---------------|
| Workspace | Spec (NLSpec format) | Ship-ready code (MR) |
| Agent (within workspace) | Task + constraints + context | Implementation + completion report |
| Hook | Event + accumulated context | Decision (proceed / block / modify) |
| Spec | User story + scenarios | Decomposed tasks with acceptance criteria |
| Note | Task outcome + insight | Reusable knowledge for future tasks |
| Conductor | Task + organism level + knowledge context | WorkflowPlan (steps + topology + access lists) |
| Risk Engine | Data contract + DORA metrics + history | Risk score + classification + explanation |
| Synapse Engine | Task context + catalog metadata | Design assessment + conductor guidance |
| PR Reviewer | Issue spec + PR diff + test results | APPROVE / REWORK verdict |

**Rule**: If a component cannot define its input and output in one sentence each, decompose it.

### 0.2 Synaptic Cleft — Clean Context Transmission

The gap where information jumps between neurons. Signal quality degrades if the cleft is noisy.

- **Context pruning**: Load ONLY relevant context per interaction
- **Signal-to-noise**: 50 lines of precise context > 500 lines of everything
- **Handoff contracts**: When work moves between stages, the interface is a defined contract
- **Communication topology**: Conductor-generated access lists control which agents see which outputs
- **Inter-workspace synapses**: Interface contracts (OpenAPI, types) are the neurotransmitter

### 0.3 Neural Plasticity — Reinforcement and Decay

**Reinforcement** (what worked gets stronger):
- Notes from PASS tasks are `[VERIFIED]` — trusted
- Risk Engine weights self-improve via gradient descent on outcomes (Recursive Optimizer)
- ICRL episodes accumulate successful patterns for rework context injection
- Patterns in feedback.md promoted to steering

**Decay** (what didn't work fades):
- Notes older than 90 days without `[PINNED]` → archived
- Risk Engine false positives reduce signal weights automatically
- ICRL episodes expire after 30 days (TTL)
- Unused hook prompts → candidates for removal

### 0.4 Executive Function — Human as Prefrontal Cortex

| Human Decides | Agent Decides |
|---------------|---------------|
| WHAT to build (spec) | HOW to implement (code) |
| WHY to build it (value) | HOW to orchestrate (Conductor plans) |
| WHEN to ship (approve MR at L2/L3) | HOW to review (PR Reviewer at L4/L5) |
| WHICH autonomy level (fde-profile.json) | HOW to assess risk (Risk Engine) |
| WHICH connections to strengthen (feedback) | HOW to design (Synapse Engine) |

### 0.5 SWE Synapses — Cognitive Design Intelligence (ADR-024, ADR-026)

Seven cognitive design principles operate as a pre-execution intelligence layer:

| # | Synapse | Academic Source | What It Governs |
|---|---------|---------------|-----------------|
| 1 | Deep Module Principle | Ousterhout (APOSD) | Interface depth, agent instruction quality |
| 2 | Bundle Coherence | Wei (2026) | Architectural co-occurrence rules |
| 3 | Paradigm Selection | Ralph (2013) | Rational vs alternative design stance |
| 4 | Decomposition Cost | Homay (2025) | When decomposition harms vs helps |
| 5 | Epistemic Stance | King & Kimble (2004) | What the agent assumes about the domain |
| 6 | Transparency | ATTP (ADR-026) | Reasoning consistency, divergence detection |
| 7 | Coordination | Heartbeat (ADR-026) | Task ownership, goal ancestry |

**Firing order**: Epistemic → Paradigm → Cost → Coherence → Depth → Assessment

### 0.6 Derived Design Rules

| Rule | Principle | Governs |
|------|-----------|---------|
| Every workspace: defined input (spec) → defined output (MR) | Neurons | §2 Topology |
| Context per-interaction is minimal and relevant | Synaptic Cleft | §3 Intake |
| Risk scored before execution, not after failure | Risk Engine | §5 Pipeline |
| Design intelligence prescribes approach, not just gates risk | Synapses | §6 Execution |
| Reviewer independent from implementer (no shared context) | Isolation | §9 Delivery |
| Successful patterns promoted; unused patterns decay | Plasticity | §6 Notes |
| Human: specs + outcomes. Agent: implementation + validation | Executive Function | §1 Model |


---

## 1. Operating Model

### 1.1 The Staff Engineer's Role

The Staff Engineer does NOT write code. The Staff Engineer:
- Writes specs (the control plane)
- Approves test contracts (the halting condition)
- Approves outcomes (the MR — at L2/L3; auto-approved at L4/L5)
- Configures factory intensity (`fde-profile.json`)
- Refines the factory (meta-agent feedback)

### 1.2 Autonomy Level

| Level | Description | Human Role | Review Model | Our Target |
|-------|-------------|-----------|--------------|------------|
| L1 | AI-assisted | Human writes, AI suggests | — | — |
| L2 | AI-generated with human review | Human reviews every diff | L3 human only | — |
| L3 | AI-generated with automated gates | Human reviews exceptions | L1 + L2 + L3 human | Brownfield fixes |
| **L4** | **AI-generated, human approves outcomes** | **Human writes specs, approves results** | **L1 agent + L2 score + L3 human (edge cases)** | **Primary mode** |
| L5 | Fully autonomous | Human monitors metrics | L1 agent + L2 auto-merge | Future |

### 1.3 Three-Level Review Architecture (ADR-028)

| Level | Reviewer | Isolation | When |
|-------|----------|-----------|------|
| L1 | `fde-pr-reviewer-agent` (independent ECS task) | Own ICRL store, no squad context | Every PR |
| L2 | Branch Evaluation Agent (GitHub Actions) | Multi-dimensional scoring | Every PR |
| L3 | Human Reviewer | Final authority | L2/L3 autonomy or L1+L2 disagree |

**DTL Committer Decision Matrix**:

| L1 Verdict | L2 Score | Autonomy | Action |
|-----------|----------|----------|--------|
| APPROVE | >= 8.0 | L4/L5 | Auto-merge (squash) |
| APPROVE | >= 6.0 | L3 | Mark ready for human review |
| APPROVE | >= 6.0 | L2 | Assign human reviewer |
| APPROVE | < 6.0 | Any | Back to L1 with "score too low" |
| REWORK | Any | Any | Internal rework loop (human never sees it) |

### 1.4 Daily Operating Rhythm

```
09:00  DISPATCH — Write/approve specs for 3 projects
09:30  APPROVE TESTS — Review generated test contracts (not code)
09:45  RELEASE — Agents execute in background
12:00  HARVEST — Review MRs (only those that passed L1+L2)
14:00  REFINE — Analyze completion reports, update specs
16:00  ARCHITECT — Plan next milestone, write new specs
```

---

## 2. Factory Topology — Multi-Workspace Orchestration

### 2.1 The Factory Floor

```
~/.kiro/ (GLOBAL — inherited by ALL workspaces)
├── steering/
│   ├── agentic-tdd-mandate.md (auto)       ← Universal law
│   └── adversarial-protocol.md (auto)      ← Universal law
├── settings/mcp.json                        ← Shared credentials
├── notes/shared/                            ← Cross-project insights
└── skills/adversarial-planner.md            ← Universal skill

WORKSPACE A: payment-service ──── Status: IN_PROGRESS (TDD, Task 3/5)
WORKSPACE B: analytics-dashboard ── Status: SHIP_READINESS (E2E running)
WORKSPACE C: infra-terraform ───── Status: AWAITING_SPEC
```

### 2.2 Inheritance Model

| Layer | Location | Scope | Examples |
|-------|----------|-------|----------|
| Global laws | `~/.kiro/steering/` (auto) | ALL workspaces | TDD mandate, adversarial protocol |
| Global credentials | `~/.kiro/settings/mcp.json` | ALL workspaces | GitHub token, Asana token |
| Global knowledge | `~/.kiro/notes/shared/` | ALL workspaces (read) | Error patterns, tool conventions |
| Project steering | `.kiro/steering/` (manual) | THIS workspace only | Pipeline chain, régua |
| Project hooks | `.kiro/hooks/` | THIS workspace only | Gates per fde-profile.json |
| Project profile | `fde-profile.json` | THIS workspace only | Gate/extension configuration |
| Project MCP | `.kiro/settings/mcp.json` | THIS workspace (overrides global) | Project-specific servers |

### 2.3 Extension Opt-In System (ADR-032)

`fde-profile.json` at project root configures FDE intensity:

```json
{
  "version": "1.0",
  "profile": "strict",
  "gates": {
    "dor": true, "adversarial": true, "dod": true,
    "pipeline-validation": true, "branch-evaluation": true, "icrl-feedback": true
  },
  "extensions": {
    "multi-platform-export": true,
    "brown-field-elevation": true,
    "ddd-design-phase": true
  },
  "conductor": { "auto-design-threshold": 0.5 }
}
```

| Preset | Gates | Extensions | Use Case |
|--------|-------|-----------|----------|
| minimal | DoR + DoD only | none | Simple bug fixes, scripts |
| standard | All core gates | none | Regular development |
| strict | All gates + branch eval + ICRL | all | Production-critical systems |
| custom | per config | per config | Team-specific tuning |

**Rule**: Missing file = all gates ON (backward compatible).

### 2.4 Execution Modes (ADR-021)

| Mode | Infrastructure | When | Switch |
|------|---------------|------|--------|
| Monolith | Single `strands-agent` ECS task | Default, simple tasks | `execution_mode=monolith` |
| Distributed | Orchestrator + squad ECS tasks | O3+ tasks, multi-agent | `execution_mode=distributed` |

**Two-Way Door**: `terraform apply -var="execution_mode=distributed"` — rollback in <30s. Both images always in ECR. Zero-downtime switching.

### 2.5 Work Routing

| Signal | Route To |
|--------|----------|
| GitHub Issue on repo X | Workspace X |
| Asana task in Project Y | Workspace Y |
| Cross-cutting (shared lib) | Workspace that owns the lib |
| New project | Provision new workspace (§16.3) |
| Inter-project dependency | Spec in A references contract from B |


---

## 3. Work Intake

### 3.1 ALM Sources

| Source | Role | MCP Power |
|--------|------|-----------|
| GitHub Issues | Primary (open-source, public) | `@modelcontextprotocol/server-github` |
| Asana | Primary (internal, enterprise) | Asana MCP server |
| GitLab Issues | Secondary (via mirror) | `@modelcontextprotocol/server-gitlab` |

### 3.2 Work Hierarchy

```
Milestone (Quarter/Release)
  └── Epic (GitHub Milestone / Asana Project)
       └── Feature (GitHub Issue [type:feature] / Asana Section)
            └── Task (Kiro Spec task)
                 └── Subtask (Single commit)
```

### 3.3 User Story Format (NLSpec-Inspired)

```markdown
# Feature: [Title]

## Context
- Project: [name]
- Epic: [parent]
- Affected modules: [list]
- Type: [greenfield | brownfield | bugfix | refactor]

## Narrative
As a [role], I want [capability] so that [business value].

## Acceptance Criteria (BDD Scenarios)
GIVEN [precondition]
WHEN [action]
THEN [expected outcome]

## Constraints
- MUST NOT: [what cannot change]
- MUST: [NFRs — performance, security, accessibility]
- OUT OF SCOPE: [excluded]

## Definition of Done
- [ ] All acceptance scenarios pass as automated tests
- [ ] Existing test suite passes (zero regressions)
- [ ] CI/CD pipeline green
- [ ] Ship-readiness validated (Docker + E2E)
- [ ] Risk Engine score below τ_block (0.40)
- [ ] Fidelity Score >= 0.70
```

---

## 4. Spec as Control Plane

### 4.1 The StrongDM Insight

"The bottleneck has shifted from implementation speed to spec quality."

The spec is NOT documentation. It is the **control instrument** of the factory.

### 4.2 Scenarios as Holdout Set

```
Scenarios in Spec
  ├── 70% → Agent-visible (used for TDD)
  └── 30% → Holdout (used only for ship-readiness validation)
```

### 4.3 Spec Lifecycle

```
DRAFT → REVIEW → READY → IN_PROGRESS → VALIDATION → SHIPPED
```

---

## 5. Agent Pipeline — Orchestration Architecture

### 5.1 Full Pipeline (Distributed Mode)

```
Issue arrives
  → Router (scope check + data contract extraction)
    → Risk Inference Engine (P(Failure|Context) scoring)
      → Synapse Engine (design intelligence assessment)
        → Conductor (WorkflowPlan generation)
          → Distributed Orchestrator (ECS task dispatch)
            → Agent Squad (parallel/sequential execution)
              → Verification Reward Gate (linter + types + tests)
                → DTL Committer (DRAFT PR creation)
                  → PR Reviewer Agent (Level 1 — independent)
                    → Branch Evaluation (Level 2 — scoring)
                      → Human Review (Level 3 — if needed)
                        → Merge
```

### 5.2 Risk Inference Engine (ADR-022)

Calculates P(Failure|Context) before execution using 18 normalized signals:

| Category | Signals | Source |
|----------|---------|--------|
| Historical (3) | CFR, failure recurrence, repo hotspot | DORA metrics + failure_modes |
| Complexity (4) | file count, cyclomatic, dependency depth, cross-module | Data contract + catalog |
| DORA Trend (2) | lead time trend, deployment frequency | DORA metrics |
| Organism (1) | organism level (O1-O5) | Data contract |
| Protective (3) | test coverage, prior success, catalog confidence | Catalog + history |
| Synapse (3) | interface depth, decomposition cost, paradigm fit | Synapse Engine |
| Transparency (2) | reasoning divergence, coordination overhead | ATTP + Heartbeat |

**Thresholds**:

| Threshold | Value | Action |
|-----------|-------|--------|
| τ_warn | 0.08 | Emit warning to portal |
| τ_escalate | 0.15 | Tighten autonomy gates |
| τ_block | 0.40 | Eject to Staff Engineer |

**Self-improvement**: Recursive Optimizer adjusts weights via gradient descent after each task outcome.

### 5.3 Conductor Orchestration (ADR-020)

Dynamically generates WorkflowPlans based on task complexity:

```
Task + Organism Level + Synapse Assessment
  → Conductor (Bedrock reasoning model, ~$0.02/plan)
    → WorkflowPlan (steps + topology + access lists)
      → DistributedOrchestrator (ECS dispatch)
```

**Properties**:
- Focused instructions per agent (not generic role prompts)
- Communication topology via access lists (prevents context pollution)
- Difficulty adaptivity: O1-O5 drives workflow complexity
- Bounded recursion: max 2 refinements before fallback
- Topology types: Sequential | Parallel | Tree | Debate | Recursive

### 5.4 Brown-Field Elevation & DDD Design Phase (ADR-033)

Optional Conductor steps activated via `fde-profile.json`:

```
Step 0: [architect] Elevate existing code → elevation-model.md
Step 1: [architect] Domain design → domain-model.md
Step 2: [architect] Logical design → logical-design.md
Step 3: [coder] Implement per design (access_list: [0, 1, 2])
Step 4: [reviewer] Verify conformance (access_list: [1, 2, 3])
Step 5: [adversarial] Challenge design + implementation (access_list: all)
```

Activation: `ddd-design-phase = true` AND cognitive depth >= threshold (default 0.5).

### 5.5 Greenfield Pipeline

```
Spec READY → DoR Gate → Risk Engine → Synapse Engine → Conductor
  → TDD (tests first) → Human approves tests
    → Implementation → Adversarial gate on each write
      → Verification Gate → DoD Gate → PR Reviewer → Branch Eval → Delivery
```

### 5.6 Brownfield Pipeline

```
Issue → Reconnaissance → Risk Engine → Brown-Field Elevation (optional)
  → DDD Design Phase (optional) → Spec generation → Human approves
    → TDD loop → CI/CD (ALL existing tests pass)
      → PR Reviewer → Branch Eval → Delivery
```


---

## 6. Execution

### 6.1 Agentic TDD

- SHIFT-LEFT: Tests before code
- ANTI-LAZY MOCK: Cannot mock core business rule
- TEST IMMUTABILITY: Human-approved tests are frozen (hook enforced)
- HALTING: Stop when tests green + constraints satisfied

### 6.2 Working Memory

`.kiro/specs/WORKING_MEMORY.md` — updated at recipe checkpoints, max 30 lines.

### 6.3 Circuit Breaker

```
Error → Read last 40 lines stderr → Classify
  ├── ENVIRONMENT → STOP, report to human
  └── CODE → Fix (max 3 attempts, then different approach, then rollback)
```

### 6.4 Verification Reward Gate (ADR-027)

Deterministic verification before PR creation:

```
Linter → Type-checker → Test suite → Binary verdict (Pass/Fail)
```

- Agent gets max 3 inner iterations to achieve all-pass
- Measures actual rework duration (not estimated)
- Graceful degradation: skip unavailable checks

### 6.5 ICRL — In-Context Reinforcement Learning (ADR-027)

Structured episodes from review feedback:

```
Episode = (task_context, agent_action, human_reward, correction)
```

- Retrieved by relevance for rework context injection
- Pattern digests after 10+ episodes
- TTL: 30 days
- Separate stores: squad ICRL vs reviewer ICRL (isolation)

### 6.6 MCTS Planner for Rework (ADR-027)

When rework triggered, Monte Carlo Tree Search generates diverse plans:
1. Generate N=3 candidates (sequential/parallel/debate)
2. Score against feedback alignment + structural quality
3. Select best viable plan and execute with feedback constraints

### 6.7 Knowledge Graph Reconnaissance (ADR-034)

Phase 1 enhanced with graph queries:
- **Impact analysis**: Blast radius via precomputed dependency trees
- **Symbol context**: 360-degree view (callers, callees, cluster)
- **Semantic query**: Process-grouped search across codebase
- **Staleness detection**: Hook detects when writes invalidate reconnaissance

### 6.8 Cross-Session Notes

`.kiro/notes/` — hindsight notes with verification status and anti-patterns.

---

## 7. Review Feedback Loop (ADR-027)

### 7.1 Classification

| Event | Classification | Action |
|-------|---------------|--------|
| Fundamental approach wrong | full_rework | MCTS re-plan |
| Specific issues identified | partial_fix | Targeted correction |
| Quality confirmed | approval | Reinforce patterns |

### 7.2 Feedback Flow

```
PR Review Event (EventBridge)
  → Lambda: classify + resolve task_id
    → Record metrics (DORA/Trust/Verification/Happy Time)
      → Update Risk Engine weights (Bayesian learning)
        → Check circuit breaker (max 2 rework attempts)
          → Emit rework event OR close task
```

### 7.3 Circuit Breaker

- Max 2 internal rework cycles per task
- If exceeded: escalate to human with full context
- Prevents infinite rework loops

### 7.4 Conditional Autonomy

- Consistent approvals → unlock higher autonomy
- Rejections → tighten gates for similar patterns
- Risk Engine weights updated via Recursive Optimizer

---

## 8. CI/CD Integration

### 8.1 Architecture

```
GitHub (primary) ──→ GitHub Actions (CI)
  │                    ├── Branch Evaluation Agent (on PR)
  │                    └── Standard CI (lint, test, build)
  └── mirror.sh ──→ GitLab ──→ GitLab CI Ultimate
```

### 8.2 Agent Rules

- ALWAYS feature branch (never main)
- Reads CI status via MCP
- Fixes CODE errors only (circuit breaker classifies)
- NEVER merges, NEVER deploys, NEVER modifies CI config

### 8.3 Feedback Loop

```
Push → CI runs → GREEN → proceed to PR Reviewer (Level 1)
                → RED → Circuit breaker → fix or escalate
```


---

## 9. Ship-Readiness

### 9.1 Validation Stack

```
Layer 1: Unit Tests (pytest/jest) — in CI
Layer 2: Integration (Docker Compose) — agent-triggered
Layer 3: E2E + BDD (Playwright + pytest-bdd) — agent-triggered
Layer 4: Holdout Scenarios (human-written, agent never saw)
Layer 5: Visual Regression (Playwright screenshots) — for UI projects
```

### 9.2 Docker Validation

Agent runs:
1. `docker compose -f docker-compose.test.yml up -d`
2. Wait for health checks
3. Run E2E suite + holdout scenarios
4. Capture results
5. `docker compose down`
6. Report pass/fail

---

## 10. Delivery

### 10.1 Semantic Commit

```
feat(auth): implement JWT refresh rotation

Implements token refresh with 30s grace period.
Holdout scenarios validated race condition handling.
Risk score: 0.04 | Fidelity: 0.82

Closes #123
Spec: .kiro/specs/jwt-refresh.md
Co-authored-by: AI Agent <agent@kiro.dev>
```

### 10.2 MR Structure

- Summary (1-2 sentences)
- Spec reference + Issue link
- Changes per module
- Validation results (tests, E2E, holdout, CI)
- Risk Engine score + Fidelity Score
- Risks and residuals

### 10.3 Auto-Merge Path (L4/L5)

When DTL Decision Matrix yields auto-merge:
1. L1 PR Reviewer: APPROVE
2. L2 Branch Evaluation: score >= 8.0
3. Autonomy level: L4 or L5
4. Action: squash merge, close issue, update ALM

### 10.4 ALM Update

- Issue → `in-review` (MR opened)
- Issue → `closed` (MR merged)
- Asana → section moved, PR linked

---

## 11. Observability & Portal

### 11.1 Portal Architecture (Cloudscape UX — ADR-031)

AWS Cloudscape Design System with persona-based card filtering:

| Persona | Cards Visible | Focus |
|---------|--------------|-------|
| PM | DORA Sun, Review Feedback, Conductor Plan, Factory State | Delivery |
| SWE | Cognitive Autonomy, Review Feedback, Quality Gate, Pipeline Health | Quality |
| SRE | Pipeline Health, DORA Sun, Evidence Confidence, Factory State | Reliability |
| Architect | Evidence Confidence, Cognitive Autonomy, Quality Gate | Design |
| Staff | All cards (superset) | Full observability |

### 11.2 Portal Cards

| Card | What It Shows | Source |
|------|--------------|--------|
| DoraSunCard | Radial health pulse (0-100), DORA level, 7d projection | DORA Forecast Engine |
| CognitiveAutonomyCard | Organism level, synapse scores, autonomy state | Synapse Engine |
| ReviewFeedbackCard | ICRL metrics, rework rate, verification pass rate | Review Feedback |
| ConductorPlanCard | WorkflowPlan topology, agent assignments, progress | Conductor |
| QualityGateCard | 7-dimension DoD heatmap | DoD Gate v3.0 |
| PipelineHealthCard | Process trace funnel, timing, anomaly detection | Pipeline Tracing |
| EvidenceConfidenceCard | Tiered resolution breakdown, confidence badges | Evidence Resolution |

### 11.3 DORA Forecast Engine (ADR-023)

Predictive DORA metrics using EWMA projection:
- Trend direction per metric (improving/stable/degrading)
- Projects DORA levels at T+7d and T+30d
- Identifies "weakest link" metric
- Health pulse (0-100) for portal "DORA Sun" visualization
- Integrates with Risk Engine for risk-adjusted CFR

### 11.4 Fidelity Score (7 Dimensions)

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| spec_adherence | 0.20 | Does output match spec? |
| design_quality | 0.15 | Synapse satisfaction |
| reasoning_quality | 0.15 | Logical consistency |
| transparency | 0.15 | Reasoning consistency, escalation rate |
| governance_compliance | 0.15 | Gate conformance |
| context_utilization | 0.10 | Effective use of context |
| user_value_delivery | 0.10 | Business value realized |

### 11.5 Metrics (Derived, Not Collected)

| Metric | Source | Indicates |
|--------|--------|-----------|
| Tasks completed | Completion reports | Throughput |
| DoD outcomes | Completion reports | Gate effectiveness |
| Risk Engine accuracy | Prediction vs outcome | Self-improvement |
| Rework rate (5th DORA metric) | Review feedback | First-attempt quality |
| Holdout pass rate | Ship-readiness | True quality |
| Auto-merge rate | DTL decisions | Autonomy achievement |
| ICRL episode count | Episode store | Learning velocity |


---

## 12. MCP Powers

### 12.1 Required

| Power | Purpose |
|-------|---------|
| GitHub | Issues, PRs, Actions, code search |
| GitLab | MRs, pipelines, wiki |
| Asana | Tasks, projects, status |
| Playwright | Browser E2E, visual validation |
| Code Intelligence | Knowledge graph queries (impact, context, semantic) |

### 12.2 Security Boundaries

| Allowed | Forbidden |
|---------|-----------|
| Read issues, create PRs, push feature branch | Merge to main, deploy, modify CI config |
| Read CI status, create subtasks | Access secrets, modify permissions |
| Run Docker locally, run tests | Push to production, delete branches |
| Query knowledge graph | Modify graph index directly |

---

## 13. Kiro Artifacts

### 13.1 Hooks (16 total)

| Hook | Event | Purpose |
|------|-------|---------|
| fde-dor-gate | preTaskExecution | Readiness validation |
| fde-adversarial-gate | preToolUse (write) | Challenge each write (10 questions, v2.1.0) |
| fde-dod-gate | postTaskExecution | 7-dimension machine-readable validation (v3.0) |
| fde-pipeline-validation | postTaskExecution | Pipeline testing + report |
| fde-test-immutability | preToolUse (write) | VETO writes to approved tests |
| fde-circuit-breaker | postToolUse (shell) | Error classification |
| fde-enterprise-backlog | postTaskExecution | ALM sync |
| fde-enterprise-docs | postTaskExecution | ADR + docs |
| fde-enterprise-release | userTriggered | Commit + MR |
| fde-ship-readiness | userTriggered | Docker + E2E + holdout |
| fde-alternative-exploration | userTriggered | 2 approaches for L4 |
| fde-notes-consolidate | userTriggered | Cleanup notes |
| fde-prompt-refinement | userTriggered | Meta-agent analysis |
| fde-graph-staleness | postToolUse (write) | Detects reconnaissance invalidation |
| fde-graph-augmented-search | preToolUse (read) | Suggests graph queries over file reading |
| fde-compound-review | postTaskExecution | 6 specialized review lenses |

### 13.2 Steerings

| File | Inclusion | Purpose |
|------|-----------|---------|
| fde.md | manual (#fde) | Core protocol |
| fde-enterprise.md | manual (#fde-enterprise) | Enterprise ALM context |
| harness-first.md | auto | The 1.6% Rule: capabilities = harness, not prompts |

### 13.3 Multi-Platform Rule Distribution

`scripts/export_fde_rules.py` exports canonical `.kiro/steering/fde.md` to 6 platforms:

| Platform | Output Location |
|----------|----------------|
| Q Developer | `.amazonq/rules/fde-workflow.md` |
| Cursor | `.cursor/rules/fde-workflow.mdc` |
| Cline | `.clinerules/fde-workflow.md` |
| Claude Code | `.claude/fde-workflow.md` |
| GitHub Copilot | `.github/fde-instructions.md` |
| AI-DLC | `.aidlc-rule-details/fde/fde-quality-gates.md` |

Hash-based drift detection (`--verify` mode). Single source of truth.

---

## 14. Infrastructure (AWS)

### 14.1 Core Components

| Component | Purpose | Status |
|-----------|---------|--------|
| ECS Fargate | Agent execution (monolith + distributed) | Active |
| EventBridge | Task routing, review events, rework triggers | Active |
| DynamoDB | Task state, SCD events, ICRL episodes | Active |
| S3 | Artifacts, execution plans, design documents | Active |
| ECR | Agent images (strands + orchestrator + reviewer) | Active |
| EFS | Shared workspace for distributed agents | Active |
| CloudWatch | Alarms, metrics, scheduled reaper | Active |
| Lambda | Review feedback processor, reaper handler | Active |

### 14.2 Execution Mode Switch (ADR-021)

```hcl
variable "execution_mode" {
  type    = string
  default = "monolith"  # or "distributed"
}
```

- Both task definitions always exist
- EventBridge target switches based on variable
- Rollback: `terraform apply -var="execution_mode=monolith"` (<30s)
- Zero-downtime: in-flight tasks complete on old mode

### 14.3 Pipeline Reliability

| Component | Purpose |
|-----------|---------|
| Reaper Lambda | Scheduled (5min): reaps stuck tasks, retries queued |
| `@retry_with_backoff` | Decorator for critical DynamoDB operations |
| S3 failure classification | Retriable vs permanent write failures |
| Cross-container resume | Execution plans persisted to DynamoDB |

### 14.4 Review Feedback Infrastructure

```
EventBridge Rules:
  ├── pr_review_submitted → Lambda (classify + record)
  ├── pr_rework_comment → Lambda (partial fix)
  └── task_rework_requested → ECS target (re-execute with feedback)
```

Feature flag: `review_feedback_enabled` (two-way door).

---

## 15. Risk Register

| Risk | Mitigation |
|------|------------|
| Low spec quality → bad output | Spec review as human gate; holdout catches gaps |
| Agent modifies approved tests | Test immutability VETO hook |
| CI failure loop burns tokens | Circuit breaker; max 3 attempts |
| Agent pushes to main | Hook prohibition + branch protection |
| Risk Engine over-blocks during calibration | Conservative τ_block=0.40; needs 30+ tasks |
| PR Reviewer becomes rubber stamp | Track approval rate; alert if >95% |
| Rework loop burns tokens | Circuit breaker: max 2 internal rework cycles |
| Conductor generates invalid plans | Fallback to safe sequential plan |
| Synapse thresholds too aggressive | Conservative defaults; neutral values |
| Auto-merge introduces regressions | L2 score >= 8.0 + full test suite required |
| Knowledge graph stale after writes | Staleness hook detects and flags |

---

## 16. Adoption & Operations

### 16.1 Prerequisites

- Kiro IDE or Kiro CLI installed
- Git configured with SSH or HTTPS
- Environment variables: GITHUB_TOKEN, GITLAB_TOKEN, ASANA_TOKEN
- MCP servers: GitHub, Code Intelligence (optional)
- Docker installed (for ship-readiness)
- Playwright installed (for UI projects)

### 16.2 First-Time Setup

```bash
# 1. Clone the factory template
git clone https://github.com/<org>/forward-deployed-engineer-pattern.git ~/factory-template

# 2. Create global steerings
mkdir -p ~/.kiro/steering
cp ~/factory-template/docs/global-steerings/*.md ~/.kiro/steering/

# 3. Create global MCP config
mkdir -p ~/.kiro/settings
# Edit ~/.kiro/settings/mcp.json with tokens

# 4. Create global notes
mkdir -p ~/.kiro/notes/shared
```

### 16.3 Onboarding a New Project

```bash
# 1. Clone project repo
git clone <repo-url> && cd <repo>

# 2. Copy factory structure
cp -r ~/factory-template/.kiro .kiro

# 3. Create fde-profile.json (choose preset: minimal/standard/strict)
echo '{"version":"1.0","profile":"standard"}' > fde-profile.json

# 4. Customize .kiro/steering/fde.md for THIS project

# 5. Open in Kiro IDE — verify: #fde in chat
```

### 16.4 First Task Walkthrough

```
1. Write spec in .kiro/specs/my-first-feature.md
2. In Kiro chat: "#fde Execute the spec"
3. Pipeline: DoR → Risk Engine → Synapse → Conductor → TDD → DoD
4. Review completion report
5. PR auto-reviewed (L4) or manually reviewed (L2/L3)
6. Approve and merge
```

---

## 17. References

1. Bhandwaldar et al. "Agent Factories for HLS." arXiv:2603.25719, 2026.
2. Wong et al. "Confucius Code Agent." arXiv:2512.10398, 2026.
3. StrongDM/Attractor. NLSpec pattern. 2025-2026.
4. Shapiro. "Five Levels of AI Coding Autonomy." 2025.
5. Nielsen et al. "RL Conductor for Multi-Agent Coordination." arXiv:2512.04388v5, ICLR 2026.
6. ICRL. "In-Context Reinforcement Learning." arXiv:2602.17084, 2026.
7. c-CRAB. "Code Review Agent Benchmark." arXiv:2603.23448, 2026.
8. Ousterhout. "A Philosophy of Software Design." 2018.
9. Wei. "Multi-Agent Bundle Coherence." arXiv:2604.18071, 2026.
10. Ralph. "Design Theory." arXiv:1303.5938, 2013.
11. Homay. "Fundamental Theorem of Software Engineering." arXiv:2507.09596, 2025.
12. King & Kimble. "Epistemic Stance in Knowledge Management." arXiv:cs/0406022, 2004.

---

## 18. ADR Index

| ADR | Title | Date | Blueprint Section |
|-----|-------|------|-------------------|
| ADR-019 | Agentic Squad Architecture | 2026-05-11 | §2.4, §14 |
| ADR-020 | Conductor Orchestration Pattern | 2026-05-11 | §5.3 |
| ADR-021 | Two-Way Door Distributed Execution | 2026-05-11 | §2.4, §14.2 |
| ADR-022 | Risk Inference Engine | 2026-05-12 | §5.2 |
| ADR-023 | DORA Forecast Engine | 2026-05-12 | §11.3 |
| ADR-024 | SWE Synapses Cognitive Architecture | 2026-05-12 | §0.5 |
| ADR-025 | Permission Pipeline Alignment | 2026-05-13 | §13.1 |
| ADR-026 | Synapse 6 & 7 Implementation | 2026-05-13 | §0.5 |
| ADR-027 | Review Feedback Loop (ICRL) | 2026-05-13 | §6.4-6.6, §7 |
| ADR-028 | PR Reviewer Agent (Three-Level) | 2026-05-13 | §1.3, §10.3 |
| ADR-029 | Cognitive Autonomy Model | 2026-05-14 | §1.2 |
| ADR-030 | Cognitive Router Dual Path | 2026-05-14 | §5.1 |
| ADR-031 | Cloudscape UX Reform | 2026-05-15 | §11.1 |
| ADR-032 | FDE Extension Opt-In System | 2026-05-15 | §2.3 |
| ADR-033 | Brown-Field Elevation & DDD | 2026-05-15 | §5.4 |
| ADR-034 | Knowledge Graph Reconnaissance | 2026-05-15 | §6.7 |

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| V3.0 | 2026-05-03 | Initial blueprint |
| V4.0 | 2026-05-15 | Added: Risk Engine (§5.2), Conductor (§5.3), SWE Synapses (§0.5), Three-Level Review (§1.3), ICRL Feedback Loop (§7), DORA Forecast (§11.3), Cloudscape Portal (§11.1), Extension Opt-In (§2.3), Two-Way Door (§2.4), Brown-Field Elevation (§5.4), Knowledge Graph Recon (§6.7), Fidelity Score 7D (§11.4), Pipeline Reliability (§14.3). Restructured: §5 Pipeline, §11 Observability, §14 Infrastructure. |
