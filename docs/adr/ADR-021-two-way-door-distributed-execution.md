# ADR-021: Two-Way Door Distributed Execution

> Status: **Accepted**
> Date: 2026-05-11
> Deciders: Staff SWE (rocand)
> Related: ADR-019 (Agentic Squad Architecture), ADR-020 (Conductor Orchestration Pattern)

## Context

The monolith execution mode (single `strands-agent` ECS task handling the full pipeline sequentially) has reached its scaling limits:

1. **No parallelization** — A single task processes agents sequentially. Complex tasks with independent subtasks (e.g., frontend + backend + tests) cannot run concurrently.
2. **No failure isolation** — A crash in one agent stage (e.g., OOM in reasoning) kills the entire pipeline. The task must restart from scratch.
3. **Single InProgress constraint** — The concurrency guard limits the monolith to one active task per project. Multiple InProgress tasks require independent execution contexts.

The distributed mode (ADR-019) solves these problems but introduces operational risk during the transition. We need a mechanism to switch between modes safely, with instant rollback capability.

## Decision

Implement an `execution_mode` Terraform variable (`monolith` | `distributed`) that switches the EventBridge target between the `strands-agent` and `orchestrator` ECS task definitions.

### Mechanism

```hcl
variable "execution_mode" {
  type        = string
  default     = "monolith"
  description = "Execution mode: monolith (single agent) or distributed (orchestrator + squad)"
  validation {
    condition     = contains(["monolith", "distributed"], var.execution_mode)
    error_message = "execution_mode must be 'monolith' or 'distributed'"
  }
}

resource "aws_cloudwatch_event_target" "factory_task" {
  rule     = aws_cloudwatch_event_rule.factory_trigger.name
  arn      = var.execution_mode == "distributed" ? module.ecs.orchestrator_cluster_arn : module.ecs.strands_cluster_arn
  role_arn = aws_iam_role.eventbridge_ecs.arn

  ecs_target {
    task_definition_arn = var.execution_mode == "distributed" ? module.ecs.orchestrator_task_def_arn : module.ecs.strands_task_def_arn
    # ...
  }
}
```

### Key Properties

- **Rollback in <30 seconds** — Switching from `distributed` back to `monolith` requires only `terraform apply -var="execution_mode=monolith"`. No image builds, no code changes, no Lambda updates.
- **Both images stay in ECR** — The `strands-agent` and `orchestrator` images are always built and pushed. Neither is deleted when the other is active.
- **Canary mode planned** — Future enhancement: `execution_mode = "canary"` routes a percentage of tasks to distributed while the rest stay on monolith. Requires weighted EventBridge targets or a routing Lambda.
- **Zero-downtime switching** — In-flight tasks on the old mode complete normally. Only new EventBridge invocations route to the new target.

## Alternatives Considered

### DynamoDB Runtime Config Flag

Store `execution_mode` in a DynamoDB config table. A routing Lambda reads the flag and dispatches to the appropriate task definition.

**Rejected** — Requires a new Lambda function (or modification to the DAG fan-out Lambda), adds a DynamoDB read to the hot path, and introduces a runtime failure mode (what if the config read fails?). The Terraform variable approach has zero runtime overhead.

### AWS Step Functions

Use Step Functions to orchestrate the mode selection and agent dispatch.

**Rejected** — Over-engineering for the current scale. Step Functions add state machine complexity, additional IAM roles, and per-transition costs. The binary switch via Terraform is simpler, cheaper, and sufficient until we need canary routing.

## Consequences

### Positive

- **Zero-downtime switching** — Both execution paths coexist in the infrastructure. Switching is a Terraform variable change, not a deployment.
- **IAM already permits both** — The EventBridge execution role has `ecs:RunTask` permission for both task definitions. No IAM changes needed for switching.
- **Operational simplicity** — The switch is a single variable in `terraform.tfvars`. No code changes, no image builds, no Lambda updates.
- **Instant rollback** — If distributed mode exhibits issues in production, reverting to monolith takes <30 seconds.

### Negative

- **Both task definitions consume resources** — ECR storage for both images, task definition revisions accumulate. Cost is negligible (<$1/month).
- **No gradual rollout** — The switch is binary (all traffic or none). Canary mode requires additional infrastructure (planned for future iteration).

### Neutral

- **Monitoring covers both paths** — CloudWatch alarms, OTEL traces, and portal observability work identically regardless of execution mode.
- **DynamoDB SCD schema unchanged** — Both modes write to the same task_events table with the same schema.
