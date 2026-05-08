# Flow 15: Branch Evaluation Gate

> Automated quality scoring and merge decision for feature branches.

## Trigger

- **GitHub Action**: PR opened, synchronized, or reopened
- **Kiro Hook**: `fde-branch-eval` (userTriggered)
- **Orchestrator**: After `push_and_create_pr()` completes

## Flow

```mermaid
flowchart LR
    subgraph Trigger
        PR[PR Opened/Updated]
        Hook[Kiro Hook]
    end

    subgraph "Phase 0: Intake"
        Diff[Compute Diff<br/>main...HEAD]
        Classify[Classify Files<br/>9 artifact types]
        Edges[Map Pipeline Edges<br/>E1-E6]
    end

    subgraph "Phase 1-4: Evaluation"
        D1[D1: Structural<br/>ast.parse, JSON, HCL]
        D2[D2: Convention<br/>docstrings, naming]
        D3[D3: Compatibility<br/>git diff API removal]
        D4[D4: Domain<br/>WAF, FDE protocol]
        D5[D5: Test Coverage<br/>pytest execution]
        D6[D6: Adversarial<br/>secrets, eval, bare except]
        D7[D7: Documentation<br/>CHANGELOG, ADR]
    end

    subgraph "Phase 5: Decision"
        Score[Compute Aggregate<br/>Weighted 0-10]
        Veto{Veto Rule<br/>Triggered?}
        Verdict[Determine Verdict]
    end

    subgraph "Phase 6: Action"
        Report[Post PR Comment<br/>+ JSON Artifact]
        Check[Set GitHub Check<br/>pass/fail]
        AutoMerge{Score >= 8.0<br/>AND L1/L2?}
        Merge[Squash Merge]
        Done[Issue to DONE<br/>GitHub Projects]
    end

    PR --> Diff
    Hook --> Diff
    Diff --> Classify --> Edges
    Edges --> D1 & D2 & D3 & D4 & D5 & D6 & D7
    D1 & D2 & D3 & D4 & D5 & D6 & D7 --> Score
    Score --> Veto
    Veto -->|Yes| Verdict
    Veto -->|No| Verdict
    Verdict --> Report --> Check
    Check --> AutoMerge
    AutoMerge -->|Yes| Merge --> Done
    AutoMerge -->|No| End[Human Review]
```

## Scoring Model

| Dimension | Weight | Veto Threshold |
|-----------|--------|----------------|
| Structural Validity | 20% | < 3 |
| Convention Compliance | 15% | — |
| Backward Compatibility | 20% | < 3 |
| Domain Alignment | 15% | < 3 |
| Test Coverage | 15% | — |
| Adversarial Resilience | 10% | — |
| Documentation | 5% | — |

## Verdicts

| Score | Verdict | Merge | Auto-Merge |
|-------|---------|-------|------------|
| >= 8.0 | PASS | Yes | Yes (L1/L2) |
| 7.0-7.9 | CONDITIONAL PASS | Yes | No |
| 5.0-6.9 | CONDITIONAL FAIL | No | No |
| < 5.0 | FAIL | No | No |

## Issue Lifecycle (Post-Merge)

After successful auto-merge:
1. Close issue via REST API (state: closed, state_reason: completed)
2. Move to DONE via GraphQL (updateProjectV2ItemFieldValue mutation)

## Related

- [ADR-018](../adr/ADR-018-branch-evaluation-agent.md) — Architecture decision
- [Design Doc](../design/branch-evaluation-agent.md) — Full specification
- [Flow 04](04-adversarial-gate.md) — Adversarial gate (D6 formalizes this)
- [Flow 06](06-ship-readiness.md) — Ship readiness (evaluation is the automated equivalent)
