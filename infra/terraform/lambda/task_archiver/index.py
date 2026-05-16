"""
Task Archiver Lambda — DynamoDB Streams → S3 Archive.

Triggered by DynamoDB Streams on the task_queue table. Captures REMOVE events
(TTL deletions) and writes the deleted item to S3 for long-term historical access.

Architecture:
  DynamoDB TTL expires item → Stream emits REMOVE event → This Lambda → S3

Design decisions:
  - Idempotent: Uses task_id as S3 key (duplicate writes are no-ops)
  - Filters: Only processes REMOVE events with OldImage (TTL deletions)
  - Strips: Removes spec_content and event_payload (large fields) from archive
  - Partitions: S3 path uses YYYY/MM/DD for efficient date-range queries

WAF Alignment:
  - REL 9: Backup and recovery (data preserved beyond DynamoDB TTL)
  - COST 6: Manage demand (DynamoDB stays lean, S3 for cold storage)
  - OPS 8: Evolve operations (historical data accessible for analysis)
"""

import json
import logging
import os
from datetime import datetime, timezone

import boto3

logger = logging.getLogger("fde.task_archiver")
logger.setLevel(logging.INFO)

ARTIFACTS_BUCKET = os.environ.get("ARTIFACTS_BUCKET", "")
ARCHIVE_PREFIX = os.environ.get("ARCHIVE_PREFIX", "history/tasks/")
REGION = os.environ.get("AWS_REGION", "us-east-1")

s3 = boto3.client("s3", region_name=REGION)


def handler(event, context):
    """Process DynamoDB Stream events — archive REMOVE (TTL-expired) items to S3.

    Args:
        event: DynamoDB Streams event with Records array.
        context: Lambda context.

    Returns:
        Summary of processed records.
    """
    if not ARTIFACTS_BUCKET:
        logger.error("ARTIFACTS_BUCKET not configured — cannot archive")
        return {"error": "ARTIFACTS_BUCKET not set", "processed": 0}

    processed = 0
    skipped = 0
    errors = 0

    for record in event.get("Records", []):
        event_name = record.get("eventName", "")

        # Only process REMOVE events (TTL deletions)
        if event_name != "REMOVE":
            skipped += 1
            continue

        # Get the old image (the item before deletion)
        old_image = record.get("dynamodb", {}).get("OldImage")
        if not old_image:
            skipped += 1
            continue

        try:
            # Convert DynamoDB JSON to standard Python dict
            item = _deserialize_dynamodb_item(old_image)

            # Skip CONFIG# and COUNTER# items (not real tasks)
            task_id = item.get("task_id", "")
            if task_id.startswith("CONFIG#") or task_id.startswith("COUNTER#"):
                skipped += 1
                continue

            # Archive the task
            _archive_task(item)
            processed += 1

        except Exception as e:
            logger.error("Failed to archive record: %s", str(e)[:200])
            errors += 1

    result = {
        "processed": processed,
        "skipped": skipped,
        "errors": errors,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    logger.info("Archiver result: %s", json.dumps(result))
    return result


def _archive_task(item: dict) -> None:
    """Write a task item to S3 in the archive partition.

    S3 path: {prefix}{YYYY}/{MM}/{DD}/{task_id}.json

    Strips large fields (spec_content, event_payload) to keep archive lean.
    Preserves: task metadata, events (reasoning), status, timing, links.
    """
    task_id = item.get("task_id", "unknown")
    created_at = item.get("created_at", "")

    # Parse date for partitioning
    try:
        dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        dt = datetime.now(timezone.utc)

    # Build archive record (strip large fields, keep metadata + reasoning)
    archive_record = {
        "task_id": task_id,
        "title": item.get("title", ""),
        "status": item.get("status", ""),
        "repo": item.get("repo", ""),
        "source": item.get("source", ""),
        "issue_id": item.get("issue_id", ""),
        "issue_url": item.get("issue_url", ""),
        "pr_url": item.get("pr_url", ""),
        "pr_error": item.get("pr_error", ""),
        "priority": item.get("priority", ""),
        "current_stage": item.get("current_stage", ""),
        "assigned_agent": item.get("assigned_agent", ""),
        "duration_ms": item.get("duration_ms", 0),
        "created_at": created_at,
        "updated_at": item.get("updated_at", ""),
        "started_at": item.get("started_at", ""),
        "error": item.get("error", ""),
        "events": item.get("events", []),  # Preserve reasoning timeline
        "retry_of": item.get("retry_of", ""),
        "retry_count": item.get("retry_count", 0),
        "archived_at": datetime.now(timezone.utc).isoformat(),
        "archive_reason": "ttl_expiry",
    }

    # S3 key with date partitioning
    s3_key = f"{ARCHIVE_PREFIX}{dt.strftime('%Y/%m/%d')}/{task_id}.json"

    s3.put_object(
        Bucket=ARTIFACTS_BUCKET,
        Key=s3_key,
        Body=json.dumps(archive_record, default=str),
        ContentType="application/json",
        ServerSideEncryption="AES256",
        Metadata={
            "task_id": task_id,
            "status": item.get("status", ""),
            "repo": item.get("repo", ""),
        },
    )

    logger.info("Archived task %s → s3://%s/%s", task_id, ARTIFACTS_BUCKET, s3_key)


def _deserialize_dynamodb_item(dynamodb_item: dict) -> dict:
    """Convert DynamoDB JSON format to standard Python dict.

    DynamoDB Streams uses typed format: {"S": "value"}, {"N": "123"}, {"L": [...]}, etc.
    """
    result = {}
    for key, typed_value in dynamodb_item.items():
        result[key] = _deserialize_value(typed_value)
    return result


def _deserialize_value(typed_value: dict) -> any:
    """Recursively deserialize a single DynamoDB typed value."""
    if "S" in typed_value:
        return typed_value["S"]
    elif "N" in typed_value:
        num_str = typed_value["N"]
        return int(num_str) if "." not in num_str else float(num_str)
    elif "BOOL" in typed_value:
        return typed_value["BOOL"]
    elif "NULL" in typed_value:
        return None
    elif "L" in typed_value:
        return [_deserialize_value(item) for item in typed_value["L"]]
    elif "M" in typed_value:
        return {k: _deserialize_value(v) for k, v in typed_value["M"].items()}
    elif "SS" in typed_value:
        return list(typed_value["SS"])
    elif "NS" in typed_value:
        return [int(n) if "." not in n else float(n) for n in typed_value["NS"]]
    else:
        # Fallback: return the raw value
        return typed_value
