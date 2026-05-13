"""
Webhook Router Lambda — Dynamic detail-type routing for ALM webhooks.

COE-131: The API Gateway EventBridge-PutEvents integration hardcodes
DetailType="issue.labeled" for ALL GitHub events. This means PR review
events, issue comments, and other webhook types arrive on EventBridge
with the WRONG detail-type, causing EventBridge rules to never match.

This Lambda replaces the direct integration. It:
  1. Reads the event type from platform-specific signals:
     - GitHub: X-GitHub-Event header
     - GitLab: object_kind field in body
     - Asana: resource.resource_type field
  2. Puts the event on EventBridge with the CORRECT detail-type
  3. Returns 200 to the webhook sender

Ref: docs/coe/COE-131-hardcoded-detail-type.md
"""

import json
import logging
import os

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

EVENT_BUS_NAME = os.environ.get("EVENT_BUS_NAME", "fde-dev-factory-bus")
REGION = os.environ.get("AWS_REGION", os.environ.get("AWS_REGION_NAME", "us-east-1"))

eventbridge = boto3.client("events", region_name=REGION)

GITHUB_EVENT_MAP = {
    "issues": "issue.labeled",
    "pull_request_review": "pull_request_review.submitted",
    "issue_comment": "issue_comment.created",
    "pull_request": "pull_request.updated",
    "push": "push.completed",
    "check_run": "check_run.completed",
    "workflow_run": "workflow_run.completed",
}

GITLAB_EVENT_MAP = {
    "issue": "issue.updated",
    "merge_request": "merge_request.updated",
    "note": "note.created",
    "push": "push.completed",
    "pipeline": "pipeline.completed",
}

ASANA_EVENT_MAP = {
    "task": "task.moved",
    "story": "story.created",
}


def handler(event, context):
    """Route webhook events to EventBridge with correct detail-type."""
    path = event.get("rawPath", event.get("path", ""))
    headers = event.get("headers", {})
    body_str = event.get("body", "{}")

    try:
        body = json.loads(body_str) if isinstance(body_str, str) else body_str
    except (json.JSONDecodeError, TypeError):
        return _response(400, {"error": "Invalid JSON body"})

    if "/webhook/github" in path:
        source = "fde.github.webhook"
        detail_type = _resolve_github(headers, body)
    elif "/webhook/gitlab" in path:
        source = "fde.gitlab.webhook"
        detail_type = _resolve_gitlab(headers, body)
    elif "/webhook/asana" in path:
        source = "fde.asana.webhook"
        detail_type = _resolve_asana(body)
    else:
        return _response(200, {"status": "skipped", "reason": "unknown path"})

    logger.info("Webhook routed: path=%s source=%s detail_type=%s", path, source, detail_type)

    try:
        response = eventbridge.put_events(Entries=[{
            "Source": source,
            "DetailType": detail_type,
            "Detail": json.dumps(body),
            "EventBusName": EVENT_BUS_NAME,
        }])

        failed = response.get("FailedEntryCount", 0)
        if failed > 0:
            logger.error("EventBridge delivery failed: %s", response.get("Entries", []))
            return _response(500, {"error": "EventBridge delivery failed"})

        logger.info("Delivered: source=%s detail_type=%s", source, detail_type)
        return _response(200, {"status": "delivered", "source": source, "detail_type": detail_type})

    except Exception as e:
        logger.error("EventBridge error: %s", str(e))
        return _response(500, {"error": str(e)[:200]})


def _resolve_github(headers: dict, body: dict) -> str:
    """Resolve detail-type from GitHub X-GitHub-Event header + action."""
    gh_event = headers.get("x-github-event", headers.get("X-GitHub-Event", ""))
    action = body.get("action", "")

    if gh_event == "issues" and action == "labeled":
        return "issue.labeled"
    if gh_event == "issues":
        return f"issue.{action}"
    if gh_event == "pull_request_review":
        return "pull_request_review.submitted"
    if gh_event == "issue_comment":
        return "issue_comment.created"
    if gh_event == "pull_request":
        return f"pull_request.{action}"

    return GITHUB_EVENT_MAP.get(gh_event, f"{gh_event}.{action}" if gh_event else "unknown")


def _resolve_gitlab(headers: dict, body: dict) -> str:
    """Resolve detail-type from GitLab object_kind."""
    object_kind = body.get("object_kind", "")
    action = body.get("object_attributes", {}).get("action", "")

    if object_kind == "merge_request" and action:
        return f"merge_request.{action}"
    if object_kind == "note":
        return "note.created"

    return GITLAB_EVENT_MAP.get(object_kind, f"{object_kind}.{action}" if object_kind else "unknown")


def _resolve_asana(body: dict) -> str:
    """Resolve detail-type from Asana event."""
    events = body.get("events", [body])
    if events:
        resource_type = events[0].get("resource", {}).get("resource_type", "task")
        action = events[0].get("action", "changed")
        return ASANA_EVENT_MAP.get(resource_type, f"{resource_type}.{action}")
    return "task.moved"


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json", "Access-Control-Allow-Origin": "*"},
        "body": json.dumps(body),
    }
