# ═══════════════════════════════════════════════════════════════════
# ECS — Fidelity Agent Task Definition
# ═══════════════════════════════════════════════════════════════════
#
# Specialized task definition for the fde-fidelity-agent.
# Runs in the final stage (Stage 6) of the squad pipeline.
# Uses fast tier (Haiku) for deterministic scoring.
# Lightweight: 512MB / 256 CPU (scoring only, no code generation).
#
# Ref: docs/design/fde-core-brain-development.md Wave 2
# ═══════════════════════════════════════════════════════════════════

resource "aws_ecs_task_definition" "fidelity_agent" {
  family                   = "${var.name_prefix}-fidelity-agent"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "fidelity-agent"
      image     = "${var.ecr_repository_url}:fidelity-latest"
      essential = true

      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "ENVIRONMENT", value = var.environment },
        { name = "BEDROCK_MODEL_ID", value = "us.anthropic.claude-haiku-3-20240307-v1:0" },
        { name = "AGENT_ROLE", value = "fde-fidelity-agent" },
        { name = "AGENT_STAGE", value = "6" },
        { name = "MODEL_TIER", value = "fast" },
        { name = "SCD_TABLE", value = var.scd_table_name },
        { name = "METRICS_TABLE", value = var.metrics_table_name },
        { name = "MEMORY_TABLE", value = var.memory_table_name },
        { name = "KNOWLEDGE_TABLE", value = var.knowledge_table_name },
        { name = "FACTORY_BUCKET", value = var.artifacts_bucket },
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4318" },
        { name = "OTEL_SERVICE_NAME", value = "${var.name_prefix}-fidelity-agent" },
        { name = "OTEL_RESOURCE_ATTRIBUTES", value = "deployment.environment=${var.environment},service.namespace=fde-factory" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "fidelity-agent"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "test -f /tmp/agent_ready || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 10
      }
    }
  ])

  tags = {
    Component   = "fidelity-agent"
    Environment = var.environment
  }
}

output "fidelity_agent_task_definition_arn" {
  description = "ARN of the fidelity agent task definition"
  value       = aws_ecs_task_definition.fidelity_agent.arn
}
