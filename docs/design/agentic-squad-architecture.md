# Agentic Squad Architecture — FDE Code Factory

> **Status**: Design Proposal
> **Date**: 2026-05-08
> **Author**: Staff SWE + Kiro
> **ADR**: Pending (ADR-019)

---

## 1. Problem Statement (5W2H)

| Dimension | Current State | Target State |
|-----------|--------------|--------------|
| **What** | 3 monolithic agents (reconnaissance, engineering, reporting) with a single prompt each | 17+ specialized agents organized in squads with dynamic hand-off |
| **Why** | The engineering agent is a "god agent" — it handles security, performance, reliability, cost, architecture, and coding in one prompt. This violates separation of concerns and limits quality depth. | Each agent is a specialist with deep domain knowledge, invoked only when needed |
| **Who** | Agent Builder provisions 3 agents per task regardless of complexity | Orchestrator + Task Intake Eval Agent dynamically compose the squad based on task analysis |
| **When** | Every task gets the same pipeline (recon → eng → report) | Squad composition is determined at intake time based on task type, complexity, and WAF pillar relevance |
| **Where** | `agent_builder.py` hardcodes role→prompt mapping | New `squad_composer.py` resolves agents dynamically from a capability registry |
| **How** | Static pipeline: always 3 agents in sequence | Dynamic DAG: Task Intake Eval → parallel specialist invocation → convergence → reporting |
| **How much** | ~$0.15/task (3 agent invocations × ~$0.05 each) | ~$0.30-0.80/task depending on squad size (4-8 agents), but 3-5x quality improvement |

---

## 2. Current Architecture (Naive Model)

