# ═══════════════════════════════════════════════════════════════════
# DAG Fan-Out — DynamoDB Streams + Lambda (ADR-014, Step 2)
#
# When a task transitions to READY in the task queue (after dependency
# resolution), a DynamoDB Stream event triggers this Lambda. The Lambda
# reads the READY task and calls ecs:RunTask to start a new agent
# container for parallel execution.
#
# Architecture:
#   complete_task() → DynamoDB update (COMPLETED)
#   → _resolve_dependencies() promotes dependents to READY
#   → DynamoDB Stream captures READY transition
#   → Lambda (this) reads READY task, calls ecs:RunTask
#   → New ECS task starts with the promoted task's data contract
#
# Cost: ~$0.0000002 per Lambda invocation. No always-on coordinator.
# ═══════════════════════════════════════════════════════════════════

# ─── Lambda Function: Fan-Out Trigger ────────────────────────────

resource "aws_lambda_function" "dag_fanout" {
  function_name = "${local.name_prefix}-dag-fanout"
  runtime       = "python3.12"
  handler       = "index.handler"
  timeout       = 30
  memory_size   = 128

  role = aws_iam_role.dag_fanout_lambda.arn

  filename         = data.archive_file.dag_fanout_zip.output_path
  source_code_hash = data.archive_file.dag_fanout_zip.output_base64sha256

  environment {
    variables = {
      ECS_CLUSTER_ARN     = aws_ecs_cluster.factory.arn
      TASK_DEFINITION_ARN = aws_ecs_task_definition.strands_agent.arn
      SUBNETS             = join(",", module.vpc.private_subnet_ids)
      SECURITY_GROUPS     = module.vpc.ecs_security_group_id
      ENVIRONMENT         = var.environment
    }
  }

  tags = { Component = "dag-fanout" }
}

# ─── Lambda Source Code (inline archive) ─────────────────────────

data "archive_file" "dag_fanout_zip" {
  type        = "zip"
  output_path = "${path.module}/.build/dag_fanout.zip"

  source {
    content  = file("${path.module}/lambda/dag_fanout/index.py")
    filename = "index.py"
  }
}

# ─── DynamoDB Stream → Lambda Event Source Mapping ───────────────

resource "aws_lambda_event_source_mapping" "task_queue_stream" {
  event_source_arn  = aws_dynamodb_table.task_queue.stream_arn
  function_name     = aws_lambda_function.dag_fanout.arn
  starting_position = "LATEST"
  batch_size        = 10

  # ADR-014 OPS 6+8: Route permanently failed batches to dead-letter queue
  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.dead_letter.arn
    }
  }

  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["MODIFY"]
        dynamodb = {
          NewImage = {
            status = { S = ["READY"] }
          }
          OldImage = {
            status = { S = ["PENDING"] }
          }
        }
      })
    }
  }
}

# ─── IAM Role for Lambda ────────────────────────────────────────

resource "aws_iam_role" "dag_fanout_lambda" {
  name = "${local.name_prefix}-dag-fanout-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Component = "dag-fanout" }
}

resource "aws_iam_role_policy" "dag_fanout_lambda" {
  name = "${local.name_prefix}-dag-fanout-policy"
  role = aws_iam_role.dag_fanout_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetRecords",
          "dynamodb:GetShardIterator",
          "dynamodb:DescribeStream",
          "dynamodb:ListStreams"
        ]
        Resource = ["${aws_dynamodb_table.task_queue.arn}/stream/*"]
      },
      {
        Effect = "Allow"
        Action = ["dynamodb:GetItem"]
        Resource = [aws_dynamodb_table.task_queue.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["ecs:RunTask"]
        Resource = [aws_ecs_task_definition.strands_agent.arn]
        Condition = {
          ArnLike = { "ecs:cluster" = aws_ecs_cluster.factory.arn }
        }
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.dead_letter.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["iam:PassRole"]
        Resource = [
          aws_iam_role.ecs_task_execution.arn,
          aws_iam_role.ecs_task.arn
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = ["arn:aws:logs:*:*:*"]
      }
    ]
  })
}

# ─── CloudWatch Log Group for Lambda ────────────────────────────

resource "aws_cloudwatch_log_group" "dag_fanout" {
  name              = "/aws/lambda/${local.name_prefix}-dag-fanout"
  retention_in_days = 14
  tags              = { Component = "dag-fanout" }
}
