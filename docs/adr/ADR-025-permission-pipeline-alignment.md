# ADR-025: Permission Pipeline Alignment — Liu et al. 7-Layer Superset Proof

**Status**: Accepted
**Date**: 2026-05-13
**Author**: FDE Protocol (rocand)
**Context**: Synapse 7 (Deterministic Harness over Decision Scaffolding)
**Source**: Liu et al. (arXiv:2604.14228) — "Dive into Claude Code: The Design Space of Today's and Future AI Agent Systems"

## Decision

We formally document that the FDE gate architecture is a **superset** of Liu et al.'s seven-layer permission pipeline. Our implementation covers all seven layers plus additional governance mechanisms not present in the reference architecture.

## Context

Liu et al. (2026) analyzed Claude Code's architecture (~512K lines of TypeScript) and identified a seven-layer permission pipeline as the core safety mechanism. Their finding: only ~1.6% of the codebase constitutes AI decision logic; the remaining 98.4% is operational harness.

We need to validate that our FDE pipeline provides equivalent or superior safety guarantees.

## Seven-Layer Alignment Audit

| # | Liu et al. Layer | Description | FDE Equivalent | Implementation | Coverage |
|---|-----------------|-------------|----------------|----------------|----------|
| 1 | Tool pre-filtering (blanket deny) | Unrecognized tools are never exposed to the model | Risk Engine hard-block (risk > 0.9) | `src/core/risk/inference_engine.py` — `should_block` property | **SUPERSET** — we also score partial risk, not just binary allow/deny |
| 2 | Deny-first rule evaluation | Deny rules override allow rules; unrecognized actions blocked | preToolUse hook (adversarial gate) | `.kiro/hooks/fde-adversarial-gate.kiro.hook` | **EQUIVALENT** — deny-first with structured challenge |
| 3 | Permission mode constraints | Graduated permission levels based on context | Organism Ladder autonomy levels (L1-L5) | `src/core/brain_sim/organism_ladder.py` | **SUPERSET** — 5 levels vs Claude Code's 3 modes |
| 4 | Auto-mode ML classifier | ML model decides allow/deny for ambiguous cases | Risk Engine sigmoid classification | `src/core/risk/inference_engine.py` — P(Failure\|Context) | **SUPERSET** — 18-signal Bayesian inference vs binary classifier |
| 5 | Shell sandboxing | Execution environment is isolated | ECS Fargate container isolation | `infra/terraform/ecs.tf` + `infra/docker/` | **EQUIVALENT** — container-level isolation |
| 6 | Not restoring permissions on resume | Session resume does not inherit previous permissions | Session-scoped SCD (no cross-session trust) | `src/core/orchestration/distributed_orchestrator.py` | **EQUIVALENT** — each dispatch starts fresh |
| 7 | Hook-based interception | Lifecycle hooks gate operations at key points | FDE hooks (DoR, adversarial, DoD, pipeline) | `.kiro/hooks/fde-*.kiro.hook` (19 hooks) | **SUPERSET** — 19 hooks vs Claude Code's ~5 hook points |

## Additional FDE Governance (Beyond Liu et al.)

| # | FDE Mechanism | What It Adds | Why Liu et al. Doesn't Have It |
|---|--------------|--------------|-------------------------------|
| 8 | 5W2H Validation (Phase 3.c) | Structured reasoning validation against all guidance | Claude Code trusts model reasoning within harness; we validate it |
| 9 | 5 Whys Root Cause (Phase 3.d) | Forces root cause analysis before accepting fixes | Claude Code doesn't have iterative failure analysis |
| 10 | Pipeline Validation (Phase 3.b) | Validates data journey across module boundaries | Claude Code operates on single files; we validate cross-module |
| 11 | ATTP Transparency Probes (Synapse 6) | Detects hidden reasoning divergence | Claude Code doesn't probe internal model state |
| 12 | Goal Ancestry Validation (Synapse 7) | Traces every action back to original request | Claude Code doesn't track goal decomposition trees |
| 13 | Coordination Overhead Signal (Synapse 7) | Detects agent saturation before it degrades quality | Claude Code is single-agent; doesn't need coordination governance |
| 14 | Heartbeat Liveness (Synapse 6) | Detects stalled long-running tasks | Claude Code tasks are prompt-triggered, not persistent |
| 15 | Fidelity Score (7 dimensions) | Post-execution quality measurement | Claude Code doesn't score execution quality |
| 16 | Recursive Optimizer (gradient descent) | Learns from failures to adjust risk weights | Claude Code's permission system is static |
| 17 | SWE Synapse Engine (5 pre-execution synapses) | Design intelligence before execution | Claude Code doesn't apply design theory to planning |

## Quantitative Comparison

| Metric | Liu et al. (Claude Code) | FDE Pipeline |
|--------|-------------------------|--------------|
| Permission layers | 7 | 7 + 10 additional |
| Risk signals | ~3 (binary classifier) | 18 (Bayesian sigmoid) |
| Autonomy levels | 3 (modes) | 5 (L1-L5) |
| Hook points | ~5 | 19 |
| Post-execution scoring | None | 7-dimension Fidelity Score |
| Learning from failures | None | Recursive Optimizer (gradient descent) |
| Multi-agent governance | N/A (single agent) | AtomicTaskOwnership + Conductor |
| Transparency probes | None | ATTP (NLA-lite) |

## Conclusion

The FDE gate architecture provides a **strict superset** of Liu et al.'s permission pipeline. Every layer in their seven-layer model has a direct equivalent in our implementation, and we add ten additional governance mechanisms that address multi-agent coordination, transparency, learning, and design intelligence — concerns that a single-agent system like Claude Code does not face.

The key architectural difference: Liu et al.'s system trusts model judgment within a deterministic harness (correct for single-agent). Our system additionally validates that judgment via ATTP probes, goal ancestry checks, and fidelity scoring (necessary for multi-agent autonomous execution).

## Consequences

- Validates our architectural approach against the state-of-the-art reference
- Identifies where we exceed the reference (multi-agent governance, transparency)
- Confirms the 1.6% Rule applies to our system (harness >> decision logic)
- Provides a checklist for future capability additions: new capabilities should extend the harness, not the decision logic

## References

- Liu et al. (2604.14228): "Dive into Claude Code" — seven-layer permission pipeline
- fde-design-swe-sinapses.md Section 9.6: Deny-First Gate Alignment
- ADR-019: Agentic Squad Architecture
- ADR-020: Conductor Orchestration Pattern
- ADR-022: Risk Inference Engine
