"""
Dead-Letter Handler — Processes failed DAG fan-out invocations (ADR-014, OPS 6 + OPS 8).

When the dag_fanout Lambda fails after all DynamoDB Stream retries are exhausted,
the failed event batch lands here via Lambda's on_failure destination. This handler:

1. Extracts failed task metadata from the stream records
2. Publishes a structured alert to SNS for operator notification
3. Logs the failure with full context for post-mortem analysis
4. Optionally marks the task as DEAD_LETTER in DynamoDB for visibility

Architecture:
  DynamoDB Stream → dag_fanout Lambda (fails 3x)
  → on_failure destination → this Lambda
  → SNS notification + DynamoDB status update

Well-Architected alignment:
  OPS 6: Telemetry — structured failure events with correlation IDs
  OPS 8: Respond to events — automated alerting on pipeline failures
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

sns = boto3.client("sns")
dynamodb = boto3.resource("dynamodb")

SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
TASK_QUEUE_TABLE = os.environ.get("TASK_QUEUE_TABLE", "")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")


def handler(event, context):
    """Process failed DAG fan-out events from the on_failure destination.

    The event structure from Lambda's on_failure async invocation:
    {
        "version": "1.0",
        "timestamp": "...",
        "requestContext": {
            "requestId": "...",
            "functionArn": "...",
            "condition": "RetriesExhausted",
            "approximateInvokeCount": 3
        },
        "requestPayload": { ... original DynamoDB Stream event ... },
        "responseContext": {
            "statusCode": 200,
            "executedVersion": "$LATEST",
            "functionError": "Unhandled"
        },
        "responsePayload": { "errorMessage": "...", "errorType": "..." }
    }
    """
    logger.info("Dead-letter handler invoked: %s", json.dumps(event, default=str))

    failures_processed = 0

    # SQS event source mapping wraps messages in Records[].body
    if "Records" in event and event["Records"] and "body" in event["Records"][0]:
        # SQS trigger — each record's body contains the on_failure payload
        for sqs_record in event["Records"]:
            try:
                failure_event = json.loads(sqs_record["body"])
                failures_processed += _process_failure_record(failure_event, context)
            except (json.JSONDecodeError, KeyError) as e:
                logger.error("Failed to parse SQS record body: %s", e)
                failures_processed += 1
    elif "requestPayload" in event:
        # Direct on_failure destination format (testing)
        failures_processed += _process_failure_record(event, context)
    else:
        logger.warning("Unexpected event format: %s", json.dumps(event, default=str))

    logger.info("Dead-letter processing complete: %d failures handled", failures_processed)
    return {"processed": failures_processed}


def _process_failure_record(failure_event: dict, context) -> int:
    """Process a single failure record: extract tasks, notify, update status."""
    request_payload = failure_event.get("requestPayload", {})
    response_payload = failure_event.get("responsePayload", {})
    request_context = failure_event.get("requestContext", {})

    error_message = response_payload.get("errorMessage", "Unknown error")
    error_type = response_payload.get("errorType", "Unknown")
    invoke_count = request_context.get("approximateInvokeCount", 0)
    condition = request_context.get("condition", "Unknown")

    # Extract task IDs from the original stream records
    records = request_payload.get("Records", [])
    task_ids = []

    for record in records:
        task_id = _extract_task_id(record)
        if task_id != "unknown":
            task_ids.append(task_id)
            _mark_task_dead_letter(task_id, error_message)

    # Build structured alert
    alert = {
        "alert_type": "dag_fanout_dead_letter",
        "environment": ENVIRONMENT,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "severity": "HIGH",
        "condition": condition,
        "approximate_invoke_count": invoke_count,
        "error_type": error_type,
        "error_message": error_message,
        "affected_tasks": task_ids,
        "task_count": len(task_ids),
        "lambda_request_id": context.aws_request_id if context else "local",
        "source_function": request_context.get("functionArn", "unknown"),
    }

    # Publish to SNS
    _publish_alert(alert)

    logger.error(
        "DEAD_LETTER: %d tasks failed permanently after %d retries. "
        "Error: [%s] %s. Tasks: %s",
        len(task_ids), invoke_count, error_type, error_message, task_ids,
    )

    return len(task_ids) if task_ids else 1


def _mark_task_dead_letter(task_id: str, error_message: str) -> None:
    """Update task status to DEAD_LETTER in DynamoDB for visibility."""
    if not TASK_QUEUE_TABLE:
        logger.warning("TASK_QUEUE_TABLE not set, skipping status update for %s", task_id)
        return

    try:
        table = dynamodb.Table(TASK_QUEUE_TABLE)
        table.update_item(
            Key={"task_id": task_id},
            UpdateExpression=(
                "SET #status = :status, "
                "dead_letter_at = :ts, "
                "dead_letter_error = :err"
            ),
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": "DEAD_LETTER",
                ":ts": datetime.now(timezone.utc).isoformat(),
                ":err": error_message[:500],  # Truncate to avoid DynamoDB item size issues
            },
        )
        logger.info("Marked task %s as DEAD_LETTER", task_id)
    except Exception as e:
        # Don't fail the dead-letter handler if DynamoDB update fails
        logger.error("Failed to mark task %s as DEAD_LETTER: %s", task_id, e)


def _publish_alert(alert: dict) -> None:
    """Publish structured alert to SNS topic."""
    subject = (
        f"[{alert['environment'].upper()}] DAG Fan-Out Dead Letter — "
        f"{alert['task_count']} task(s) failed"
    )

    # SNS subject max 100 chars
    if len(subject) > 100:
        subject = subject[:97] + "..."

    try:
        sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=subject,
            Message=json.dumps(alert, indent=2, default=str),
            MessageAttributes={
                "severity": {
                    "DataType": "String",
                    "StringValue": alert["severity"],
                },
                "environment": {
                    "DataType": "String",
                    "StringValue": alert["environment"],
                },
            },
        )
        logger.info("Alert published to SNS: %s", subject)
    except Exception as e:
        # Log but don't fail — the CloudWatch logs are the fallback
        logger.error("Failed to publish SNS alert: %s", e)


def _extract_task_id(record: dict) -> str:
    """Safely extract task_id from a DynamoDB stream record."""
    try:
        return record["dynamodb"]["NewImage"]["task_id"]["S"]
    except (KeyError, TypeError):
        return "unknown"
