# ═══════════════════════════════════════════════════════════════════
# DynamoDB — Prompt Registry + Task Queue + Agent Lifecycle
# ═══════════════════════════════════════════════════════════════════

resource "aws_dynamodb_table" "prompt_registry" {
  name         = "${local.name_prefix}-prompt-registry"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "prompt_name"
  range_key    = "version"

  attribute {
    name = "prompt_name"
    type = "S"
  }

  attribute {
    name = "version"
    type = "N"
  }

  tags = { Component = "prompt-registry" }
}

resource "aws_dynamodb_table" "task_queue" {
  name         = "${local.name_prefix}-task-queue"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "task_id"

  # ADR-014: Enable streams for DAG fan-out (PENDING → READY transitions)
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "task_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "status-created-index"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  tags = { Component = "task-queue" }
}

# ─── Task Queue: Concurrency Config Items (seeded by Terraform) ──
# These CONFIG# items are read by the orchestrator at runtime via
# resolve_max_concurrent(). Changing them here and running terraform apply
# hot-tunes the system without Docker image redeploy.

resource "aws_dynamodb_table_item" "config_max_concurrent" {
  table_name = aws_dynamodb_table.task_queue.name
  hash_key   = aws_dynamodb_table.task_queue.hash_key

  item = jsonencode({
    task_id     = { S = "CONFIG#max_concurrent_tasks" }
    value       = { S = tostring(var.max_concurrent_tasks) }
    description = { S = "Max concurrent tasks per repo (managed by Terraform)" }
    status      = { S = "CONFIG" }
    updated_at  = { S = "2026-05-12T00:00:00Z" }
  })

  lifecycle {
    ignore_changes = [item]  # Don't overwrite if operator hot-tuned at runtime
  }
}

resource "aws_dynamodb_table_item" "config_budget_exceeded" {
  table_name = aws_dynamodb_table.task_queue.name
  hash_key   = aws_dynamodb_table.task_queue.hash_key

  item = jsonencode({
    task_id     = { S = "CONFIG#budget_exceeded" }
    value       = { S = "false" }
    description = { S = "Budget throttle flag. Set to 'true' to reduce concurrency to 1. Managed by cost-tracking automation." }
    status      = { S = "CONFIG" }
    updated_at  = { S = "2026-05-12T00:00:00Z" }
  })

  lifecycle {
    ignore_changes = [item]  # Don't overwrite — cost Lambda manages this
  }
}

resource "aws_dynamodb_table_item" "config_daily_budget_usd" {
  table_name = aws_dynamodb_table.task_queue.name
  hash_key   = aws_dynamodb_table.task_queue.hash_key

  item = jsonencode({
    task_id     = { S = "CONFIG#daily_budget_usd" }
    value       = { S = "5.00" }
    description = { S = "Daily cost budget in USD. When exceeded, budget_exceeded flag is set to true." }
    status      = { S = "CONFIG" }
    updated_at  = { S = "2026-05-12T00:00:00Z" }
  })

  lifecycle {
    ignore_changes = [item]  # Operator can adjust without redeploy
  }
}

resource "aws_dynamodb_table" "agent_lifecycle" {
  name         = "${local.name_prefix}-agent-lifecycle"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "agent_instance_id"

  attribute {
    name = "agent_instance_id"
    type = "S"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "status-created-index"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  tags = { Component = "agent-lifecycle" }
}

# ─── DORA Metrics ────────────────────────────────────────────────
# Append-only table for DORA + factory metrics.
# GSIs enable querying by task_id or metric_type for dashboards.

resource "aws_dynamodb_table" "dora_metrics" {
  name         = "${local.name_prefix}-dora-metrics"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "metric_id"

  attribute {
    name = "metric_id"
    type = "S"
  }

  attribute {
    name = "task_id"
    type = "S"
  }

  attribute {
    name = "metric_type"
    type = "S"
  }

  attribute {
    name = "recorded_at"
    type = "S"
  }

  global_secondary_index {
    name            = "task-index"
    hash_key        = "task_id"
    range_key       = "recorded_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "type-index"
    hash_key        = "metric_type"
    range_key       = "recorded_at"
    projection_type = "ALL"
  }

  tags = { Component = "dora-metrics" }
}
