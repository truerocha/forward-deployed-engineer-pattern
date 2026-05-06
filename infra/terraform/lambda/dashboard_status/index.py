"""
Dashboard Status API — Lambda handler for /status/tasks endpoint.

Reads from DynamoDB task_queue table and returns task status + metrics
for the observability dashboard.

Security: Returns only task metadata (title, status, stage, duration).
Never returns spec content, code, or internal error traces.
"""

import json
import os
from datetime import datetime, timezone, timedelta

import boto3
from boto3.dynamodb.conditions import Attr

TASK_QUEUE_TABLE = os.environ.get("TASK_QUEUE_TABLE", "fde-dev-task-queue")
REGION = os.environ.get("AWS_REGION", "us-east-1")

dynamodb = boto3.resource("dynamodb", region_name=REGION)
table = dynamodb.Table(TASK_QUEUE_TABLE)


def handler(event, context):
    """Lambda handler for GET /status/tasks."""
    try:
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        response = table.scan(
            FilterExpression=Attr("created_at").gte(cutoff),
            Limit=50,
        )

        items = response.get("Items", [])

        active = sum(1 for i in items if i.get("status") in ("RUNNING", "PENDING", "READY"))
        completed = sum(1 for i in items if i.get("status") == "COMPLETED")
        failed = sum(1 for i in items if i.get("status") in ("FAILED", "DEAD_LETTER"))
        durations = [int(i.get("duration_ms", 0)) for i in items if i.get("duration_ms")]
        avg_duration = int(sum(durations) / len(durations)) if durations else 0

        tasks = []
        for item in sorted(items, key=lambda x: x.get("created_at", ""), reverse=True):
            tasks.append({
                "task_id": item.get("task_id", ""),
                "title": item.get("title", item.get("task_id", "Unknown")),
                "status": _map_status(item.get("status", "PENDING")),
                "current_stage": item.get("current_stage", ""),
                "repo": item.get("repo", ""),
                "source": item.get("source", ""),
                "level": item.get("level", "L3"),
                "duration_ms": int(item.get("duration_ms", 0)),
                "created_at": item.get("created_at", ""),
            })

        body = {
            "metrics": {
                "active": active,
                "completed_24h": completed,
                "failed_24h": failed,
                "avg_duration_ms": avg_duration,
            },
            "tasks": tasks[:20],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, OPTIONS",
                "Access-Control-Allow-Headers": "Content-Type, Accept",
            },
            "body": json.dumps(body),
        }

    except Exception:
        return {
            "statusCode": 500,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps({"error": "Internal server error"}),
        }


def _map_status(dynamo_status: str) -> str:
    """Map DynamoDB status values to dashboard display status."""
    mapping = {
        "PENDING": "pending",
        "READY": "pending",
        "RUNNING": "running",
        "COMPLETED": "completed",
        "FAILED": "failed",
        "DEAD_LETTER": "failed",
        "BLOCKED": "pending",
    }
    return mapping.get(dynamo_status, "pending")
