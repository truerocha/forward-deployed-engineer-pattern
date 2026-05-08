# ═══════════════════════════════════════════════════════════════════
# DynamoDB — Knowledge Annotations + Quality Scores
# ═══════════════════════════════════════════════════════════════════
#
# Stores knowledge annotations (what governs each module) and
# data quality scores (freshness, completeness, consistency, accuracy)
# for all knowledge artifacts in the system.
#
# Schema:
#   PK: project_id (S) — repository/project identifier
#   SK: knowledge_key (S) — e.g.,
#       "annotation#src/core/orchestration/distributed_orchestrator.py",
#       "quality#config/mappings/fact_type_question_map.yaml",
#       "coverage#waf_security_corpus", "freshness#recommendation_templates"
#
# Knowledge annotation fields (stored in item attributes):
#   - module_path: file path of the governed module
#   - governing_artifacts: list of knowledge artifacts that govern this module
#   - domain_source_of_truth: canonical reference for validation
#   - last_validated: timestamp of last domain validation
#   - confidence: 0.0-1.0 confidence in annotation accuracy
#
# Quality score fields:
#   - freshness_score: 0-100 (based on last update date)
#   - completeness_score: 0-100 (coverage vs corpus)
#   - consistency_score: 0-100 (cross-reference integrity)
#   - accuracy_score: 0-100 (validated against source of truth)
#   - composite_score: weighted average of all four
#   - assessed_at: timestamp of last assessment
# ═══════════════════════════════════════════════════════════════════

resource "aws_dynamodb_table" "knowledge" {
  name         = "${var.name_prefix}-knowledge"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "project_id"
  range_key    = "knowledge_key"

  attribute {
    name = "project_id"
    type = "S"
  }

  attribute {
    name = "knowledge_key"
    type = "S"
  }

  attribute {
    name = "knowledge_type"
    type = "S"
  }

  attribute {
    name = "assessed_at"
    type = "S"
  }

  global_secondary_index {
    name            = "type-index"
    hash_key        = "project_id"
    range_key       = "knowledge_type"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "freshness-index"
    hash_key        = "project_id"
    range_key       = "assessed_at"
    projection_type = "KEYS_ONLY"
  }

  point_in_time_recovery {
    enabled = var.environment == "prod"
  }

  tags = {
    Component   = "knowledge"
    Environment = var.environment
    DataClass   = "persistent"
  }
}

output "knowledge_table_name" {
  description = "Knowledge annotations DynamoDB table name"
  value       = aws_dynamodb_table.knowledge.name
}

output "knowledge_table_arn" {
  description = "Knowledge annotations DynamoDB table ARN"
  value       = aws_dynamodb_table.knowledge.arn
}
