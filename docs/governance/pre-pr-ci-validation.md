# Pre-PR CI Validation — Mandatory Instruction for AI Engineers

> Status: **enforced**
> Version: 1.0
> Date: 2026-05-13
> Scope: All AI Squad agents across all repositories
> Origin: COE-130 — PR #129 submitted with 14 pre-existing CI failures undetected

---

## The Rule

**Before creating a PR, the engineer MUST verify that the full CI test suite passes on the branch being submitted.**

A PR with a red CI gate is an automatic rejection. There is no "not my problem" category.

## Pre-PR Validation Protocol

1. **Discover** CI commands from `.github/workflows/*.yml` or `.gitlab-ci.yml`
2. **Run** the full CI suite locally (not just your module's tests)
3. **Triage** failures: caused by your code → fix it; pre-existing → still fix it
4. **Verify** all generated artifacts are committed and up to date
5. **Confirm** CI suite passes before running `gh pr create`

## Handling Pre-Existing Failures

| Option | Action |
|--------|--------|
| A (Preferred) | Fix them in your PR as a separate commit |
| B | Fix them in a prerequisite PR, wait for merge, rebase |
| C (Last resort) | Escalate — but NEVER submit into a known-red pipeline |

## Implementation

The `PrePRCIGate` class in `infra/docker/agents/pre_pr_ci_gate.py` enforces this:
- Discovers CI commands automatically from workflow files
- Runs them before PR creation
- Blocks submission if any required gate fails
- Classifies failures as pre-existing vs PR-caused
- Provides structured feedback for the agent to fix

Feature flag: `PRE_PR_CI_GATE_ENABLED` (default: true)

## Factory Issue Format Requirements

Issues must include `### Acceptance Criteria` (H3 heading) for the scope checker to accept them. Without it, the task is rejected with `no_halting_condition`.

## Ref

- COE-130: PR #129 submitted with 14 pre-existing CI failures
- ADR-027: Review Feedback Loop
- ADR-028: PR Reviewer Agent (Three-Level Review)
- ADR-029: Cognitive Autonomy Model
