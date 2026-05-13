# ═══════════════════════════════════════════════════════════════════
# ECS — Orchestrator Task Definition
# ═══════════════════════════════════════════════════════════════════
#
# Lightweight dispatcher (512MB) that receives work items from
# EventBridge, queries context/organism/memory, produces the Squad
# Manifest, and dispatches agent tasks via ECS RunTask.
#
# The orchestrator does NOT execute agent logic. It:
#   1. Receives work item (EventBridge trigger)
#   2. Queries System Maturity Score (validates amplifier readiness)
#   3. Queries Context Hierarchy (injects L1-L2 into SCD)
#   4. Queries Organism Ladder (determines complexity class)
#   5. Queries Memory Manager (injects relevant past decisions)
#   6. Checks Anti-Instability Loop (confirms autonomy level valid)
#   7. Dispatches Stage 1: task-intake-eval-agent
#   8. Monitors stage completion, dispatches subsequent stages
#   9. Dispatches Final Stage: fde-fidelity-agent + reporting-agent
#  10. Push + Create PR + Update portal + Track cost + Update VSM
#
# Resource sizing: 512MB / 256 CPU (0.25 vCPU) - dispatcher only.
# ═══════════════════════════════════════════════════════════════════

variable "orchestrator_cpu" {
  description = "CPU units for orchestrator (256 = 0.25 vCPU)"
  type        = string
  default     = "256"
}

variable "orchestrator_memory" {
  description = "Memory (MiB) for orchestrator"
  type        = string
  default     = "512"
}

variable "ecs_cluster_arn" {
  description = "ECS cluster ARN where agent tasks will be dispatched"
  type        = string
}

variable "private_subnet_ids" {
  description = "Private subnet IDs for agent task networking"
  type        = list(string)
}

variable "ecs_security_group_id" {
  description = "Security group ID for ECS tasks"
  type        = string
}

variable "context_hierarchy_table_name" {
  description = "DynamoDB context hierarchy table name"
  type        = string
}

variable "organism_table_name" {
  description = "DynamoDB organism table name"
  type        = string
}

# ─── Orchestrator Task Definition ────────────────────────────────
resource "aws_ecs_task_definition" "orchestrator" {
  family                   = "${var.name_prefix}-orchestrator"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.orchestrator_cpu
  memory                   = var.orchestrator_memory
  execution_role_arn       = var.execution_role_arn
  task_role_arn            = var.task_role_arn

  container_definitions = jsonencode([
    {
      name      = "orchestrator"
      image     = "${var.ecr_repository_url}:orchestrator-latest"
      essential = true

      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "ENVIRONMENT", value = var.environment },
        { name = "SCD_TABLE", value = var.scd_table_name },
        { name = "CONTEXT_HIERARCHY_TABLE", value = var.context_hierarchy_table_name },
        { name = "METRICS_TABLE", value = var.metrics_table_name },
        { name = "MEMORY_TABLE", value = var.memory_table_name },
        { name = "ORGANISM_TABLE", value = var.organism_table_name },
        { name = "KNOWLEDGE_TABLE", value = var.knowledge_table_name },
        { name = "FACTORY_BUCKET", value = var.artifacts_bucket },
        { name = "ECS_CLUSTER_ARN", value = var.ecs_cluster_arn },
        { name = "AGENT_TASK_FAMILY", value = aws_ecs_task_definition.agent.family },
        { name = "AGENT_SUBNETS", value = join(",", var.private_subnet_ids) },
        { name = "AGENT_SECURITY_GROUP", value = var.ecs_security_group_id },
        # Orchestrator-specific config
        { name = "MAX_CONCURRENT_AGENTS", value = "6" },
        { name = "STAGE_TIMEOUT_SECONDS", value = "600" },
        { name = "DISPATCH_MODE", value = "parallel-within-stage" },
        # Synapse 6: Heartbeat governance budgets
        { name = "HEARTBEAT_TOKEN_BUDGET", value = "5000" },
        { name = "ATTP_PROBE_BUDGET", value = "10000" },
        { name = "TOTAL_TASK_CEILING", value = "200000" },
        { name = "HEARTBEAT_ENABLED", value = "true" },
        # Observability
        { name = "OTEL_EXPORTER_OTLP_ENDPOINT", value = "http://localhost:4318" },
        { name = "OTEL_SERVICE_NAME", value = "${var.name_prefix}-orchestrator" },
        { name = "OTEL_RESOURCE_ATTRIBUTES", value = "deployment.environment=${var.environment},service.namespace=fde-factory" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "orchestrator"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "test -f /tmp/orchestrator_ready || exit 1"]
        interval    = 30
        timeout     = 5
        retries     = 3
        startPeriod = 15
      }
    },
    # ADOT Sidecar
    {
      name      = "adot-collector"
      image     = "${var.ecr_repository_url}:adot-v0.40.0"
      essential = false

      command = ["--config=/etc/ecs/ecs-xray.yaml"]

      portMappings = [
        { containerPort = 4317, protocol = "tcp" },
        { containerPort = 4318, protocol = "tcp" },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = var.log_group_name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "adot-orchestrator"
        }
      }
    }
  ])

  tags = {
    Component   = "orchestrator"
    Environment = var.environment
  }
}

# ─── Outputs ─────────────────────────────────────────────────────
output "orchestrator_task_definition_arn" {
  description = "ARN of the orchestrator task definition"
  value       = aws_ecs_task_definition.orchestrator.arn
}

output "orchestrator_task_definition_family" {
  description = "Family name of the orchestrator task definition"
  value       = aws_ecs_task_definition.orchestrator.family
}
