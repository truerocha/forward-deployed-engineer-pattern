# Task Plan: Harness Engineering Capabilities

> Status: Completed
> Date: 2026-05-05
> Completed: All 7 tasks implemented + E2E data travel validation
> Context: Gaps identified from OpenAI Harness Engineering post, Ralph Loop, Gas Town L8, and PLANS.md cookbook
> Priority: Items ordered by impact × feasibility
> Constraint: No fake code. Every item produces testable, integrated functionality.

---

## Session Context (read first)

Key files to read at session start:
1. `docs/design/data-contract-task-input.md` — the data contract
2. `docs/adr/ADR-013-enterprise-grade-autonomy-and-observability.md` — autonomy + failure modes
3. `infra/docker/agents/orchestrator.py` — the pipeline entry point
4. `infra/docker/agents/sdlc_gates.py` — inner loop gates
5. `infra/docker/agents/dora_metrics.py` — metrics collector
6. `docs/corrections-of-error.md` — the pattern these tasks resolve
7. `examples/web-app/test_data_journey.py` — existing integration tests

---

## Task 1: Execution Plans with Progress Tracking

**Source**: OpenAI PLANS.md cookbook
**Impact**: Allows L3/L4 tasks to resume from interruption point instead of restarting
**Effort**: Medium

### Problem
Current specs are static. The agent reads the spec, runs the pipeline, and reports. If interrupted (timeout, context limit, environment issue), the entire pipeline restarts from zero. For tasks that take 30+ minutes, this wastes compute and time.

### Acceptance Criteria
- [ ] A new `execution_plan.md` file is created in `.kiro/specs/{task_id}/` at pipeline start
- [ ] The plan contains: milestones (ordered), current_milestone (index), progress_log (append-only), decision_log (append-only)
- [ ] The Orchestrator reads the plan at start and resumes from `current_milestone` if the plan already exists
- [ ] Each pipeline stage updates `current_milestone` and appends to `progress_log` on completion
- [ ] If the pipeline is interrupted and restarted, it skips completed milestones
- [ ] BDD test validates: create plan → complete 2/4 milestones → simulate interruption → restart → resumes from milestone 3

### Implementation Approach
1. Create `infra/docker/agents/execution_plan.py` with `ExecutionPlan` dataclass (milestones, current, progress_log, decision_log)
2. Add `create_plan()`, `update_milestone()`, `resume_from_plan()` functions
3. Integrate into `orchestrator.py`: before pipeline starts, check if plan exists → if yes, resume; if no, create
4. Write to S3 (scoped by ProjectContext) so plans persist across container restarts
5. BDD test in `tests/test_execution_plans.py`

### Files to Create/Modify
- NEW: `infra/docker/agents/execution_plan.py`
- NEW: `tests/test_execution_plans.py`
- MODIFY: `infra/docker/agents/orchestrator.py` (add plan integration)
- MODIFY: `CHANGELOG.md`

---

## Task 2: Doc-Gardening Agent

**Source**: OpenAI Harness Engineering + COE-001 through COE-006 pattern
**Impact**: Resolves the most repeated pattern in COEs (docs drift from code)
**Effort**: Medium

### Problem
Documentation drifts from code. The COE log shows 6 of 9 entries are "doc was outdated." Currently, drift is detected manually. The OpenAI team runs a recurring agent that scans for stale docs and opens fix-up PRs.

### Acceptance Criteria
- [ ] A Kiro hook (`fde-doc-gardening`) runs on `userTriggered` event
- [ ] The hook scans: README.md (hook count, ADR count, flow count), design-document.md (components table), CHANGELOG.md (unreleased section not empty after changes)
- [ ] For each drift detected, the hook reports: file, what is stale, what the current state is
- [ ] The hook can be extended with custom checks (function registry pattern)
- [ ] BDD test validates: introduce a known drift (change hook count in code but not in README) → run gardening → drift detected

### Implementation Approach
1. Create `infra/docker/agents/doc_gardening.py` with `DocCheck` protocol and concrete checks:
   - `check_hook_count()`: count `.kiro/hooks/*.hook` files, compare against README badge
   - `check_adr_count()`: count `docs/adr/ADR-*.md` files, compare against README badge
   - `check_flow_count()`: count `docs/flows/*.md` files (excluding README), compare against README
   - `check_design_components()`: parse design-document.md components table, compare against actual modules in `infra/docker/agents/`
2. Create `.kiro/hooks/fde-doc-gardening.kiro.hook` (userTriggered, askAgent)
3. BDD test in `tests/test_doc_gardening.py`

### Files to Create/Modify
- NEW: `infra/docker/agents/doc_gardening.py`
- NEW: `.kiro/hooks/fde-doc-gardening.kiro.hook`
- NEW: `tests/test_doc_gardening.py`
- MODIFY: `CHANGELOG.md`

---

## Task 3: Custom Linters with Remediation Messages

