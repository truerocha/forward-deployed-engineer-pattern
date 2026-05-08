# ═══════════════════════════════════════════════════════════════════
# DynamoDB — Unified Metrics Table
# ═══════════════════════════════════════════════════════════════════
#
# Append-only metrics store for all factory telemetry. Consolidates:
#   - DORA 4 metrics (per autonomy level): dora#{metric}#{autonomy_level}#{date}
#   - Cost tracking: cost#agent_name#{date}
#   - Verification metrics: verification#{metric}#{date}
#   - VSM timestamps: vsm#{task_id}#{stage}
#   - Autonomy adjustments: autonomy_adjustment#{timestamp}
#   - Maturity scores: maturity#{project_id}#{date}
#   - Trust metrics: trust#{metric}#{date}
#   - Net friction: friction#{project_id}#{date}
#   - Learning curve: learning#{project_id}#{metric}
#   - Gate feedback quality: gate_feedback#{gate_name}#{date}
#
# Schema:
#   PK: project_id (S) — repository/project identifier
#   SK: metric_key (S) — composite key encoding metric type + dimensions + timestamp
#
# GSI: metric_type-index for cross-project metric queries (dashboards).
# GSI: task-index for per-task metric aggregation.
# ═══════════════════════════════════════════════════════════════════

resource "aws_dynamodb_table" "metrics" {
  name         = "${var.name_prefix}-metrics"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "project_id"
  range_key    = "metric_key"

  attribute {
    name = "project_id"
    type = "S"
  }

  attribute {
    name = "metric_key"
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

  attribute {
    name = "task_id"
    type = "S"
  }

  global_secondary_index {
    name            = "metric-type-index"
    hash_key        = "metric_type"
    range_key       = "recorded_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "task-index"
    hash_key        = "task_id"
    range_key       = "recorded_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }

  tags = {
    Component   = "metrics"
    Environment = var.environment
    DataClass   = "append-only"
  }
}

output "metrics_table_name" {
  description = "Unified metrics DynamoDB table name"
  value       = aws_dynamodb_table.metrics.name
}

output "metrics_table_arn" {
  description = "Unified metrics DynamoDB table ARN"
  value       = aws_dynamodb_table.metrics.arn
}
