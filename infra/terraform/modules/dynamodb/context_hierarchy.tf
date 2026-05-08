# ═══════════════════════════════════════════════════════════════════
# DynamoDB — Context Hierarchy
# ═══════════════════════════════════════════════════════════════════
#
# Cross-session learned context that persists across task executions.
# The orchestrator queries L1-L2 items at dispatch time and injects
# them into the SCD context_enrichment section.
#
# Schema:
#   PK: project_id (S) — repository/project identifier
#   SK: level#item_key (S) — e.g., "L1#architecture_style",
#       "L2#test_framework", "L3#auth_pattern_decision",
#       "L4#team_preference_naming", "L5#historical_incident_auth"
#
# Levels:
#   L1: Immutable facts (language, framework, architecture)
#   L2: Stable conventions (test framework, naming, CI tool)
#   L3: Decisions (ADR-backed choices, with confidence decay)
#   L4: Preferences (team style, with confidence decay)
#   L5: Historical (past incidents, patterns, with confidence decay)
#
# No TTL — project context is permanent. Confidence decay is
# application-level (managed by context_hierarchy.py).
# ═══════════════════════════════════════════════════════════════════

resource "aws_dynamodb_table" "context_hierarchy" {
  name         = "${var.name_prefix}-context-hierarchy"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "project_id"
  range_key    = "level_item_key"

  attribute {
    name = "project_id"
    type = "S"
  }

  attribute {
    name = "level_item_key"
    type = "S"
  }

  attribute {
    name = "level"
    type = "S"
  }

  global_secondary_index {
    name            = "level-index"
    hash_key        = "project_id"
    range_key       = "level"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.environment == "prod"
  }

  tags = {
    Component   = "context-hierarchy"
    Environment = var.environment
    DataClass   = "persistent"
  }
}

output "context_hierarchy_table_name" {
  description = "Context Hierarchy DynamoDB table name"
  value       = aws_dynamodb_table.context_hierarchy.name
}

output "context_hierarchy_table_arn" {
  description = "Context Hierarchy DynamoDB table ARN"
  value       = aws_dynamodb_table.context_hierarchy.arn
}
