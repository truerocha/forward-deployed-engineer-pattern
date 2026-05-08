# ADR-019: Agentic Squad Architecture

- **Status**: Accepted
- **Date**: 2026-05-08
- **Deciders**: Staff SWE (rocand)
- **Context**: COE-019 observability fix revealed the engineering agent is a "god agent" that handles all concerns in one prompt

## Context

The Code Factory currently uses 3 monolithic agents (reconnaissance → engineering → reporting) provisioned statically by the Agent Builder. The engineering agent's prompt tries to cover security, performance, reliability, cost, architecture, testing, and coding — violating separation of concerns and limiting quality depth.

Real software teams don't work this way. A Staff SWE doesn't write code, review security, validate architecture, and write docs in one pass. They collaborate with specialists.

## Decision

Replace the static 3-agent pipeline with a **dynamic Agentic Squad** composed at task intake time. The squad is organized in 5 layers:

### Layer 1: Quarteto (Control Plane) — 4 agents
| Agent | Role |
|-------|------|
| `task-intake-eval-agent` | Analyzes task, determines complexity, composes squad |
| `architect-standard-agent` | Validates architecture decisions |
| `reviewer-security-agent` | Security review (OWASP, threat model) |
| `fde-code-reasoning` | Deep code reasoning for refactoring |

### Layer 2: WAF Pillar Agents (Specialist) — 6 agents
| Agent | Pillar |
|-------|--------|
| `code-ops-agent` | Operational Excellence |
| `code-sec-agent` | Security |
| `code-rel-agent` | Reliability |
| `code-perf-agent` | Performance Efficiency |
| `code-cost-agent` | Cost Optimization |
| `code-sus-agent` | Sustainability |

### Layer 3: SWE Agents (Execution) — 7 agents
| Agent | Responsibility |
|-------|---------------|
| `swe-issue-code-reader-agent` | Reads issue + related code |
| `swe-code-context-agent` | Maps codebase dependencies |
| `swe-developer-agent` | Writes new code |
| `swe-architect-agent` | Designs components |
| `swe-code-quality-agent` | Linting, coverage, SOLID |
| `swe-adversarial-agent` | Challenges implementation |
| `swe-redteam-agent` | Attacks implementation |

### Layer 4: Delivery Agents — 2 agents
| Agent | Responsibility |
|-------|---------------|
| `swe-tech-writer-agent` | Updates repo docs (README, CHANGELOG, ADRs) after task completion |
| `swe-dtl-commiter-agent` | Commits with "FDE Squad Leader" identity, separating human vs machine authorship |

### Layer 5: Reporting — 1 agent
| Agent | Responsibility |
|-------|---------------|
| `reporting-agent` | Writes completion report, updates ALM |

### Dynamic Composition

The `task-intake-eval-agent` produces a **Squad Manifest** that tells the orchestrator which agents to invoke. A simple bugfix uses 4 agents. A complex feature uses 8. WAF pillar agents run in parallel.

### Git Identity Separation

| Author | Identity | When |
|--------|----------|------|
| Human developer | Personal GitHub/GitLab account | Manual commits |
| FDE Squad | `FDE Squad Leader <fde-squad@factory.local>` | All factory-generated commits |

This separation ensures:
- Git blame clearly shows human vs machine authorship
- The GitHub PAT owner's name never appears on machine-generated commits
- PR attribution is explicit (agent authored, human reviews)

## Consequences

### Positive
- Each agent is a focused specialist (1-page prompt max)
- WAF pillar coverage is explicit and measurable
- Dynamic composition avoids unnecessary agents for simple tasks
- Parallel execution reduces latency despite more agents
- Clear human/machine authorship boundary

### Negative
- More prompts to maintain (20 vs 3)
- Higher token cost per task (~$0.40 vs ~$0.15)
- Squad composition logic adds complexity to the orchestrator
- Prompt Registry becomes a critical dependency

### Risks
- Token explosion if squad composition is too aggressive (mitigated: max 8 agents/task)
- Context loss between agents (mitigated: structured context passing)
- Conflicting recommendations between WAF agents (mitigated: priority hierarchy SEC > REL > PERF > COST > SUS)

## Alternatives Considered

1. **Keep 3 agents, improve prompts** — Rejected: a single prompt cannot be a deep specialist in 6 WAF pillars simultaneously
2. **Fixed 6-agent pipeline** — Rejected: wastes tokens on irrelevant agents for simple tasks
3. **Human-in-the-loop composition** — Rejected: defeats the purpose of autonomous execution at L4/L5

## Implementation

- Phase 1: `squad_composer.py` + `task-intake-eval-agent` (Week 1)
- Phase 2: WAF pillar agent prompts (Week 2)
- Phase 3: SWE specialist agents (Week 3)
- Phase 4: Delivery agents + Quarteto integration (Week 4)
- Feature flag: `SQUAD_MODE=classic|dynamic` (default: classic)

## Well-Architected Alignment

| Pillar | Alignment |
|--------|-----------|
| OPS 3 | Each agent has documented responsibility |
| OPS 6 | OTEL traces show squad composition per task |
| SEC 1 | Dedicated security agents (reviewer-security, swe-redteam) |
| REL 2 | Parallel execution with fallback to sequential |
| PERF 1 | Parallel WAF review reduces pipeline time |
| COST 2 | Dynamic composition avoids unnecessary agents |
| SUS 1 | Focused prompts use fewer tokens than god-prompts |