**Source**: OpenAI "custom lints with error messages that inject remediation instructions into agent context"
**Impact**: Increases inner loop first-pass rate by giving the agent actionable fix instructions
**Effort**: Low

### Problem
Current SDLC gates run generic linters (ruff, eslint, go vet). When they report errors, the agent sees raw error output without remediation guidance. The OpenAI team writes custom linters where error messages ARE the remediation instructions.

### Acceptance Criteria
- [ ] `sdlc_gates.py` lint commands include a post-processing step that enriches error output with remediation hints
- [ ] For Python (ruff): common error codes (E501, F401, F841) get appended remediation text
- [ ] For TypeScript (eslint): common rules (no-unused-vars, no-console) get remediation text
- [ ] The enriched output is what the agent sees in the inner loop retry
- [ ] BDD test validates: given a lint error with code E501 → output includes "Remediation: split line at logical boundary or extract variable"

### Implementation Approach
1. Add `_enrich_lint_output(raw_output: str, tech_stack: list[str]) -> str` to `sdlc_gates.py`
2. Create a `REMEDIATION_MAP` dict mapping error codes to actionable instructions
3. Call `_enrich_lint_output()` before returning from `check_lint()`
4. BDD test in `tests/test_lint_remediation.py`

### Files to Create/Modify
- MODIFY: `infra/docker/agents/sdlc_gates.py` (add enrichment function + map)
- NEW: `tests/test_lint_remediation.py`
- MODIFY: `CHANGELOG.md`

---

## Task 4: Golden Principles + Garbage Collection

**Source**: OpenAI "golden principles encoded in repo + recurring cleanup process"
**Impact**: Prevents architectural drift in agent-generated code
**Effort**: Medium

### Problem
The agent replicates patterns that exist in the codebase — including inconsistent ones. Over time, this leads to drift. The OpenAI team encodes "taste invariants" and runs background tasks that scan for deviations and open cleanup PRs.

### Acceptance Criteria
- [ ] A `docs/design/golden-principles.md` document defines 5-10 mechanical rules (file size limits, naming conventions, structured logging, import ordering)
- [ ] A `infra/docker/agents/golden_principles.py` module validates code against these rules
- [ ] Each principle has: rule name, detection logic (function), remediation instruction
- [ ] A Kiro hook (`fde-golden-principles`) runs on `userTriggered` and reports deviations
- [ ] BDD test validates: introduce a deviation (file > 500 lines) → golden principles check detects it

### Implementation Approach
1. Create `docs/design/golden-principles.md` with initial rules:
   - Max file size: 500 lines (split if larger)
   - No `print()` in production code (use `logger`)
   - All modules have docstrings
   - No `import *`
   - Function max length: 50 lines
2. Create `infra/docker/agents/golden_principles.py` with `check_principles(workspace_dir)` → list of deviations
3. Create `.kiro/hooks/fde-golden-principles.kiro.hook`
4. BDD test in `tests/test_golden_principles.py`

### Files to Create/Modify
- NEW: `docs/design/golden-principles.md`
- NEW: `infra/docker/agents/golden_principles.py`
- NEW: `.kiro/hooks/fde-golden-principles.kiro.hook`
- NEW: `tests/test_golden_principles.py`
- MODIFY: `CHANGELOG.md`

---

## Task 5: Agent-to-Agent PR Review

**Source**: OpenAI "review effort handled agent-to-agent"
**Impact**: Reduces human review time by pre-screening PRs with LLM analysis
**Effort**: Medium

### Problem
The PR Diff Review Gate (`pipeline_safety.py`) checks for secrets and debug code (pattern matching). It does not review the logic, architecture alignment, or acceptance criteria conformance. The OpenAI team uses agent-to-agent review where one agent reviews another's output.

### Acceptance Criteria
- [ ] A new `review_pr_with_llm(diff_text, spec_content, constraints)` function in `pipeline_safety.py`
- [ ] The function sends the diff + spec + constraints to the LLM and asks: "Does this diff satisfy the acceptance criteria? Are there architectural concerns?"
- [ ] The LLM response is structured: {approved: bool, concerns: list[str], suggestions: list[str]}
- [ ] The review is opt-in (enabled via env var `PR_REVIEW_LLM_ENABLED=true`) — same pattern as constraint extraction
- [ ] BDD test validates: given a diff that introduces a console.log → LLM review flags it as concern

### Implementation Approach
1. Add `review_pr_with_llm()` to `infra/docker/agents/pipeline_safety.py`
2. Use the same Bedrock invocation pattern as the Constraint Extractor (direct `invoke_model`)
3. Structured prompt: "You are reviewing a PR. The spec says X. The constraints say Y. The diff is Z. Does this satisfy the acceptance criteria?"
4. Parse response into `PRReviewResult` dataclass
5. BDD test in `tests/test_pr_llm_review.py`

