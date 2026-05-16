# ═══════════════════════════════════════════════════════════════════
# Task Archiver Lambda — DynamoDB Streams → S3 Archive
# ═══════════════════════════════════════════════════════════════════
#
# Triggered by DynamoDB Streams on the task_queue table.
# Archives TTL-expired items to S3 before they are permanently deleted.
#
# Data flow:
#   DynamoDB TTL expires item → Stream REMOVE event → Archiver Lambda → S3
#
# WAF Alignment:
#   REL 9: Data preserved beyond DynamoDB TTL
#   COST 6: DynamoDB stays lean, S3 for cold storage
#   OPS 8: Historical data accessible for analysis
#
# Two-Way Door: disable by setting archiver_enabled = false
# ═══════════════════════════════════════════════════════════════════

variable "archiver_enabled" {
  description = "Enable the task archiver Lambda. Set false to disable without destroying."
  type        = bool
  default     = true
}

# ─── Package ─────────────────────────────────────────────────────

data "archive_file" "task_archiver" {
  type        = "zip"
  source_file = "${path.module}/lambda/task_archiver/index.py"
  output_path = "${path.module}/.build/task_archiver.zip"
}

# ─── IAM ─────────────────────────────────────────────────────────

resource "aws_iam_role" "task_archiver_lambda" {
  name = "${local.name_prefix}-task-archiver-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "task_archiver_dynamodb_streams" {
  name = "${local.name_prefix}-task-archiver-streams"
  role = aws_iam_role.task_archiver_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "dynamodb:GetRecords",
        "dynamodb:GetShardIterator",
        "dynamodb:DescribeStream",
        "dynamodb:ListStreams",
      ]
      Resource = [
        "${aws_dynamodb_table.task_queue.arn}/stream/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy" "task_archiver_s3" {
  name = "${local.name_prefix}-task-archiver-s3"
  role = aws_iam_role.task_archiver_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = [
        "s3:PutObject",
      ]
      Resource = [
        "${aws_s3_bucket.factory_artifacts.arn}/history/tasks/*",
      ]
    }]
  })
}

resource "aws_iam_role_policy_attachment" "task_archiver_logs" {
  role       = aws_iam_role.task_archiver_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# ─── Lambda Function ────────────────────────────────────────────

resource "aws_lambda_function" "task_archiver" {
  function_name    = "${local.name_prefix}-task-archiver"
  role             = aws_iam_role.task_archiver_lambda.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  timeout          = 60
  memory_size      = 256
  filename         = data.archive_file.task_archiver.output_path
  source_code_hash = data.archive_file.task_archiver.output_base64sha256

  environment {
    variables = {
      ARTIFACTS_BUCKET = aws_s3_bucket.factory_artifacts.id
      ARCHIVE_PREFIX   = "history/tasks/"
      ENVIRONMENT      = var.environment
    }
  }

  tags = { Component = "task-archiver" }
}

# ─── DynamoDB Streams Event Source Mapping ───────────────────────

resource "aws_lambda_event_source_mapping" "task_archiver_stream" {
  count = var.archiver_enabled ? 1 : 0

  event_source_arn  = aws_dynamodb_table.task_queue.stream_arn
  function_name     = aws_lambda_function.task_archiver.arn
  starting_position = "LATEST"
  batch_size        = 25
  maximum_batching_window_in_seconds = 30

  # Only process REMOVE events (TTL deletions)
  filter_criteria {
    filter {
      pattern = jsonencode({
        eventName = ["REMOVE"]
      })
    }
  }

  # Retry configuration for reliability
  maximum_retry_attempts             = 3
  maximum_record_age_in_seconds      = 86400  # 24h max age
  bisect_batch_on_function_error     = true
  parallelization_factor             = 2

  # Dead-letter for failed archival attempts
  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.archiver_dlq.arn
    }
  }
}

# ─── Dead Letter Queue (failed archival attempts) ───────────────

resource "aws_sqs_queue" "archiver_dlq" {
  name                      = "${local.name_prefix}-task-archiver-dlq"
  message_retention_seconds = 1209600  # 14 days

  tags = { Component = "task-archiver" }
}

resource "aws_iam_role_policy" "task_archiver_dlq" {
  name = "${local.name_prefix}-task-archiver-dlq"
  role = aws_iam_role.task_archiver_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Action = ["sqs:SendMessage"]
      Resource = [aws_sqs_queue.archiver_dlq.arn]
    }]
  })
}

# ─── Outputs ────────────────────────────────────────────────────

output "task_archiver_lambda_arn" {
  description = "ARN of the task archiver Lambda function"
  value       = aws_lambda_function.task_archiver.arn
}

output "task_archiver_dlq_url" {
  description = "URL of the archiver dead-letter queue"
  value       = aws_sqs_queue.archiver_dlq.url
}
