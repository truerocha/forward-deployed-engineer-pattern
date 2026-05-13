# ADR-024: SWE Synapses — Cognitive Design Intelligence for Agent Architecture

> Status: **Accepted**
> Date: 2026-05-12
> Deciders: Staff SWE (rocand)
> Sources: Ousterhout (APOSD), Wei (arXiv:2604.18071), Ralph (arXiv:1303.5938), Homay (arXiv:2507.09596), King & Kimble (arXiv:cs/0406022)
> Related: ADR-020 (Conductor), ADR-022 (Risk Inference Engine), ADR-019 (Agentic Squad)

## Context

The Risk Inference Engine (ADR-022) provides reactive governance: it scores risk and gates execution. The Conductor (ADR-020) generates WorkflowPlans. Neither component reasons about *why* a particular design approach is appropriate for the task at hand.

Historical COEs reveal recurring failure patterns:
- **COE-052**: 20 cascading fixes because the agent did not understand the system (epistemic failure)
- **COE-052**: Reactive fix cycle where each fix created the next bug (paradigm mismatch)
- **COE-019**: God agent handling all concerns in one prompt (shallow module)
- **COE-019**: Over-decomposition risk with 20 agents proposed (cost-unjustified decomposition)

These failures trace to the absence of **design-level intelligence** — the system could detect risk but could not prescribe what to do differently.

## Decision

Implement five **SWE Synapses** — cognitive design principles extracted from peer-reviewed software engineering theory — as a pre-execution intelligence layer at `src/core/synapses/`.

### Architecture

```
Task Arrives (Data Contract)
  -> Synapse 5 (Epistemic): What do we KNOW?
    -> Synapse 3 (Paradigm): Should we plan or explore?
      -> Synapse 4 (Cost): Should we decompose?
        -> Synapse 2 (Harness): Which bundle fits?
          -> Synapse 1 (Depth): Are responsibilities deep enough?
            -> SynapseAssessment
              -> Risk Engine (3 new signals)
              -> Conductor (paradigm guidance)
              -> Fidelity Score (design_quality dimension)
```

### Five Synapses

| # | Synapse | Academic Source | What It Governs | Signal |
|---|---------|---------------|-----------------|--------|
| 1 | Deep Module Principle | Ousterhout (APOSD) | Interface depth, agent instruction quality | `interface_depth_ratio` (protective, -1.2) |
| 2 | Bundle Coherence | Wei (2026) | Architectural co-occurrence rules | Coherence violations (advisory) |
| 3 | Paradigm Selection | Ralph (2013) | Rational vs alternative design stance | `paradigm_fit_score` (protective, -0.8) |
| 4 | Decomposition Cost | Homay (2025) | When decomposition harms vs helps | `decomposition_cost_ratio` (risk, +1.0) |
| 5 | Epistemic Stance | King & Kimble (2004) | What the agent assumes about the domain | Epistemic sub-signals (advisory) |

### Risk Engine Extension (13 to 16 signals)

| # | Signal | Direction | Weight | Source |
|---|--------|-----------|--------|--------|
| 14 | `interface_depth_ratio` | Protective | -1.2 | Synapse 1 |
| 15 | `decomposition_cost_ratio` | Risk | +1.0 | Synapse 4 |
| 16 | `paradigm_fit_score` | Protective | -0.8 | Synapse 3 |

### Fidelity Score Extension (5 to 6 dimensions)

New `design_quality` dimension (25% weight) measures whether the execution applied sound design principles across all five synapses.

### Conductor Integration

The SynapseEngine fires twice in the Conductor pipeline:
1. **Pre-plan**: Determines paradigm, recommended agent count, and conductor guidance
2. **Post-plan**: Validates depth and coherence of the generated WorkflowPlan

## Alternatives Considered

### A: Hardcoded Rules in Conductor Prompt

Embed design principles directly in the Conductor's system prompt.

- Pro: No new module, zero latency overhead
- Con: Not measurable, not observable, not self-improving
- Con: Cannot feed signals back to Risk Engine

### B: LLM-Based Design Reviewer (Separate Agent)

Add a design review agent that evaluates plans before execution.

- Pro: Flexible, can reason about novel situations
- Con: Additional Bedrock call (~$0.02 + 200ms per task)
- Con: Non-deterministic — same plan could get different reviews
- Con: Cannot produce normalized signals for the Risk Engine

### C: Deterministic Synapse Engine (Selected)

Compute design intelligence via deterministic algorithms grounded in academic theory.

- Pro: Measurable (produces normalized [0,1] signals)
- Pro: Observable (every assessment is logged with full reasoning)
- Pro: Self-improving (signals feed into Risk Engine gradient descent)
- Pro: Zero external calls (pure computation, less than 1ms)
- Con: Cannot reason about truly novel design situations (mitigated: epistemic synapse detects novelty and recommends exploratory approach)

## Consequences

### Positive

- Transforms the pipeline from reactive (detect risk, then gate) to prescriptive (understand context, select approach, compose architecture)
- Prevents COE-052 class failures: low epistemic confidence now triggers escalation before execution
- Prevents COE-019 class failures: decomposition cost check prevents over-engineering
- Provides causal understanding of risk (not just correlation)
- Backward compatible: existing pipelines produce identical results when synapse data is not injected

### Negative

- Additional complexity in the orchestration layer (6 new files, approximately 800 LOC)
- Synapse thresholds require calibration period (30+ tasks for meaningful tuning)
- Design quality dimension changes Fidelity Score weights (existing scores shift slightly)

### Risks

| Risk | Mitigation |
|------|------------|
| Synapse thresholds too aggressive | Conservative defaults; all signals have sensible neutral values |
| Paradigm selector wrong for edge cases | Hybrid is the default; rational/alternative only trigger on strong signals |
| Decomposition cost blocks valid decomposition | Threshold set at 0.8 (generous); only consolidates when clearly over-decomposed |
| Fidelity Score regression | design_quality defaults to 0.5 when no synapse assessment provided |

## Well-Architected Alignment

| Pillar | Alignment |
|--------|-----------|
| OPS 4 | Every synapse assessment logged with full reasoning for observability |
| SEC 1 | Epistemic synapse detects knowledge artifacts and requires domain validation |
| REL 3 | Paradigm selection prevents wrong approach on novel problems (reduces CFR) |
| PERF 2 | Pure computation (less than 1ms), no external calls, no latency impact |
| COST 4 | Decomposition cost check prevents unnecessary agent dispatch ($0.02/agent saved) |
| SUS 2 | Fewer over-decomposed plans = fewer wasted tokens |

## Testing

Existing test suites updated:
- `tests/test_risk_inference_engine.py` — 33 tests (updated signal count assertions: 13 to 16)
- `tests/integration/test_conductor_e2e.py` — 13 tests (unchanged, backward compatible)

New module verified via integration scenarios:
- O1 simple bugfix: rational paradigm, high design quality (0.846)
- O5 novel feature: alternative paradigm, exploratory approach, 5 assumptions documented
- O3 entangled agents: hybrid paradigm, entanglement detected, lower design quality (0.490)

Command: `python3 -m pytest tests/test_risk_inference_engine.py tests/integration/test_conductor_e2e.py -v`