### Files to Create/Modify
- MODIFY: `infra/docker/agents/pipeline_safety.py` (add LLM review function)
- NEW: `tests/test_pr_llm_review.py`
- MODIFY: `CHANGELOG.md`

---

## Task 6: Observability Accessible to Agent

**Source**: OpenAI "logs, metrics, and traces exposed to Codex via local observability stack"
**Impact**: Gives the agent a feedback loop on its own performance
**Effort**: High

### Problem
The DORA metrics collector records data but the agent cannot read it. The agent has no awareness of its own performance history. The OpenAI team exposes observability data directly to the agent so it can reason about performance.

### Acceptance Criteria
- [ ] A new Strands tool `read_factory_metrics(task_id)` returns the DORA metrics for a task
- [ ] A new Strands tool `read_factory_health()` returns the latest Factory Health Report
- [ ] The Reporting Agent uses these tools to include performance data in completion reports
- [ ] The tools are read-only (no writes to metrics from agent tools)
- [ ] BDD test validates: agent tool returns structured metrics for a known task_id

### Implementation Approach
1. Add `read_factory_metrics` and `read_factory_health` as `@tool` functions in `infra/docker/agents/tools.py`
2. These tools call `DORACollector.get_task_metrics()` and `DORACollector.generate_factory_report()`
3. Add to `REPORTING_TOOLS` list so the Reporting Agent has access
4. BDD test in `tests/test_observability_tools.py`

### Files to Create/Modify
- MODIFY: `infra/docker/agents/tools.py` (add 2 new tools)
- NEW: `tests/test_observability_tools.py`
- MODIFY: `CHANGELOG.md`

---

## Task 7: Minimal Gates for L5 (Loop Mindset)

**Source**: OpenAI "corrections are cheap, waiting is expensive" + Ralph Loop
**Impact**: Increases throughput for L5 (Observer) tasks
**Effort**: Low

### Problem
L5 tasks (bugfixes, documentation) currently skip the adversarial gate but still run DoR Gate, constraint extraction (via fast path), and ship-readiness. For high-confidence L5 tasks, these gates add latency without proportional value.

### Acceptance Criteria
- [ ] L5 tasks with `confidence_level == "high"` skip: DoR Gate (scope boundaries already validated), ship-readiness (inner loop gates are sufficient)
- [ ] L5 tasks with `confidence_level != "high"` run all gates (safety net for low-confidence tasks)
- [ ] The `resolve_pipeline_gates()` function in `autonomy.py` implements this logic
- [ ] DORA metrics track whether minimal-gate L5 tasks have higher or lower CFR than full-gate L5 tasks
- [ ] BDD test validates: L5 + high confidence → only inner loop gates run

### Implementation Approach
1. Modify `autonomy.py` `resolve_pipeline_gates()` to accept `confidence_level` parameter
2. When `autonomy_level == "L5"` and `confidence_level == "high"`: skip `dor_gate` and `ship_readiness` from outer gates
3. Add `confidence_level` to the DORA metric dimensions for L5 tasks
4. BDD test in `tests/test_autonomy_level.py` (extend existing)

### Files to Create/Modify
- MODIFY: `infra/docker/agents/autonomy.py` (add confidence-aware gate resolution)
- MODIFY: `tests/test_autonomy_level.py` (add new scenarios)
- MODIFY: `CHANGELOG.md`

---

## Execution Order

| Sprint | Tasks | Rationale |
|--------|-------|-----------|
| 1 | Task 3 (Custom Linters) + Task 7 (Minimal Gates L5) | Low effort, immediate throughput improvement |
| 2 | Task 2 (Doc-Gardening) + Task 4 (Golden Principles) | Resolve the COE pattern, prevent drift |
| 3 | Task 1 (Execution Plans) | Enable long-running L3/L4 tasks |
| 4 | Task 5 (Agent PR Review) + Task 6 (Observability) | Higher effort, requires LLM integration |

---

## DoD Checklist (apply to each task)

Before committing any task:
- [ ] BDD tests written and passing
- [ ] CHANGELOG updated
- [ ] Language lint passes (zero violations)
- [ ] All existing tests still pass (`PYTHONPATH=infra/docker python3 -m pytest tests/ examples/`)
- [ ] ADR written if architectural decision was made
- [ ] Diagrams updated if data journey changed
- [ ] COE file updated if this resolves a known pattern

---

## References

- OpenAI Harness Engineering: https://openai.com/index/harness-engineering/
- OpenAI PLANS.md Cookbook: https://cookbook.openai.com/articles/codex_exec_plans
- Ralph Loop: https://ghuntley.com/loop/
- Steve Yegge Gas Town (8 Levels): https://steve-yegge.medium.com/welcome-to-gas-town-4f25ee16dd04
- ADR-013: Enterprise-Grade Autonomy
- ADR-012: Over-Engineering Mitigations
