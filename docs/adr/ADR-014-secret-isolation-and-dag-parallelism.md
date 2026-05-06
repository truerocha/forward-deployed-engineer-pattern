# ADR-014: Secret Isolation and DAG Parallelism for Agent Pipeline

## Status
Accepted

## Date
2026-05-06

## Context

The adversarial red-team evaluation (conversation record, 2026-05-06) identified five architectural flaws in the current factory orchestration. This ADR documents the two highest-priority fixes and their implementation plan.

### Problem 1: Secret Exposure to LLM Context

The current architecture injects ALM tokens (GitHub, GitLab, Asana) as **environment variables** into the ECS Fargate container via Secrets Manager references in the task definition. The Strands agent has full access to these env vars during execution. This means:

1. The LLM's context window can observe token values if the agent introspects its environment (e.g., via `run_shell_command("env")` or a prompt injection in an issue body).
2. The `pipeline_safety.py` PR diff review catches secrets **post-hoc** in committed code, but cannot prevent the agent from leaking tokens during execution.
3. All three ALM tokens are available to ALL agents (reconnaissance, engineering, reporting), violating least-privilege — the reconnaissance agent only needs read access, not write.

IronClaw's architecture ([github.com/nearai/ironclaw](https://github.com/nearai/ironclaw)) solves this with "credential injection at the network boundary" — secrets are never visible to the agent process, only injected into outbound HTTP requests by a proxy layer. While we do not integrate IronClaw (it's a complete runtime replacement, not a composable library), we adopt the same **principle**: tools fetch secrets at the moment of use and never expose them to the agent's reasoning context.

### Problem 2: Sequential Pipeline with Unused DAG Resolution

The `task_queue.py` module implements full DynamoDB-backed DAG dependency resolution (PENDING → READY promotion when dependencies complete, BLOCKED propagation on failure). However, the `Orchestrator._execute_pipeline` method is a simple sequential loop. The DAG resolution is never triggered during pipeline execution.

The current `agent_entrypoint.py` is a single-shot process (handles one event, exits). Fan-out parallelism requires an external trigger mechanism — not an in-process polling loop.

## Decision

### Step 1: Secret Isolation (Fetch-Use-Discard Pattern)

**Principle:** ALM tokens are fetched from Secrets Manager **inside** the `@tool` function at the moment of use, used for the HTTP request, and immediately discarded. The token never enters the agent's message history or context window.

**Changes:**

1. **`infra/docker/agents/tools.py`** — Refactor `update_github_issue`, `update_gitlab_issue`, `update_asana_task` to call a new `_fetch_alm_token(token_name)` helper that reads from Secrets Manager (with a short-lived cache to avoid repeated API calls within a single pipeline execution).

2. **`infra/docker/agents/tools.py`** — Add `_fetch_alm_token()` helper:
   - Reads from Secrets Manager secret `fde-{env}/alm-tokens`
   - Caches in a module-level dict with 5-minute TTL
   - Returns the token value (never logged, never returned to the agent)
   - Falls back to env var if Secrets Manager is unavailable (local dev mode)

3. **`infra/terraform/main.tf`** — Remove ALM token entries from the ECS task definition `secrets` block. Tokens are no longer injected as env vars.

4. **`infra/docker/agent_entrypoint.py`** — Remove the ALM token validation from `validate_environment()`. The tools self-validate at invocation time.

5. **`infra/terraform/main.tf`** — Add `secretsmanager:GetSecretValue` permission to the ECS task role (scoped to the `fde-{env}/alm-tokens` secret ARN).

**Security properties achieved:**
- The LLM never sees token values in its context window
- `run_shell_command("env")` does not reveal ALM tokens
- Prompt injection in issue bodies cannot exfiltrate tokens via agent reasoning
- Each tool function is self-contained — if a tool is not called, its token is never fetched
- Local development still works via env var fallback

