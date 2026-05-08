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
