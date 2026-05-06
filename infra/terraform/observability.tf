# ═══════════════════════════════════════════════════════════════════
# Observability — Dead-Letter Handler + CloudWatch Alarms (ADR-014, OPS 6 + OPS 8)
#
# Closes the observability gaps identified in ADR-014:
#   OPS 6: Telemetry for failed fan-out invocations
#   OPS 8: Automated response to pipeline failures via SNS alerts
#
# Components:
#   - SNS topic for operator notifications
#   - Dead-letter Lambda (processes failed dag_fanout events)
#   - CloudWatch alarms: fan-out errors, dead-letter invocations,
#     ECS task failures, DynamoDB throttles
#
# Well-Architected alignment:
#   OPS 6: Workload telemetry — structured alerts with correlation IDs
#   OPS 8: Respond to events — alarms trigger SNS → operator notification
#   REL 9: Fault isolation — dead-letter path prevents cascade failures
# ═══════════════════════════════════════════════════════════════════

# ─── Variables ───────────────────────────────────────────────────

variable "alert_email" {
  description = "Email address for pipeline failure alerts (leave empty to skip subscription)"
  type        = string
  default     = ""
}

variable "alarm_evaluation_periods" {
  description = "Number of periods to evaluate before triggering alarm"
  type        = number
  default     = 1
}

variable "alarm_period_seconds" {
  description = "CloudWatch alarm evaluation period in seconds"
  type        = number
  default     = 300
}

# ─── SNS Topic: Pipeline Failure Alerts ──────────────────────────

resource "aws_sns_topic" "pipeline_alerts" {
  name = "${local.name_prefix}-pipeline-alerts"

  tags = { Component = "observability" }
}

resource "aws_sns_topic_subscription" "email_alert" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.pipeline_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# ─── Dead-Letter Lambda Function ────────────────────────────────

resource "aws_lambda_function" "dead_letter" {
  function_name = "${local.name_prefix}-dead-letter"
  runtime       = "python3.12"
  handler       = "index.handler"
  timeout       = 30
  memory_size   = 128

  role = aws_iam_role.dead_letter_lambda.arn

  filename         = data.archive_file.dead_letter_zip.output_path
  source_code_hash = data.archive_file.dead_letter_zip.output_base64sha256

  environment {
    variables = {
      SNS_TOPIC_ARN    = aws_sns_topic.pipeline_alerts.arn
      TASK_QUEUE_TABLE = aws_dynamodb_table.task_queue.name
      ENVIRONMENT      = var.environment
    }
  }

  tags = { Component = "observability" }
}

data "archive_file" "dead_letter_zip" {
  type        = "zip"
  output_path = "${path.module}/.build/dead_letter.zip"

  source {
    content  = file("${path.module}/lambda/dead_letter/index.py")
    filename = "index.py"
  }
}

resource "aws_cloudwatch_log_group" "dead_letter" {
  name              = "/aws/lambda/${local.name_prefix}-dead-letter"
  retention_in_days = 30
  tags              = { Component = "observability" }
}

# ─── IAM Role for Dead-Letter Lambda ────────────────────────────

resource "aws_iam_role" "dead_letter_lambda" {
  name = "${local.name_prefix}-dead-letter-lambda"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })

  tags = { Component = "observability" }
}

resource "aws_iam_role_policy" "dead_letter_lambda" {
  name = "${local.name_prefix}-dead-letter-policy"
  role = aws_iam_role.dead_letter_lambda.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = [aws_sns_topic.pipeline_alerts.arn]
      },
      {
        Effect = "Allow"
        Action = ["dynamodb:UpdateItem"]
        Resource = [aws_dynamodb_table.task_queue.arn]
      },
      {
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes"
        ]
        Resource = [aws_sqs_queue.dead_letter.arn]
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

# ─── Lambda Permission: Allow dag_fanout to invoke dead-letter ───

resource "aws_lambda_permission" "dead_letter_invoke" {
  statement_id  = "AllowSQSTrigger"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.dead_letter.function_name
  principal     = "sqs.amazonaws.com"
  source_arn    = aws_sqs_queue.dead_letter.arn
}

# ─── SQS Dead-Letter Queue ──────────────────────────────────────
# Event source mappings only support SQS or SNS as on_failure destinations.
# Failed fan-out batches land here, then trigger the dead-letter Lambda.

resource "aws_sqs_queue" "dead_letter" {
  name                       = "${local.name_prefix}-dag-fanout-dlq"
  message_retention_seconds  = 1209600  # 14 days
  visibility_timeout_seconds = 60       # 2x the dead-letter Lambda timeout

  tags = { Component = "observability" }
}

# ─── SQS → Dead-Letter Lambda Event Source Mapping ───────────────

resource "aws_lambda_event_source_mapping" "dead_letter_from_sqs" {
  event_source_arn = aws_sqs_queue.dead_letter.arn
  function_name    = aws_lambda_function.dead_letter.arn
  batch_size       = 1
}

