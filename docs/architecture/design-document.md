# Design Document: Autonomous Code Factory

> Forward Deployed Engineer — GenAI powered by Kiro
> Version: 3.0
> Date: 2026-05-04

## Executive Summary

This document describes the design of the Autonomous Code Factory, a system that enables a Staff Engineer to manage multiple software projects simultaneously by delegating implementation to AI agents governed by structured specifications, quality gates, and automated validation.

## Problem Statement

Standard AI-assisted development follows a reactive cycle: the human writes prompts, reviews generated code line-by-line, and manually coordinates between the IDE, ALM systems, CI/CD pipelines, and documentation. This approach does not scale beyond one project and produces locally correct changes that cascade into system-level issues.

## Requirements

### Functional Requirements

| No. | Role | Use Case | Priority |
|-----|------|----------|----------|
| 1.1 | Staff Engineer | Write specs in NLSpec format and mark as ready for execution | P0 |
| 1.2 | Staff Engineer | Approve test contracts before implementation begins | P0 |
| 1.3 | Staff Engineer | Trigger ship-readiness validation (Docker, E2E, holdout) | P0 |
| 1.4 | Staff Engineer | Trigger release (semantic commit, MR, ALM update) | P0 |
| 2.1 | Agent | Execute specs following the 4-phase protocol (Recon, Intake, Engineering, Completion) | P0 |
| 2.2 | Agent | Generate tests from spec scenarios before writing production code | P0 |
| 2.3 | Agent | Classify errors as CODE or ENVIRONMENT before modifying source | P0 |
| 2.4 | Agent | Generate hindsight notes after task completion | P1 |
| 2.5 | Agent | Sync progress to ALM via MCP | P1 |
| 3.1 | Factory | Support 3+ workspaces operating in parallel | P0 |
| 3.2 | Factory | Inherit global laws and credentials across all workspaces | P0 |
| 3.3 | Factory | Share cross-project knowledge via notes | P1 |
| 3.4 | Factory | Provide observability via Factory Health Report | P2 |

### Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Onboarding time for new project | Under 10 minutes |
| Hook validation overhead per write | Under 5 seconds |
| Ship-readiness Docker timeout | 5 minutes maximum |
| Note archival threshold | 90 days without PINNED tag |
| Meta-agent suggestion threshold | 2+ feedback items |
| Language compliance | Zero violent, trauma, or weasel words |

## Architecture

See `docs/architecture/autonomous-code-factory.png` for the system diagram.

### Components

| Component | Owned State | Responsibility |
|-----------|-------------|----------------|
| Spec Control Plane | `.kiro/specs/` | Stores work items, acceptance criteria, holdout scenarios |
| Hook Engine | `.kiro/hooks/` (13 hooks) | Gates execution at preToolUse, postToolUse, preTask, postTask, userTriggered |
| Steering Context | `.kiro/steering/` + `~/.kiro/steering/` | Provides project-specific and universal context to the agent |
| Notes System | `.kiro/notes/` + `~/.kiro/notes/shared/` | Persists cross-session knowledge with verification status |
| Meta System | `.kiro/meta/` | Stores human feedback and prompt refinement history |
| MCP Integration | `.kiro/settings/mcp.json` | Connects to GitHub, GitLab, Asana for ALM operations |
| Provision Script | `scripts/provision-workspace.sh` | Automates global setup and project onboarding |

### Information Flow

| From | To | Data |
|------|----|------|
| Staff Engineer | Spec Control Plane | NLSpec with BDD scenarios |
| Spec Control Plane | Hook Engine (DoR) | Spec readiness check |
| Hook Engine | Agent | Gate decisions (proceed/block/modify) |
| Agent | CI/CD | Code push to feature branch |
| CI/CD | Hook Engine (Circuit Breaker) | Build/test results |
| Agent | Notes System | Hindsight notes |
| Agent | MCP Integration | ALM updates, MR creation |
| Meta System | Hook Engine | Prompt improvement suggestions |

## Key Design Decisions

See `docs/adr/` for detailed Architecture Decision Records:
- ADR-001: Synaptic Engineering Foundation
- ADR-002: Spec as Control Plane
- ADR-003: Agentic TDD as Halting Condition
- ADR-004: Circuit Breaker for Error Classification
- ADR-005: Multi-Workspace Factory Topology
- ADR-006: Enterprise ALM Integration via MCP
- ADR-007: Cross-Session Learning via Notes

## Testing Design

| Scope | Command | Coverage |
|-------|---------|----------|
| Protocol E2E | `python3 -m pytest tests/test_fde_e2e_protocol.py` | All 13 hooks, steerings, design doc coherence |
| Quality Threshold | `python3 -m pytest tests/test_fde_quality_threshold.py` | Bare vs FDE response quality comparison |
| Language Lint | `python3 scripts/lint_language.py` | Violent, trauma, weasel word detection |

## Open Questions

1. How to handle inter-workspace dependency validation at scale (currently manual via interface contracts)
2. When to introduce Strands SDK for parallel agent orchestration
3. How to measure ROI of the factory compared to traditional development

## References

- Blueprint: `docs/blueprint/fde-blueprint-design.md`
- Adoption Guide: `docs/guides/fde-adoption-guide.md`
- Hook Deploy Guide: `docs/blueprint/fde-hooks-deploy-guide.md`
