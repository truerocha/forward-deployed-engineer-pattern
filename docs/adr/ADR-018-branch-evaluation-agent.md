# ADR-018: Branch Evaluation Agent — Automated Quality Gate for Merge Readiness

## Status
Accepted

## Date
2026-05-07

## Context

Feature branches require manual review to validate structural correctness, convention compliance, backward compatibility, domain alignment, adversarial resilience, test coverage, and documentation completeness. This is time-consuming, error-prone, and inconsistent across reviewers.

The factory already has FDE protocol with adversarial gates, DoR/DoD gates, pipeline-aware testing, and agent-to-agent PR review. What's missing: a deterministic, reproducible quality score that can gate merge decisions and enable auto-merge for low-risk changes.

### Design Space Explored

| Approach | Pros | Cons | Decision |
|----------|------|------|----------|
| Manual review only | Human judgment | Slow, inconsistent | Rejected |
| LLM-only review | Semantic understanding | Non-deterministic, expensive | Rejected |
| Static analysis only | Fast, deterministic | No domain awareness | Rejected |
| **Hybrid: deterministic scoring + pipeline awareness** | Reproducible, domain-aware, adversarial | Custom implementation | **Selected** |

## Decision

### 7-Dimension Scoring Engine with Auto-Merge

| Dimension | Weight | Measures |
|-----------|--------|----------|
| D1: Structural Validity | 20% | All artifacts parse and compile |
| D2: Convention Compliance | 15% | Project patterns followed |
| D3: Backward Compatibility | 20% | No breaking changes |
| D4: Domain Alignment | 15% | WAF/FDE protocol compliance |
| D5: Test Coverage | 15% | Tests exist and pass |
| D6: Adversarial Resilience | 10% | Defensive coding, no injection risks |
| D7: Documentation | 5% | Changes documented |

### Decision Thresholds

| Score | Verdict | Action |
|-------|---------|--------|
| >= 8.0 | PASS | Auto-merge eligible (L1/L2 only) |
| 7.0-7.9 | CONDITIONAL PASS | Merge eligible, human review recommended |
| 5.0-6.9 | CONDITIONAL FAIL | Merge blocked |
| < 5.0 | FAIL | Rework required |

### Veto Rules

- D1 < 3 -> automatic FAIL (broken artifacts)
- D3 < 3 -> automatic FAIL (breaking changes)
- D4 < 3 -> automatic FAIL (domain misalignment)

### Auto-Merge + Issue Lifecycle

When score >= 8.0 AND level <= L2 AND CI green:
1. Approve PR
2. Squash-merge to main
3. Close parent issue (completed)
4. Move issue to DONE in GitHub Projects V2

### Module Structure

```
infra/docker/agents/branch_evaluation/
  __init__.py, artifact_classifier.py, scoring_engine.py,
  code_evaluator.py, domain_evaluator.py, report_renderer.py,
  merge_handler.py, branch_evaluator.py, pipeline_graph.py
```

## Consequences

### Positive
- Deterministic scoring enables data-driven merge decisions
- Auto-merge for L1/L2 reduces review burden by ~60%
- Issue lifecycle automation closes the loop (spec -> code -> merge -> DONE)
- Adversarial checks catch security anti-patterns before merge
- Pipeline-aware evaluation prevents downstream breakage

### Negative
- Custom implementation requires maintenance
- No LLM in scoring = no semantic understanding of intent
- Auto-merge requires trust in scoring accuracy (calibration needed)
- GitHub Projects V2 GraphQL API complexity

### Risks
- False positives -> mitigated by shadow mode rollout
- False negatives -> mitigated by veto rules
- Auto-merge bugs -> mitigated by L1/L2 restriction + CI green
- Score gaming -> mitigated by pipeline-aware evaluation

## Related

- **ADR-003** — Agentic TDD
- **ADR-012** — Adversarial Review
- **ADR-013** — Enterprise-Grade Autonomy
- **ADR-017** — React Portal (reports in Reasoning view)
- **Design Doc** — `docs/design/branch-evaluation-agent.md`
- **WA OPS 5** — Reduce defects
- **WA REL 5** — Design interactions to prevent failures
- **WA SEC 6** — Protect compute