# ═══════════════════════════════════════════════════════════════════
# CloudWatch Alarms
# ═══════════════════════════════════════════════════════════════════

# ─── Alarm 1: DAG Fan-Out Lambda Errors ──────────────────────────
# Fires when the fan-out Lambda throws unhandled exceptions.
# This catches issues before they hit the dead-letter path.

resource "aws_cloudwatch_metric_alarm" "dag_fanout_errors" {
  alarm_name          = "${local.name_prefix}-dag-fanout-errors"
  alarm_description   = "DAG fan-out Lambda is failing — tasks may not be dispatched"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  period              = var.alarm_period_seconds
  threshold           = 0
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions = {
    FunctionName = aws_lambda_function.dag_fanout.function_name
  }

  alarm_actions = [aws_sns_topic.pipeline_alerts.arn]
  ok_actions    = [aws_sns_topic.pipeline_alerts.arn]

  tags = { Component = "observability" }
}

# ─── Alarm 2: Dead-Letter Lambda Invocations ────────────────────
# Any invocation of the dead-letter handler means a task permanently
# failed after all retries. This is always actionable.

resource "aws_cloudwatch_metric_alarm" "dead_letter_invocations" {
  alarm_name          = "${local.name_prefix}-dead-letter-invocations"
  alarm_description   = "Dead-letter handler invoked — tasks have permanently failed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  period              = var.alarm_period_seconds
  threshold           = 0
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/Lambda"
  metric_name = "Invocations"
  dimensions = {
    FunctionName = aws_lambda_function.dead_letter.function_name
  }

  alarm_actions = [aws_sns_topic.pipeline_alerts.arn]

  tags = { Component = "observability" }
}

# ─── Alarm 3: DAG Fan-Out Throttles ─────────────────────────────
# Lambda throttling means tasks are queuing up faster than they can
# be dispatched. May indicate a burst of READY transitions.

resource "aws_cloudwatch_metric_alarm" "dag_fanout_throttles" {
  alarm_name          = "${local.name_prefix}-dag-fanout-throttles"
  alarm_description   = "DAG fan-out Lambda is being throttled — task dispatch delayed"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  period              = var.alarm_period_seconds
  threshold           = 0
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/Lambda"
  metric_name = "Throttles"
  dimensions = {
    FunctionName = aws_lambda_function.dag_fanout.function_name
  }

  alarm_actions = [aws_sns_topic.pipeline_alerts.arn]

  tags = { Component = "observability" }
}

# ─── Alarm 4: DynamoDB Task Queue Read Throttles ─────────────────
# Throttled reads on the task queue table indicate capacity issues
# that could stall the entire pipeline.

resource "aws_cloudwatch_metric_alarm" "task_queue_read_throttles" {
  alarm_name          = "${local.name_prefix}-task-queue-read-throttles"
  alarm_description   = "DynamoDB task queue read throttling — pipeline may stall"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  period              = var.alarm_period_seconds
  threshold           = 0
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/DynamoDB"
  metric_name = "ReadThrottleEvents"
  dimensions = {
    TableName = aws_dynamodb_table.task_queue.name
  }

  alarm_actions = [aws_sns_topic.pipeline_alerts.arn]

  tags = { Component = "observability" }
}

# ─── Alarm 5: DynamoDB Task Queue Write Throttles ────────────────
# Throttled writes prevent task status updates (READY, COMPLETED, BLOCKED).

resource "aws_cloudwatch_metric_alarm" "task_queue_write_throttles" {
  alarm_name          = "${local.name_prefix}-task-queue-write-throttles"
  alarm_description   = "DynamoDB task queue write throttling — status updates failing"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = var.alarm_evaluation_periods
  period              = var.alarm_period_seconds
  threshold           = 0
  statistic           = "Sum"
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/DynamoDB"
  metric_name = "WriteThrottleEvents"
  dimensions = {
    TableName = aws_dynamodb_table.task_queue.name
  }

  alarm_actions = [aws_sns_topic.pipeline_alerts.arn]

  tags = { Component = "observability" }
}

# ─── Alarm 6: DAG Fan-Out Duration (approaching timeout) ────────
# If the fan-out Lambda is consistently running close to its 30s
# timeout, it may start timing out under load.

resource "aws_cloudwatch_metric_alarm" "dag_fanout_duration" {
  alarm_name          = "${local.name_prefix}-dag-fanout-duration"
  alarm_description   = "DAG fan-out Lambda duration approaching timeout (>20s avg)"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  period              = var.alarm_period_seconds
  threshold           = 20000  # 20 seconds (timeout is 30s)
  statistic           = "Average"
  treat_missing_data  = "notBreaching"

  namespace   = "AWS/Lambda"
  metric_name = "Duration"
  dimensions = {
    FunctionName = aws_lambda_function.dag_fanout.function_name
  }

  alarm_actions = [aws_sns_topic.pipeline_alerts.arn]

  tags = { Component = "observability" }
}