```
┌─────────────────────────────────────────────────────────┐
│  Pipeline (static, sequential)                          │
│                                                         │
│  reconnaissance → engineering → reporting               │
│       │                │              │                 │
│  "read spec"    "do everything"   "write report"       │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

**Problems**:
1. The `engineering` agent has a 1-page prompt that tries to cover security, performance, reliability, cost, architecture, testing, and coding. No human SWE works this way.
2. No adversarial review — the same agent that writes code also "reviews" it.
3. No architecture validation — code is written without structural analysis.
4. No WAF pillar alignment — the factory claims Well-Architected but doesn't enforce it per-pillar.
5. No dynamic composition — a trivial bugfix gets the same pipeline as a complex feature.

---

## 3. Target Architecture — Agentic Squad

### 3.1 The Quarteto (Orchestration Layer)

These 4 agents form the **control plane** — they decide what happens, not how.

| Agent | Role | Invocation |
|-------|------|------------|
| `task-intake-eval-agent` | Analyzes the task, determines complexity, identifies WAF pillars, composes the squad | Always first (replaces reconnaissance) |
| `architect-standard-agent` | Validates architecture decisions, component boundaries, information flow | Feature + Infrastructure tasks |
| `reviewer-security-agent` | Security review: threat model, input validation, auth, secrets, OWASP | All tasks (severity varies) |
| `fde-code-reasoning` | Deep code reasoning: refactoring strategy, design patterns, tech debt | Refactoring tasks only |

### 3.2 WAF Pillar Agents (Specialist Layer)

Each agent is a deep specialist in one Well-Architected pillar. Invoked based on task-intake-eval analysis.

| Agent | WAF Pillar | When Invoked |
|-------|-----------|--------------|
| `code-ops-agent` | Operational Excellence | Logging, monitoring, runbooks, deployment automation |
| `code-sec-agent` | Security | IAM, encryption, network isolation, secrets management |
| `code-rel-agent` | Reliability | Error handling, retries, circuit breakers, failover |
| `code-perf-agent` | Performance Efficiency | Caching, connection pooling, async patterns, resource sizing |
| `code-cost-agent` | Cost Optimization | Right-sizing, spot instances, reserved capacity, waste elimination |
| `code-sus-agent` | Sustainability | Efficient algorithms, minimal resource usage, carbon-aware scheduling |

### 3.3 SWE Agents (Execution Layer)

These agents do the actual work — reading, writing, and validating code.

| Agent | Responsibility | When Invoked |
|-------|---------------|--------------|
| `swe-issue-code-reader-agent` | Reads the issue, related code, and existing tests to build context | Always (replaces part of reconnaissance) |
| `swe-code-context-agent` | Maps the codebase: dependencies, call graphs, affected modules | Feature + Infrastructure |
| `swe-developer-agent` | Writes new code: features, implementations, integrations | New feature development |
| `swe-architect-agent` | Designs component structure, interfaces, data models | Complex features (>3 modules) |
| `swe-code-quality-agent` | Linting, formatting, test coverage, code smells, DRY/SOLID | All code changes |
| `swe-adversarial-agent` | Challenges the implementation: edge cases, failure modes, assumptions | All code changes (Phase 3.a) |
| `swe-redteam-agent` | Attacks the implementation: injection, privilege escalation, data leaks | Security-sensitive changes |

### 3.4 Reporting Agent (unchanged)

| Agent | Responsibility |
|-------|---------------|
| `reporting-agent` | Writes completion report, updates ALM, flags tech debt |

---

## 4. Dynamic Squad Composition

The `task-intake-eval-agent` produces a **Squad Manifest** — a JSON document that tells the orchestrator which agents to invoke and in what order.

```json
{
  "task_id": "TASK-abc123",
  "complexity": "high",
  "squad": {
    "intake": ["swe-issue-code-reader-agent", "swe-code-context-agent"],
    "architecture": ["swe-architect-agent", "architect-standard-agent"],
    "implementation": ["swe-developer-agent"],
    "waf_review": ["code-sec-agent", "code-rel-agent", "code-perf-agent"],
    "quality": ["swe-code-quality-agent", "swe-adversarial-agent"],
    "security": ["reviewer-security-agent", "swe-redteam-agent"],
    "reporting": ["reporting-agent"]
  },
  "parallel_groups": ["waf_review", "quality"],
  "skip_groups": [],
  "rationale": "Feature task touching auth module + API layer. Security and reliability are primary concerns."
}
```

### 4.1 Composition Rules

| Task Type | Minimum Squad | Optional (based on analysis) |
|-----------|--------------|------------------------------|
| **Feature (simple)** | intake-eval → issue-reader → developer → quality → reporting | architect, waf-pillar agents |
| **Feature (complex)** | intake-eval → issue-reader → context → architect → developer → waf-review → adversarial → reporting | redteam, all waf pillars |
| **Bugfix** | intake-eval → issue-reader → developer → quality → reporting | sec-agent if security-related |
| **Refactoring** | intake-eval → issue-reader → context → fde-code-reasoning → quality → reporting | architect if structural |
| **Infrastructure** | intake-eval → issue-reader → context → architect → developer → ops + sec + cost → reporting | all waf pillars |

### 4.2 Parallel Execution

Agents within the same group can run in parallel (no data dependency):

```
                    ┌─ code-sec-agent ──┐
                    │                   │
swe-developer ─────┼─ code-rel-agent ──┼──── swe-adversarial
                    │                   │
                    └─ code-perf-agent ─┘
