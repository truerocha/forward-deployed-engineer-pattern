# ═══════════════════════════════════════════════════════════════════
# Distributed Infrastructure — Wave 1 Module Wiring
# ═══════════════════════════════════════════════════════════════════
#
# Connects the EFS and DynamoDB modules created for the distributed
# agent execution model (fde-core-brain-development.md, Wave 1).
#
# Activities: 1.01-1.08
# ═══════════════════════════════════════════════════════════════════

# ─── EFS: Agent Workspaces ───────────────────────────────────────
module "efs" {
  source = "./modules/efs"

  name_prefix           = local.name_prefix
  environment           = var.environment
  vpc_id                = module.vpc.vpc_id
  private_subnet_ids    = module.vpc.private_subnet_ids
  ecs_security_group_id = module.vpc.ecs_security_group_id

  # Use bursting for dev/staging, provisioned for prod
  throughput_mode              = var.environment == "prod" ? "provisioned" : "bursting"
  provisioned_throughput_mibps = var.environment == "prod" ? 128 : 128
}

# ─── DynamoDB: Distributed Context Tables ────────────────────────
module "dynamodb_distributed" {
  source = "./modules/dynamodb"

  name_prefix = local.name_prefix
  environment = var.environment
}

# ─── ECS: Distributed Agent + Orchestrator Task Definitions ─────
module "ecs_distributed" {
  source = "./modules/ecs"

  name_prefix         = local.name_prefix
  environment         = var.environment
  ecr_repository_url  = aws_ecr_repository.strands_agent.repository_url
  execution_role_arn  = aws_iam_role.ecs_task_execution.arn
  task_role_arn       = aws_iam_role.ecs_task.arn
  log_group_name      = aws_cloudwatch_log_group.factory.name
  aws_region          = local.region
  bedrock_model_id    = var.bedrock_model_id
  bedrock_model_reasoning = var.bedrock_model_reasoning
  bedrock_model_standard  = var.bedrock_model_standard
  bedrock_model_fast      = var.bedrock_model_fast
  artifacts_bucket    = aws_s3_bucket.factory_artifacts.id

  # EFS integration
  efs_file_system_id  = module.efs.file_system_id
  efs_access_point_id = module.efs.access_point_id

  # DynamoDB tables
  scd_table_name               = module.dynamodb_distributed.scd_table_name
  metrics_table_name           = module.dynamodb_distributed.metrics_table_name
  memory_table_name            = module.dynamodb_distributed.memory_table_name
  knowledge_table_name         = module.dynamodb_distributed.knowledge_table_name
  context_hierarchy_table_name = module.dynamodb_distributed.context_hierarchy_table_name
  organism_table_name          = module.dynamodb_distributed.organism_table_name

  # Orchestrator networking
  ecs_cluster_arn       = aws_ecs_cluster.factory.arn
  private_subnet_ids    = module.vpc.private_subnet_ids
  ecs_security_group_id = module.vpc.ecs_security_group_id
}

# ─── IAM: ECS RunTask permission for Orchestrator ────────────────
resource "aws_iam_role_policy" "ecs_task_run_task" {
  name = "${local.name_prefix}-ecs-run-task"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecs:RunTask",
          "ecs:StopTask",
          "ecs:DescribeTasks"
        ]
        Resource = [
          module.ecs_distributed.agent_task_definition_arn,
          "arn:aws:ecs:${local.region}:${local.account_id}:task/${aws_ecs_cluster.factory.name}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [
          aws_iam_role.ecs_task_execution.arn,
          aws_iam_role.ecs_task.arn
        ]
        Condition = {
          StringEquals = {
            "iam:PassedToService" = "ecs-tasks.amazonaws.com"
          }
        }
      }
    ]
  })
}

# ─── IAM: EFS Access for ECS Tasks ──────────────────────────────
resource "aws_iam_role_policy" "ecs_task_efs" {
  name = "${local.name_prefix}-efs-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "elasticfilesystem:ClientMount",
          "elasticfilesystem:ClientWrite",
          "elasticfilesystem:ClientRootAccess"
        ]
        Resource = [module.efs.file_system_arn]
        Condition = {
          StringEquals = {
            "elasticfilesystem:AccessPointArn" = module.efs.access_point_arn
          }
        }
      }
    ]
  })
}

# ─── IAM: DynamoDB Access for New Tables ─────────────────────────
resource "aws_iam_role_policy" "ecs_task_dynamodb_distributed" {
  name = "${local.name_prefix}-dynamodb-distributed-access"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem",
        "dynamodb:DeleteItem", "dynamodb:Query", "dynamodb:Scan",
        "dynamodb:ConditionCheckItem"
      ]
      Resource = [
        module.dynamodb_distributed.scd_table_arn,
        "${module.dynamodb_distributed.scd_table_arn}/index/*",
        module.dynamodb_distributed.context_hierarchy_table_arn,
        "${module.dynamodb_distributed.context_hierarchy_table_arn}/index/*",
        module.dynamodb_distributed.metrics_table_arn,
        "${module.dynamodb_distributed.metrics_table_arn}/index/*",
        module.dynamodb_distributed.memory_table_arn,
        "${module.dynamodb_distributed.memory_table_arn}/index/*",
        module.dynamodb_distributed.organism_table_arn,
        "${module.dynamodb_distributed.organism_table_arn}/index/*",
        module.dynamodb_distributed.knowledge_table_arn,
        "${module.dynamodb_distributed.knowledge_table_arn}/index/*",
      ]
    }]
  })
}
