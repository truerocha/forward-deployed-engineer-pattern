# ═══════════════════════════════════════════════════════════════════
# DynamoDB — Shared Context Document (SCD)
# ═══════════════════════════════════════════════════════════════════
#
# Intra-task context passing between agents within a single pipeline
# execution. Each task creates a new SCD item; agents read/write
# sections scoped by the Squad Manifest permissions.
#
# Schema:
#   PK: task_id (S) — unique task execution identifier
#   SK: section_key (S) — e.g., "context_enrichment", "stage_1_output",
#       "adversarial_findings", "fidelity_results"
#
# TTL: 7 days (task context is ephemeral; long-lived context goes to
#      context-hierarchy table).
#
# Conditional writes enforce version attribute to prevent parallel
# agent write conflicts (ADR-019: Squad Architecture).
# ═══════════════════════════════════════════════════════════════════

variable "name_prefix" {
  description = "Resource naming prefix (e.g., fde-dev)"
  type        = string
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

resource "aws_dynamodb_table" "scd" {
  name         = "${var.name_prefix}-scd"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "task_id"
  range_key    = "section_key"

  attribute {
    name = "task_id"
    type = "S"
  }

  attribute {
    name = "section_key"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.environment == "prod"
  }

  tags = {
    Component   = "scd"
    Environment = var.environment
    DataClass   = "ephemeral"
  }
}

output "scd_table_name" {
  description = "SCD DynamoDB table name"
  value       = aws_dynamodb_table.scd.name
}

output "scd_table_arn" {
  description = "SCD DynamoDB table ARN"
  value       = aws_dynamodb_table.scd.arn
}
