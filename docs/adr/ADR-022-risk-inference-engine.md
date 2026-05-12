# ADR-022: Risk Inference Engine (PEC Blueprint Deployment)

> Status: **Accepted**
> Date: 2026-05-12
> Deciders: Staff SWE (rocand)
> Source: PEC Blueprint Chapters 1-2 (Bayesian Inference, DORA-Driven AI Mathematical Engineering)
> Related: ADR-013 (Enterprise-Grade Autonomy), ADR-019 (Agentic Squad), ADR-020 (Conductor)

## Context

The PEC (Probabilistic Engineering Controller) Blueprint defines a "Risk Inference Engine" that calculates P(Failure|Context) before agent execution begins. The current pipeline has:

- **Scope boundaries** (reject out-of-scope tasks) — binary pass/fail
- **Autonomy levels** (L1-L5) — static per project/task type
- **Failure modes** (FM-01 through FM-99) — post-hoc classification

What's missing is a **predictive risk layer** that uses historical data, code complexity, and DORA trends to score risk *before* execution starts. This enables:
1. Preventive blocking of high-risk tasks (instead of failing after 15 minutes)
2. Dynamic autonomy gate escalation based on quantified risk
3. Explainable risk decisions (SHAP-like contributions)
4. Self-improving weights via gradient descent on outcomes

## Decision

Implement a Risk Inference Engine at `src/core/risk/` with three modules:

### Architecture

```
Data Contract (from Router)
  → RiskSignalExtractor (Contextual Encoder)
    → 13 normalized signals [0, 1]
      → RiskInferenceEngine (Weighted Sigmoid)
        → Risk Score [0, 1]
          → Classification (pass/warn/escalate/block)
            → RiskExplanation (XAI Gateway)
```

### Components

| Module | Responsibility |
|--------|---------------|
| `risk_config.py` | Thresholds (τ), signal weights, operational parameters |
| `risk_signals.py` | Extracts 13 normalized signals from task context |
| `inference_engine.py` | Weighted sum → sigmoid → classification → explanation |

### Signal Categories (13 total)

| Category | Signals | Source |
|----------|---------|--------|
| Historical (3) | CFR, failure recurrence, repo hotspot | DORA metrics + failure_modes |
| Complexity (4) | file count, cyclomatic, dependency depth, cross-module | Data contract + catalog |
| DORA Trend (2) | lead time trend, deployment frequency | DORA metrics |
| Organism (1) | organism level (O1-O5) | Data contract |
| Protective (3) | test coverage, prior success, catalog confidence | Catalog + history |

### Thresholds

| Threshold | Value | Action |
|-----------|-------|--------|
| τ_warn | 0.08 | Emit warning to portal |
| τ_escalate | 0.15 | Tighten autonomy gates |
| τ_block | 0.40 | Eject to Staff Engineer |

### Recursive Optimizer

After each task completes, the engine adjusts weights via gradient descent:
- False negative (predicted safe, actually failed) → increase risk weights
- False positive (predicted risky, actually succeeded) → decrease risk weights
- Learning rate: 0.01, weight decay: 0.001, max magnitude: 5.0

## Integration Point

Between **Scope Check** and **Conductor** in the orchestrator pipeline:

```
Router → Scope Check → [RISK ENGINE] → Autonomy → Conductor → Execute
```

The risk assessment influences:
1. Whether the task proceeds at all (block)
2. Which autonomy gates are active (escalate)
3. Portal visibility (warn)
4. Conductor's complexity estimation (risk context)

## Consequences

### Positive

- Prevents costly failures before they happen (15+ min saved per blocked task)
- Quantified, explainable risk decisions (not gut feeling)
- Self-improving accuracy via outcome feedback
- Integrates with existing DORA metrics and failure modes
- Feature-flagged (RISK_ENGINE_ENABLED) for safe rollout

### Negative

- Additional computation per task (~5ms, negligible)
- Weights need initial calibration period (30+ tasks for meaningful learning)
- False positives during calibration may block valid tasks (mitigated: conservative τ_block=0.40)

### Risks

| Risk | Mitigation |
|------|------------|
| Insufficient historical data | Fallback score (0.05) when < 3 samples |
| Weight instability | Clamped to [-5, 5], weight decay regularization |
| Over-blocking during calibration | τ_block set conservatively at 0.40 |
| Stale weights after codebase evolution | 30-day rolling window, continuous learning |

## Well-Architected Alignment

| Pillar | Alignment |
|--------|-----------|
| OPS 4 | Risk assessment logged with full explanation for every task |
| SEC 1 | Prevents execution of high-risk changes without human review |
| REL 3 | Reduces change failure rate by blocking risky deployments |
| PERF 2 | Negligible overhead (sigmoid computation, no external calls) |
| COST 4 | Prevents wasted compute on tasks likely to fail |
| SUS 2 | Fewer failed executions = fewer wasted tokens |

## Testing

33 tests covering:
- Signal extraction normalization (8 tests)
- Core inference engine (6 tests)
- Threshold classification (5 tests)
- XAI explanation generation (4 tests)
- Recursive optimizer (3 tests)
- Serialization (4 tests)
- Integration scenarios (3 tests)

Command: `python3 -m pytest tests/test_risk_inference_engine.py -v`
