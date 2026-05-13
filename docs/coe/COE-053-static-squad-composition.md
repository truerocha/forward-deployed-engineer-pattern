# COE-053: Static Squad Composition and Missing Documentation Artifacts

**Date**: 2026-05-13
**Severity**: Medium (quality degradation, not outage)
**Duration**: Since initial deployment (structural defect)
**Customer Impact**: PRs produced by the factory never included documentation updates. Squad composition was identical regardless of task characteristics.

## Summary

The CODE_FACTORY always selected the same 7-agent pipeline for every task and never produced documentation artifacts in PRs. Two structural defects in the squad composition harness caused this behavior.

## Timeline

| Time | Event |
|------|-------|
| 2026-05-13 10:26 | User observed identical pipeline for GH-93 (online enrichment task) |
| 2026-05-13 10:26 | Pipeline log confirmed static composition |
| 2026-05-13 10:30 | Investigation started: 5W2H + Red Team analysis |
| 2026-05-13 11:00 | Root causes identified (3 structural defects) |
| 2026-05-13 11:15 | Fixes applied and verified |
| 2026-05-13 11:20 | Docker image rebuilt and pushed |

## Root Cause (5 Whys)

### Defect 1: Same pipeline regardless of task

1. Why same pipeline? `SQUAD_MODE` defaulted to `"classic"`
2. Why classic? Dynamic mode was opt-in, never enabled in production
3. Why not enabled? Even when enabled, complexity was hardcoded to `"medium"`
4. Why hardcoded? No inference logic existed in the orchestrator
5. Why no inference? Original design assumed `task-intake-eval-agent` would run first (it never did)

### Defect 2: No documentation in PRs

1. Why no docs? `swe-tech-writer-agent` was never in the squad
2. Why not in squad? Only included for `infrastructure` or `high` complexity
3. Why only those? Medium feature squad (the default) excluded it from delivery group
4. Why excluded? Original design treated docs as optional for medium tasks
5. Why not caught? No structural gate validates that PRs include doc updates

### Defect 3: Conductor could not select documentation agents

1. Why not? `swe-tech-writer-agent` was absent from `_AGENT_CAPABILITIES` in `conductor.py`
2. Why absent? The Conductor was designed before the tech-writer agent existed
3. Why not updated? No mechanism detected the gap between squad_composer capabilities and Conductor capabilities

## Contributing Factors

- Feature flag `SQUAD_MODE` defaulting to `"classic"` meant the dynamic composition code was never exercised in production
- The `compose_default_squad()` function accepted a `complexity` parameter but the only caller hardcoded `"medium"`
- No test validated that different task types produce different squad compositions

## Fixes Applied

| Fix | File | Change |
|-----|------|--------|
| Default to dynamic mode | `infra/docker/agents/squad_composer.py` | `SQUAD_MODE` default: `"classic"` to `"dynamic"` |
| Infer complexity from signals | `infra/docker/agents/orchestrator.py` | New `_infer_task_complexity()` method |
| Tech-writer in medium squads | `infra/docker/agents/squad_composer.py` | Added to delivery group for medium features and bugfixes |
| Tech-writer in Conductor pool | `src/core/orchestration/conductor.py` | Added to `_AGENT_CAPABILITIES` |

## Action Items

| Category | Action | Owner | Status |
|----------|--------|-------|--------|
| Prevent | Add integration test: different task types produce different squad compositions | rocand | Open |
| Prevent | Add contract test: every agent in squad_composer AGENT_CAPABILITIES must exist in Conductor _AGENT_CAPABILITIES | rocand | Open |
| Detect | Add portal metric: unique squad compositions in last 24h (alert if always 1) | rocand | Open |
| Mitigate | swe-tech-writer-agent now in all medium+ squads | rocand | Done |

## Lessons Learned

1. **Feature flags that default to off are invisible defects.** If the new path is ready, make it the default. Keep the old path as the fallback via explicit opt-out.
2. **Hardcoded parameters in callers defeat parameterized functions.** The `compose_default_squad` function was well-designed with a `complexity` parameter, but its only caller hardcoded `"medium"`.
3. **Capability registries must be synchronized.** The squad_composer and Conductor had independent agent registries that drifted apart. A contract test would have caught this.
4. **Documentation is a delivery artifact, not an optional extra.** The tech-writer agent must be structural (always in the delivery group), not conditional on complexity.
