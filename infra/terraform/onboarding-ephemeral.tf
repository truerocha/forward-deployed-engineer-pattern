# =============================================================================
# Repo Onboarding Agent — Ephemeral Mode (Regulated Environments)
# Design ref: ADR-016 Ephemeral Catalog and Data Residency
#
# This module deploys the onboarding agent in ephemeral mode:
# - No S3 persistence (catalog stays in encrypted EFS volume)
# - No internet egress (Bedrock via VPC endpoint only)
# - Customer-controlled KMS encryption
# - TTL-based auto-destruction
# - Audit events to customer SIEM only
# =============================================================================

# --- Customer-Managed KMS Key for Catalog Encryption ---

resource "aws_kms_key" "onboarding_ephemeral" {
  count = var.enable_ephemeral_mode ? 1 : 0

  description             = "Encrypts onboarding catalog data at rest (customer-controlled)"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CustomerKeyAdmin"
        Effect = "Allow"
        Principal = {
          AWS = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"
        }
        Action   = "kms:*"
        Resource = "*"
      },
      {
        Sid    = "ECSTaskEncryptDecrypt"
        Effect = "Allow"
        Principal = {
          AWS = aws_iam_role.onboarding_ephemeral_task[0].arn
        }
        Action = [
          "kms:Encrypt",
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey"
        ]
        Resource = "*"
      }
    ]
  })

  tags = {
    Component   = "onboarding-agent-ephemeral"
    Environment = var.environment
    DataClass   = "confidential"
  }
}

resource "aws_kms_alias" "onboarding_ephemeral" {
  count = var.enable_ephemeral_mode ? 1 : 0

  name          = "alias/fde-${var.environment}-onboarding-catalog"
  target_key_id = aws_kms_key.onboarding_ephemeral[0].key_id
}

# --- EFS Filesystem (Encrypted, for Catalog Volume) ---

resource "aws_efs_file_system" "onboarding_ephemeral" {
  count = var.enable_ephemeral_mode ? 1 : 0

  creation_token = "fde-${var.environment}-onboarding-ephemeral"
  encrypted      = true
  kms_key_id     = aws_kms_key.onboarding_ephemeral[0].arn

  lifecycle_policy {
    transition_to_ia = "AFTER_1_DAY"
  }

  tags = {
    Component   = "onboarding-agent-ephemeral"
    Environment = var.environment
    DataClass   = "confidential"
    TTLHours    = var.ephemeral_ttl_hours
  }
}

resource "aws_efs_mount_target" "onboarding_ephemeral" {
  count = var.enable_ephemeral_mode ? length(module.vpc.private_subnet_ids) : 0

  file_system_id  = aws_efs_file_system.onboarding_ephemeral[0].id
  subnet_id       = module.vpc.private_subnet_ids[count.index]
  security_groups = [aws_security_group.efs_onboarding[0].id]
}

# --- Security Group for EFS (No Internet, ECS Only) ---

resource "aws_security_group" "efs_onboarding" {
  count = var.enable_ephemeral_mode ? 1 : 0

  name        = "fde-${var.environment}-efs-onboarding"
  description = "EFS access for onboarding agent ephemeral volume"
  vpc_id      = module.vpc.vpc_id

  ingress {
    description     = "NFS from ECS tasks"
    from_port       = 2049
    to_port         = 2049
    protocol        = "tcp"
    security_groups = [aws_security_group.ecs_ephemeral[0].id]
  }

  tags = {
    Component   = "onboarding-agent-ephemeral"
    Environment = var.environment
  }
}

# --- Security Group for ECS Ephemeral (No Internet Egress) ---

