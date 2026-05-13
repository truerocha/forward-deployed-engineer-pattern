# ═══════════════════════════════════════════════════════════════════
# Webhook Router Lambda — Dynamic detail-type routing (COE-131 fix)
# ═══════════════════════════════════════════════════════════════════
#
# Replaces the direct EventBridge-PutEvents integration that hardcoded
# DetailType="issue.labeled" for ALL GitHub events (COE-131).
#
# This Lambda reads the X-GitHub-Event header (or GitLab object_kind,
# or Asana resource_type) and sets the correct detail-type on EventBridge.
#
# Future-proof: new event types just need a mapping entry in the Lambda
# code — no Terraform changes needed.
# ═══════════════════════════════════════════════════════════════════

data "archive_file" "webhook_router_zip" {
  type        = "zip"
  output_path = "${path.module}/.build/webhook_router.zip"

  source {
    content  = file("${path.module}/lambda/webhook_router/index.py")
    filename = "index.py"
  }
}

resource "aws_lambda_function" "webhook_router" {
  function_name    = "${local.name_prefix}-webhook-router"
  role             = aws_iam_role.webhook_router_role.arn
  handler          = "index.handler"
  runtime          = "python3.12"
  timeout          = 10
  memory_size      = 128
  filename         = data.archive_file.webhook_router_zip.output_path
  source_code_hash = data.archive_file.webhook_router_zip.output_base64sha256

  environment {
    variables = {
      EVENT_BUS_NAME  = aws_cloudwatch_event_bus.factory.name
      AWS_REGION_NAME = var.aws_region
      ENVIRONMENT     = var.environment
    }
  }

  tags = { Component = "webhook-router", COE = "131" }
}

resource "aws_cloudwatch_log_group" "webhook_router" {
  name              = "/aws/lambda/${local.name_prefix}-webhook-router"
  retention_in_days = 14
  tags              = { Component = "webhook-router" }
}

resource "aws_iam_role" "webhook_router_role" {
  name = "${local.name_prefix}-webhook-router-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  tags = { Component = "webhook-router" }
}

resource "aws_iam_role_policy" "webhook_router_policy" {
  name = "webhook-router-permissions"
  role = aws_iam_role.webhook_router_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["events:PutEvents"]
        Resource = [aws_cloudwatch_event_bus.factory.arn]
      },
      {
        Effect = "Allow"
        Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = ["arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:*"]
      }
    ]
  })
}

resource "aws_lambda_permission" "webhook_router_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.webhook_router.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.webhook.execution_arn}/*/*"
}
