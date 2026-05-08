# ═══════════════════════════════════════════════════════════════════
# DynamoDB — Organism Ladder State
# ═══════════════════════════════════════════════════════════════════
#
# Tracks the organism complexity classification for each project.
# The organism ladder determines squad composition (how many agents,
# which tiers) based on task complexity classification.
#
# Schema:
#   PK: project_id (S) — repository/project identifier
#   SK: organism_key (S) — e.g., "current_level", "history#2026-05-08",
#       "calibration#latest", "threshold#promotion", "threshold#demotion"
#
# Organism Levels (from brain simulation design):
#   O1 (Reactive): Single agent, no memory, deterministic gates only
#   O2 (Adaptive): Single agent + memory recall, basic context
#   O3 (Cognitive): Multi-agent squad, shared context, adversarial review
#   O4 (Reflective): Full squad + fidelity scoring + perturbation testing
#   O5 (Autonomous): Self-optimizing squad + gate optimization + auto-scaling
#
# The task-intake-eval-agent queries this table to determine squad size
# and composition for each incoming task.
# ═══════════════════════════════════════════════════════════════════

resource "aws_dynamodb_table" "organism" {
  name         = "${var.name_prefix}-organism"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "project_id"
  range_key    = "organism_key"

  attribute {
    name = "project_id"
    type = "S"
  }

  attribute {
    name = "organism_key"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.environment == "prod"
  }

  tags = {
    Component   = "organism"
    Environment = var.environment
    DataClass   = "persistent"
  }
}

output "organism_table_name" {
  description = "Organism ladder DynamoDB table name"
  value       = aws_dynamodb_table.organism.name
}

output "organism_table_arn" {
  description = "Organism ladder DynamoDB table ARN"
  value       = aws_dynamodb_table.organism.arn
}