resource "aws_security_group" "ecs_ephemeral" {
  count = var.enable_ephemeral_mode ? 1 : 0

  name        = "fde-${var.environment}-ecs-onboarding-ephemeral"
  description = "ECS onboarding agent — no internet, VPC endpoints only"
  vpc_id      = module.vpc.vpc_id

  # Egress: EFS only
  egress {
    description = "EFS access"
    from_port   = 2049
    to_port     = 2049
    protocol    = "tcp"
    self        = true
  }

  # Egress: Bedrock VPC endpoint (HTTPS)
  egress {
    description = "Bedrock VPC endpoint"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  # NO internet egress — this is the key security control

  tags = {
    Component   = "onboarding-agent-ephemeral"
    Environment = var.environment
    Network     = "no-internet"
  }
}

# --- VPC Endpoint for Bedrock (No Public Internet) ---

resource "aws_vpc_endpoint" "bedrock_runtime" {
  count = var.enable_ephemeral_mode ? 1 : 0

  vpc_id              = module.vpc.vpc_id
  service_name        = "com.amazonaws.${var.aws_region}.bedrock-runtime"
  vpc_endpoint_type   = "Interface"
  private_dns_enabled = true
  subnet_ids          = module.vpc.private_subnet_ids
  security_group_ids  = [aws_security_group.ecs_ephemeral[0].id]

  tags = {
    Component   = "onboarding-agent-ephemeral"
    Environment = var.environment
  }
}

# --- IAM Role (Ephemeral — No S3, No Secrets Manager for ALM) ---

resource "aws_iam_role" "onboarding_ephemeral_task" {
  count = var.enable_ephemeral_mode ? 1 : 0

  name = "fde-${var.environment}-onboarding-ephemeral-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "ecs-tasks.amazonaws.com"
      }
    }]
  })

  tags = {
    Component   = "onboarding-agent-ephemeral"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "onboarding_ephemeral_permissions" {
  count = var.enable_ephemeral_mode ? 1 : 0

  name = "onboarding-ephemeral-permissions"
  role = aws_iam_role.onboarding_ephemeral_task[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "BedrockInvokeOnly"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
          "arn:aws:bedrock:us-east-1:${data.aws_caller_identity.current.account_id}:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0"
        ]
      },
      {
        Sid    = "KMSDecrypt"
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey"
        ]
        Resource = [aws_kms_key.onboarding_ephemeral[0].arn]
      },
      {
        Sid    = "EFSAccess"
        Effect = "Allow"
        Action = [
          "elasticfilesystem:ClientMount",
          "elasticfilesystem:ClientWrite"
        ]
        Resource = [aws_efs_file_system.onboarding_ephemeral[0].arn]
      }
      # NOTE: No S3 access, no Secrets Manager, no CloudWatch
    ]
  })
}

# --- ECS Task Definition (Ephemeral — Hardened) ---

resource "aws_ecs_task_definition" "onboarding_agent_ephemeral" {
  count = var.enable_ephemeral_mode ? 1 : 0

  family                   = "fde-${var.environment}-onboarding-agent-ephemeral"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"
  memory                   = "2048"
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.onboarding_ephemeral_task[0].arn

  volume {
    name = "catalog-volume"
    efs_volume_configuration {
      file_system_id     = aws_efs_file_system.onboarding_ephemeral[0].id
      transit_encryption = "ENABLED"
      authorization_config {
        iam = "ENABLED"
      }
    }
  }

  container_definitions = jsonencode([{
    name  = "onboarding-agent"
    image = "${aws_ecr_repository.onboarding_agent.repository_url}:ephemeral"
    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "CATALOG_MODE", value = "ephemeral" },
      { name = "EPHEMERAL_VOLUME_PATH", value = "/data" },
      { name = "EPHEMERAL_TTL_HOURS", value = tostring(var.ephemeral_ttl_hours) },
      { name = "EPHEMERAL_ENCRYPTION_KEY_ARN", value = aws_kms_key.onboarding_ephemeral[0].arn },
      { name = "AWS_REGION", value = var.aws_region }
    ]
    mountPoints = [{
      sourceVolume  = "catalog-volume"
      containerPath = "/data"
      readOnly      = false
    }]
    readonlyRootFilesystem = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/fde-${var.environment}-onboarding-ephemeral"
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "onboarding"
      }
    }
  }])

  tags = {
    Component   = "onboarding-agent-ephemeral"
    Environment = var.environment
    DataClass   = "confidential"
    Network     = "no-internet"
  }
}

# --- CloudWatch Log Group (Ephemeral — operational logs only) ---

resource "aws_cloudwatch_log_group" "onboarding_ephemeral" {
  count = var.enable_ephemeral_mode ? 1 : 0

  name              = "/ecs/fde-${var.environment}-onboarding-ephemeral"
  retention_in_days = 7  # Short retention — operational logs only

  tags = {
    Component   = "onboarding-agent-ephemeral"
    Environment = var.environment
  }
}

# --- Variables ---

variable "enable_ephemeral_mode" {
  description = "Enable ephemeral mode for regulated environments (no S3, encrypted volume)"
  type        = bool
  default     = false
}

variable "ephemeral_ttl_hours" {
  description = "Hours until ephemeral catalog volume is auto-destroyed"
  type        = number
  default     = 24
}
