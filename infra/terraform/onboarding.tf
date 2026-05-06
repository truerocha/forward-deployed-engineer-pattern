# =============================================================================
# Repo Onboarding Agent — ECS Task Definition, IAM Role, EventBridge Rule
# Design ref: §6 Infrastructure Design
# =============================================================================

# --- ECR Repository ---

resource "aws_ecr_repository" "onboarding_agent" {
  name                 = "fde-${var.environment}-onboarding-agent"
  image_tag_mutability = "MUTABLE"
  force_delete         = var.environment == "dev"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Component   = "onboarding-agent"
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# --- IAM Role (Least Privilege) ---

resource "aws_iam_role" "onboarding_task" {
  name = "fde-${var.environment}-onboarding-task-role"

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
    Component   = "onboarding-agent"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy" "onboarding_permissions" {
  name = "onboarding-permissions"
  role = aws_iam_role.onboarding_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3CatalogAccess"
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:PutObject", "s3:ListBucket"]
        Resource = [
          "${aws_s3_bucket.factory_artifacts.arn}/catalogs/*",
          aws_s3_bucket.factory_artifacts.arn
        ]
      },
      {
        Sid    = "SecretsManagerRead"
        Effect = "Allow"
        Action = ["secretsmanager:GetSecretValue"]
        Resource = [
          "arn:aws:secretsmanager:${var.aws_region}:${data.aws_caller_identity.current.account_id}:secret:fde-${var.environment}/alm-tokens*"
        ]
      },
      {
        Sid    = "BedrockInvoke"
        Effect = "Allow"
        Action = ["bedrock:InvokeModel"]
        Resource = [
          "arn:aws:bedrock:${var.aws_region}::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
          "arn:aws:bedrock:us-east-1:${data.aws_caller_identity.current.account_id}:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0"
        ]
      },
      {
        Sid    = "CloudWatchMetrics"
        Effect = "Allow"
        Action = ["cloudwatch:PutMetricData"]
        Resource = ["*"]
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "fde/onboarding"
          }
        }
      }
    ]
  })
}

# --- CloudWatch Log Group ---

resource "aws_cloudwatch_log_group" "onboarding" {
  name              = "/ecs/fde-${var.environment}-onboarding"
  retention_in_days = 30

  tags = {
    Component   = "onboarding-agent"
    Environment = var.environment
  }
}

# --- ECS Task Definition ---

resource "aws_ecs_task_definition" "onboarding_agent" {
  family                   = "fde-${var.environment}-onboarding-agent"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "1024"  # 1 vCPU
  memory                   = "2048"  # 2 GB
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.onboarding_task.arn

  container_definitions = jsonencode([{
    name  = "onboarding-agent"
    image = "${aws_ecr_repository.onboarding_agent.repository_url}:latest"
    environment = [
      { name = "ENVIRONMENT", value = var.environment },
      { name = "ARTIFACTS_BUCKET", value = aws_s3_bucket.factory_artifacts.id },
      { name = "AWS_REGION", value = var.aws_region }
    ]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.onboarding.name
        "awslogs-region"        = var.aws_region
        "awslogs-stream-prefix" = "onboarding"
      }
    }
  }])

  tags = {
    Component   = "onboarding-agent"
    Environment = var.environment
  }
}

# --- EventBridge Rule (REQ-7.2) ---

resource "aws_cloudwatch_event_rule" "onboarding_trigger" {
  name           = "fde-${var.environment}-onboarding-trigger"
  description    = "Triggers onboarding agent on fde.onboarding.requested events"
  event_bus_name = aws_cloudwatch_event_bus.factory.name

  event_pattern = jsonencode({
    source      = ["fde.onboarding"]
    detail-type = ["fde.onboarding.requested"]
  })

  tags = {
    Component   = "onboarding-agent"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_event_target" "onboarding_ecs" {
  rule           = aws_cloudwatch_event_rule.onboarding_trigger.name
  event_bus_name = aws_cloudwatch_event_bus.factory.name
  arn            = aws_ecs_cluster.factory.arn
  role_arn       = aws_iam_role.eventbridge_ecs.arn

  ecs_target {
    task_definition_arn = aws_ecs_task_definition.onboarding_agent.arn
    task_count          = 1
    launch_type         = "FARGATE"

    network_configuration {
      subnets          = module.vpc.private_subnet_ids
      security_groups  = [module.vpc.ecs_security_group_id]
      assign_public_ip = false
    }
  }

  input_transformer {
    input_paths = {
      repo_url       = "$.detail.repo_url"
      correlation_id = "$.detail.correlation_id"
      clone_depth    = "$.detail.clone_depth"
    }
    input_template = <<-EOF
      {
        "containerOverrides": [{
          "name": "onboarding-agent",
          "environment": [
            {"name": "REPO_URL", "value": <repo_url>},
            {"name": "CORRELATION_ID", "value": <correlation_id>},
            {"name": "CLONE_DEPTH", "value": <clone_depth>}
          ]
        }]
      }
    EOF
  }
}

# --- CloudWatch Alarms ---

resource "aws_cloudwatch_metric_alarm" "onboarding_stage_latency" {
  alarm_name          = "fde-${var.environment}-onboarding-stage-p99-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "stage_duration"
  namespace           = "fde/onboarding"
  period              = 300
  extended_statistic  = "p99"
  threshold           = 120000
  alarm_description   = "Onboarding stage P99 latency exceeds 2 minutes"

  dimensions = {
    mode = "cloud"
  }

  tags = {
    Component   = "onboarding-agent"
    Environment = var.environment
  }
}

resource "aws_cloudwatch_metric_alarm" "onboarding_total_duration" {
  alarm_name          = "fde-${var.environment}-onboarding-total-duration"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "total_duration"
  namespace           = "fde/onboarding"
  period              = 300
  statistic           = "Maximum"
  threshold           = 300000
  alarm_description   = "Onboarding total duration exceeds 5 minute budget"

  tags = {
    Component   = "onboarding-agent"
    Environment = var.environment
  }
}
