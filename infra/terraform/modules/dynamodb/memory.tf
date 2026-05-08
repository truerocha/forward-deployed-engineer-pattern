# ═══════════════════════════════════════════════════════════════════
# DynamoDB — Structured Memory
# ═══════════════════════════════════════════════════════════════════
#
# Fast-lookup structured memory for recent decisions, task outcomes,
# and error patterns. Complements the Bedrock KB semantic store.
#
# Schema:
#   PK: project_id (S) — repository/project identifier
#   SK: memory_type#timestamp (S) — e.g., "decision#2026-05-08T10:30:00Z",
#       "outcome#2026-05-07T14:00:00Z", "error_pattern#2026-05-06T09:00:00Z",
#       "adr#ADR-019", "learning#auth_flow_v2"
#
# Memory types:
#   - decision: Architecture/design decisions with rationale
#   - outcome: Task execution results (success/failure + context)
#   - error_pattern: Recurring error patterns with resolution
#   - adr: ADR summaries for quick recall
#   - learning: Cross-session learned patterns
#
# Consolidation: Weekly job merges redundant memories (managed by
# memory_manager.py consolidate() method).
# ═══════════════════════════════════════════════════════════════════

resource "aws_dynamodb_table" "memory" {
  name         = "${var.name_prefix}-memory"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "project_id"
  range_key    = "memory_key"

  attribute {
    name = "project_id"
    type = "S"
  }

  attribute {
    name = "memory_key"
    type = "S"
  }

  attribute {
    name = "memory_type"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "type-index"
    hash_key        = "project_id"
    range_key       = "memory_type"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "recency-index"
    hash_key        = "project_id"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.environment == "prod"
  }

  tags = {
    Component   = "memory"
    Environment = var.environment
    DataClass   = "persistent"
  }
}

output "memory_table_name" {
  description = "Memory DynamoDB table name"
  value       = aws_dynamodb_table.memory.name
}

output "memory_table_arn" {
  description = "Memory DynamoDB table ARN"
  value       = aws_dynamodb_table.memory.arn
}