**Well-Architected alignment (SEC pillar):**
- SEC 3: Credentials are not embedded in code or environment
- SEC 6: Least privilege — tokens fetched only when needed, not pre-loaded
- SEC 8: Defense in depth — even if the agent is compromised, tokens are not in memory

### Step 2: DAG Parallelism via DynamoDB Streams

**Principle:** Each ECS task remains single-shot. Fan-out happens via infrastructure (DynamoDB Streams → Lambda → EventBridge → ECS RunTask), not in-process loops.

**Changes:**

1. **`infra/terraform/dynamodb_streams.tf`** — Enable DynamoDB Streams on the task queue table (NEW_AND_OLD_IMAGES).

2. **`infra/terraform/lambda_fanout.tf`** — Lambda function that:
   - Triggers on task queue stream events
   - Filters for `status` transitions to "READY"
   - Calls `ecs:RunTask` with the READY task's spec as the `EVENTBRIDGE_EVENT` env var
   - Includes correlation_id for tracing

3. **`infra/docker/agents/orchestrator.py`** — After pipeline completion, call `task_queue.complete_task()` which triggers `_resolve_dependencies()` promoting dependent tasks to READY. The DynamoDB Stream picks up the transition.

4. **`infra/terraform/main.tf`** — Add IAM permissions for the Lambda to call `ecs:RunTask` and read from the DynamoDB Stream.

5. **`infra/docker/agents/orchestrator.py`** — Add `_enqueue_subtasks()` method that the Engineering Agent can call to decompose a complex task into parallel subtasks with dependency edges.

**Architecture:**
```
Pipeline completes → complete_task(task_id)
  → DynamoDB update: status = COMPLETED
  → _resolve_dependencies(): promotes dependents to READY
  → DynamoDB Stream: captures READY transition
  → Lambda (fan-out): reads READY task, calls ecs:RunTask
  → New ECS task starts with the promoted task's data contract
```

**Cost:** One Lambda invocation per task completion (~$0.0000002). One DynamoDB Stream read per transition. No always-on coordinator.

**Well-Architected alignment:**
- REL 9: Fault isolation — each task runs in its own ECS container
- PERF 3: Compute selection — serverless fan-out (Lambda) for coordination, Fargate for execution
- COST 5: No idle resources — Lambda is pay-per-invocation, no coordinator sitting idle

## Consequences

### Step 1 Consequences
- ALM tokens are no longer visible to the agent process at any point
- Local development requires either Secrets Manager access or env var fallback
- Token caching (5-min TTL) means a rotated token takes up to 5 minutes to propagate
- The `validate_environment()` function no longer checks for ALM tokens at startup — failures surface at tool invocation time (fail-fast per tool, not fail-fast at boot)

### Step 2 Consequences
- Tasks can execute in parallel when their dependencies are satisfied
- Each parallel task is fully isolated (separate ECS container, separate branch, separate correlation_id)
- The adversarial gate runs per-task at the aggregate level (not per-write) for parallel tasks
- Failed tasks propagate BLOCKED status to dependents via `_block_dependents()`
- New infrastructure: 1 Lambda function, 1 DynamoDB Stream, IAM permissions

### Trigger to Revisit
- **Step 1:** If Secrets Manager latency (p99 ~50ms) becomes a bottleneck for high-frequency ALM updates, consider a sidecar proxy pattern (similar to IronClaw's network boundary injection)
- **Step 2:** If fan-out exceeds 10 parallel tasks per pipeline, consider Step Functions for orchestration instead of Lambda + DynamoDB Streams

## Related
- ADR-009: AWS Cloud Infrastructure
- ADR-012: Over-Engineering Mitigations and Gap Closures
- ADR-013: Enterprise-Grade Autonomy and Observability
- IronClaw security model: [github.com/nearai/ironclaw](https://github.com/nearai/ironclaw) — credential injection at network boundary
- AWS Well-Architected SEC 3, SEC 6, SEC 8
