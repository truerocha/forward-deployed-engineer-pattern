# ADR-026: Synapse 6 & 7 Implementation — Dual-Loop Transparency and Deterministic Harness

**Status**: Accepted
**Date**: 2026-05-13
**Author**: FDE Protocol (rocand)
**Context**: SWE Synapses cognitive architecture extension
**Sources**: fde-design-swe-sinapses.md Sections 8-9

## Decision

Implement Synapses 6 (Dual-Loop Agent Transparency) and 7 (Deterministic Harness over Decision Scaffolding) as operational modules in the CODE_FACTORY pipeline. This extends the Risk Inference Engine from 16 to 18 signals, adds a 7th dimension to the Fidelity Score, and introduces persistent execution governance for O4-O5 tasks.

## Context

The CODE_FACTORY pipeline lacked two capabilities identified in the SWE Synapses design document:

1. **Transparency assurance** — No mechanism to detect when an agent's stated reasoning diverges from its actual internal state (Anthropic NLA finding: 26% of evaluation contexts show unverbalized awareness)
2. **Coordination governance** — No structural prevention of the MAST taxonomy's #1 failure mode (33% of multi-agent failures are coordination failures, not model failures)

## Artifacts Produced

### New Modules (P0 — No Dependencies)

| Module | Location | Responsibility |
|--------|----------|----------------|
| AtomicTaskOwnership | `src/core/orchestration/task_ownership.py` | Lock semantics preventing two agents from claiming the same work |
| GoalAncestryTracker | `src/core/orchestration/goal_ancestry.py` | Traces every subtask back to the original user request |

### New Modules (P1 — Depends on P0)

| Module | Location | Responsibility |
|--------|----------|----------------|
| ATTP (Agent Thought Transparency Protocol) | `src/core/risk/attp.py` | NLA-lite probing of agent hidden reasoning |
| HeartbeatAwareConductor | `src/core/orchestration/heartbeat.py` | Persistent execution governance for O4-O5 tasks |

### Extended Modules

| Module | Change | Impact |
|--------|--------|--------|
| `src/core/risk/risk_signals.py` | Added signals 17-18 | Risk vector now 18-dimensional |
| `src/core/risk/risk_config.py` | Added weights for new signals | Bayesian inference updated |
| `src/core/risk/inference_engine.py` | Extended signal-to-weight mapping | Explanation generation covers 18 signals |
| `src/core/brain_sim/fidelity_score.py` | Added 7th dimension (transparency, weight 0.15) | Rebalanced from 6 to 7 dimensions |
| `src/core/orchestration/conductor.py` | Added `swe-tech-writer-agent` to capabilities | Conductor can select documentation agents |
| `.kiro/hooks/fde-adversarial-gate.kiro.hook` | Added goal ancestry and transparency probe questions | v2.0.0 to v2.1.0 |

### New Governance Artifacts

| Artifact | Location | Purpose |
|----------|----------|---------|
| Harness-First Steering | `.kiro/steering/harness-first.md` | Formalizes the 1.6% Rule as a code review constraint |
| ADR-025 | `docs/adr/ADR-025-permission-pipeline-alignment.md` | Proves FDE is a superset of Liu et al. 7-layer permission pipeline |

### Infrastructure Updates

| Layer | Change |
|-------|--------|
| Terraform | Orchestrator task def: added heartbeat budget env vars |
| Docker | Orchestrator entrypoint: wired heartbeat, ownership, goal ancestry |
| Portal | Agent interface extended with transparency fields; BrainSimCard renders transparency score |

## Design Decisions

### Signal Weights

| Signal | Weight | Rationale |
|--------|--------|-----------|
| `reasoning_divergence` | +1.5 | High weight: hidden motivation is a critical safety concern |
| `coordination_overhead_ratio` | +1.3 | Moderate-high: coordination failures are the top multi-agent failure mode |

### Execution Mode Selection

| Organism Level | Mode | Governance |
|---------------|------|-----------|
| O1-O3 | Standard (prompt, execute, complete) | Risk Engine + adversarial gate |
| O4-O5 | Heartbeat (check, evaluate, probe, act/wait) | Full governance stack + ATTP probes + heartbeat budgets |

### Budget Governance

| Budget | Default | Purpose |
|--------|---------|---------|
| Heartbeat token budget | 5,000 tokens/cycle | Caps per-cycle inference cost |
| ATTP probe budget | 10,000 tokens/task | Caps total transparency probe cost |
| Total task ceiling | 200,000 tokens | Mandatory human review before exceeding |

## Backward Compatibility

- All new signals default to 0.0 (no risk contribution when not populated)
- Heartbeat mode only activates for O4-O5 tasks
- Fidelity Score returns neutral 0.7 for transparency when no probes are available
- `HEARTBEAT_ENABLED` env var provides a kill switch

## Consequences

- Risk Engine: 16 signals to 18 signals. All existing tests pass.
- Fidelity Score: 6 dimensions to 7 dimensions. Backward compatible via neutral defaults.
- O4-O5 tasks get automatic governance escalation without configuration.
- Adversarial gate validates goal ancestry and probes for hidden motivation.
- The 1.6% Rule is enforced as a steering rule for all future code reviews.

## References

- fde-design-swe-sinapses.md Sections 8-9
- Anthropic (2026): Natural Language Autoencoders
- NVIDIA/OpenClaw (2026): Heartbeat pattern for autonomous agents
- Liu et al. (2604.14228): Dive into Claude Code
- Paperclip (Baby, 2026): Atomic task checkout and goal ancestry
- MAST taxonomy (arXiv:2503.13657): Multi-agent coordination failures