```

The orchestrator already supports DAG-based execution (ADR-014). The squad manifest maps directly to a DAG where:
- Sequential groups have edges between them
- Parallel groups have no internal edges
- Each agent receives the accumulated context from previous groups

---

## 5. Adversarial Analysis

### 5.1 What could go wrong?

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Token explosion** — 17 agents × 4K tokens each = 68K tokens/task | 🔴 High | Squad composition limits to 4-8 agents per task. WAF agents only invoked when relevant. |
| **Latency** — sequential agents add ~2min each | 🟡 Medium | Parallel execution for WAF review + quality groups. Target: <15min total. |
| **Context loss** — each agent starts fresh | 🔴 High | Accumulated context passed as structured input. Each agent receives the full chain output. |
| **Conflicting recommendations** — sec-agent says "encrypt everything", cost-agent says "minimize KMS calls" | 🟡 Medium | Priority hierarchy: Security > Reliability > Performance > Cost > Sustainability. Conflicts resolved by architect-standard-agent. |
| **Over-engineering** — adversarial + redteam agents reject valid simple solutions | 🟡 Medium | Complexity threshold: simple tasks skip adversarial/redteam. Only complex features get the full squad. |
| **Prompt Registry explosion** — 17 prompts to maintain | 🟡 Medium | Prompts are versioned in DynamoDB with hash integrity. Each prompt is focused (1 page max). |

### 5.2 Red Team: How would an attacker exploit this?

| Attack Vector | Risk | Mitigation |
|---------------|------|------------|
| **Prompt injection via issue body** — malicious issue text manipulates agent behavior | 🔴 High | task-intake-eval sanitizes input. Agents operate on structured contracts, not raw issue text. |
| **Agent impersonation** — one agent claims to be another to bypass gates | 🟢 Low | Each agent has a unique registered prompt with hash integrity. Registry validates at creation. |
| **Context poisoning** — early agent injects misleading context for later agents | 🟡 Medium | Adversarial agent explicitly challenges previous agent outputs. Architect validates structural claims. |
| **Denial of service** — task designed to trigger all 17 agents | 🟡 Medium | Max squad size cap (8 agents). Concurrency guard limits parallel execution. |

---

## 6. Implementation Plan

### Phase 1: Refactor Agent Builder (Week 1)
- Rename existing agents: `reconnaissance` → `swe-issue-code-reader-agent`
- Create `task-intake-eval-agent` with squad composition logic
- Create `squad_composer.py` module
- Update orchestrator to read Squad Manifest

### Phase 2: WAF Pillar Agents (Week 2)
- Create 6 WAF pillar agent prompts (one per pillar)
- Register in Prompt Registry with context tags
- Wire into squad composition rules

### Phase 3: SWE Specialist Agents (Week 3)
- Create `swe-developer-agent`, `swe-architect-agent`, `swe-code-quality-agent`
- Create `swe-adversarial-agent`, `swe-redteam-agent`
- Wire parallel execution groups

### Phase 4: Quarteto Integration (Week 4)
- Create `architect-standard-agent`, `reviewer-security-agent`
- Create `fde-code-reasoning` (refactoring specialist)
- End-to-end testing with real tasks

---

## 7. Migration Strategy

The transition is **backward compatible**:
1. The current 3-agent pipeline maps to: `swe-issue-code-reader-agent` → `swe-developer-agent` → `reporting-agent`
2. New agents are additive — they don't replace, they augment
3. Squad composition starts conservative (4-5 agents) and expands as prompts mature
4. Feature flag: `SQUAD_MODE=classic|dynamic` (default: classic until validated)

---

## 8. Well-Architected Alignment

| Pillar | How This Design Aligns |
|--------|----------------------|
| OPS 3 | Each agent has a clear, documented responsibility |
| OPS 6 | OTEL traces show which agents were invoked and their latency |
| SEC 1 | Dedicated security agents (reviewer-security, swe-redteam) |
| REL 2 | Parallel execution with fallback to sequential if agents fail |
| PERF 1 | Parallel WAF review reduces total pipeline time |
| COST 2 | Dynamic composition avoids invoking unnecessary agents |
| SUS 1 | Smaller, focused prompts use fewer tokens than one god-prompt |

---

## 9. Success Metrics

| Metric | Current | Target |
|--------|---------|--------|
| PR quality score (branch eval) | ~6.5/10 | 8.0+/10 |
| Security findings per PR | 0 (not checked) | 0 (actively validated) |
| WAF pillar coverage per task | 0% (not tracked) | 80%+ (relevant pillars reviewed) |
| Average agents per task | 3 (fixed) | 4-8 (dynamic) |
| Pipeline latency (p50) | ~8min | <12min (more agents but parallel) |
| Token cost per task | ~$0.15 | ~$0.40 (2.5x for 3-5x quality) |
