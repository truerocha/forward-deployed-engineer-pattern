"""
DAG Fan-Out Lambda — Triggers ECS RunTask for READY tasks (ADR-014, Step 2).

Invoked by DynamoDB Streams when a task transitions from PENDING → READY.
This happens after _resolve_dependencies() promotes a task whose dependencies
have all completed.

The Lambda:
1. Extracts the task record from the stream event
2. Builds an EVENTBRIDGE_EVENT payload with the task's data contract
3. Calls ecs:RunTask to start a new Strands agent container
4. Logs the correlation_id for distributed tracing

No Step Functions needed — this is a single-decision fan-out with no branching,
no wait-for-all, and no human approval steps. DynamoDB Streams provides 3 retries
on failure automatically.
"""

import json
import logging
import os
import uuid

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ecs = boto3.client("ecs")

ECS_CLUSTER_ARN = os.environ["ECS_CLUSTER_ARN"]
TASK_DEFINITION_ARN = os.environ["TASK_DEFINITION_ARN"]
SUBNETS = os.environ["SUBNETS"].split(",")
SECURITY_GROUPS = os.environ["SECURITY_GROUPS"].split(",")
ENVIRONMENT = os.environ.get("ENVIRONMENT", "dev")


def handler(event, context):
    """Process DynamoDB Stream records for PENDING → READY transitions.

    The stream filter (configured in Terraform) ensures we only receive
    MODIFY events where NewImage.status = READY and OldImage.status = PENDING.
    """
    records_processed = 0
    errors = []

    for record in event.get("Records", []):
        try:
            _process_record(record)
            records_processed += 1
        except Exception as e:
            task_id = _extract_task_id(record)
            logger.error("Failed to fan out task %s: %s", task_id, e)
            errors.append({"task_id": task_id, "error": str(e)})

    logger.info(
        "Fan-out complete: %d processed, %d errors",
        records_processed, len(errors),
    )

    # If any records failed, raise to trigger DynamoDB Stream retry
    if errors:
        raise RuntimeError(f"Fan-out failed for {len(errors)} tasks: {errors}")

    return {"processed": records_processed}


def _process_record(record: dict) -> None:
    """Process a single DynamoDB Stream record."""
    new_image = record["dynamodb"]["NewImage"]
    task_id = new_image["task_id"]["S"]
    correlation_id = f"fanout-{uuid.uuid4().hex[:8]}"

    logger.info(
        "Fan-out triggered: task_id=%s, correlation_id=%s",
        task_id, correlation_id,
    )

    # Build the event payload that the agent_entrypoint.py expects
    event_payload = _build_event_payload(new_image, correlation_id)

    # Call ecs:RunTask
    response = ecs.run_task(
        cluster=ECS_CLUSTER_ARN,
        taskDefinition=TASK_DEFINITION_ARN,
        launchType="FARGATE",
        count=1,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": SUBNETS,
                "securityGroups": SECURITY_GROUPS,
                "assignPublicIp": "DISABLED",
            }
        },
        overrides={
            "containerOverrides": [{
                "name": "strands-agent",
                "environment": [
                    {"name": "EVENTBRIDGE_EVENT", "value": json.dumps(event_payload)},
                    {"name": "CORRELATION_ID", "value": correlation_id},
                ],
            }]
        },
        tags=[
            {"key": "task_id", "value": task_id},
            {"key": "correlation_id", "value": correlation_id},
            {"key": "trigger", "value": "dag-fanout"},
        ],
    )

    # Check for failures
    failures = response.get("failures", [])
    if failures:
        raise RuntimeError(f"ECS RunTask failed: {failures}")

    task_arn = response["tasks"][0]["taskArn"]
    logger.info(
        "ECS task started: task_id=%s, ecs_task_arn=%s, correlation_id=%s",
        task_id, task_arn, correlation_id,
    )


def _build_event_payload(new_image: dict, correlation_id: str) -> dict:
    """Build the EVENTBRIDGE_EVENT payload from the DynamoDB record.

    The agent_entrypoint.py expects an event with:
    - source: "fde.direct"
    - detail-type: "TaskReady"
    - detail: { spec_content, spec_path, data_contract }
    """
    task_id = new_image["task_id"]["S"]
    spec_content = new_image.get("spec_content", {}).get("S", "")
    spec_path = new_image.get("spec_path", {}).get("S", "")
    source = new_image.get("source", {}).get("S", "direct")
    title = new_image.get("title", {}).get("S", "")
    priority = new_image.get("priority", {}).get("S", "P2")

    return {
        "source": "fde.direct",
        "detail-type": "TaskReady",
        "detail": {
            "spec_content": spec_content,
            "spec_path": spec_path,
            "data_contract": {
                "task_id": task_id,
                "title": title,
                "source": source,
                "type": "feature",
                "priority": priority,
                "tech_stack": [],
                "constraints": "",
                "related_docs": [],
                "target_environment": [],
                "correlation_id": correlation_id,
            },
        },
    }


def _extract_task_id(record: dict) -> str:
    """Safely extract task_id from a stream record for error logging."""
    try:
        return record["dynamodb"]["NewImage"]["task_id"]["S"]
    except (KeyError, TypeError):
        return "unknown"
