"""
Verification Metrics — Bottleneck Detection for Review/Evaluation.

DORA 2025 identifies that AI shifts the bottleneck from writing code to
verifying/reviewing code. This module tracks verification throughput to
detect when the branch evaluation agent becomes the constraint.

Metrics tracked:
  - time_in_review: Duration from PR creation to merge/reject decision
  - review_rejection_rate: % of PRs rejected by evaluation agent
  - evaluation_queue_depth: Number of PRs awaiting evaluation
  - time_from_pr_to_merge: Total PR lifecycle duration

Alerts:
  - Queue depth > 5: bottleneck warning
  - Time in review > 2 hours: SLA breach
  - Queue depth > 3 for >30min: auto-scaling trigger

Ref: docs/design/fde-core-brain-development.md Section 4.5
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Alert thresholds
_QUEUE_DEPTH_WARNING = 5
_QUEUE_DEPTH_SCALING_TRIGGER = 3
_TIME_IN_REVIEW_SLA_SECONDS = 7200  # 2 hours
_SCALING_TRIGGER_DURATION_SECONDS = 1800  # 30 minutes


@dataclass
class VerificationEvent:
    """A single verification lifecycle event."""

    event_type: str  # pr_created | review_started | review_completed | pr_merged | pr_rejected
    task_id: str
    pr_identifier: str  # e.g., "owner/repo#123"
    timestamp: str = ""
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class VerificationSnapshot:
    """Current state of the verification pipeline."""

    queue_depth: int = 0
    avg_time_in_review_seconds: float = 0.0
    rejection_rate_percent: float = 0.0
    prs_in_review: list[str] | None = None
    bottleneck_detected: bool = False
    scaling_recommended: bool = False


class VerificationMetrics:
    """
    Tracks verification throughput and detects bottlenecks.

    The evaluation agent (branch-eval) is the primary reviewer. As factory
    throughput increases, this agent may become the constraint. This module
    makes that visible and triggers scaling.

    Usage:
        vm = VerificationMetrics(project_id="my-repo")
        vm.record_pr_created(task_id="t-123", pr_id="owner/repo#45")
        vm.record_review_completed(task_id="t-123", pr_id="owner/repo#45", accepted=True)
        snapshot = vm.get_snapshot()
    """

    def __init__(
        self,
        project_id: str = "",
        metrics_table: str | None = None,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")
        self._cloudwatch = boto3.client("cloudwatch")

    def record_pr_created(self, task_id: str, pr_id: str) -> None:
        """Record that a PR was created and is awaiting review."""
        self._record_event(
            VerificationEvent(
                event_type="pr_created",
                task_id=task_id,
                pr_identifier=pr_id,
            )
        )

    def record_review_started(self, task_id: str, pr_id: str) -> None:
        """Record that the evaluation agent started reviewing a PR."""
        self._record_event(
            VerificationEvent(
                event_type="review_started",
                task_id=task_id,
                pr_identifier=pr_id,
            )
        )

    def record_review_completed(
        self, task_id: str, pr_id: str, accepted: bool
    ) -> None:
        """Record that a review was completed (accepted or rejected)."""
        event_type = "pr_merged" if accepted else "pr_rejected"
        self._record_event(
            VerificationEvent(
                event_type=event_type,
                task_id=task_id,
                pr_identifier=pr_id,
                metadata={"accepted": accepted},
            )
        )

    def get_queue_depth(self) -> int:
        """
        Compute current queue depth (PRs created but not yet reviewed).

        Returns:
            Number of PRs awaiting review.
        """
        created = self._query_events("pr_created", window_days=7)
        completed_prs = set()
        for event_type in ("pr_merged", "pr_rejected"):
            for event in self._query_events(event_type, window_days=7):
                completed_prs.add(event.get("pr_identifier", ""))

        pending = [e for e in created if e.get("pr_identifier", "") not in completed_prs]
        return len(pending)

    def get_avg_time_in_review(self, window_days: int = 7) -> float:
        """
        Compute average time from PR creation to review completion.

        Returns:
            Average time in seconds. 0.0 if no completed reviews.
        """
        created_events = self._query_events("pr_created", window_days)
        completed_events = self._query_events("pr_merged", window_days)
        rejected_events = self._query_events("pr_rejected", window_days)

        # Build lookup: pr_id -> creation timestamp
        creation_times: dict[str, str] = {}
        for event in created_events:
            pr_id = event.get("pr_identifier", "")
            if pr_id:
                creation_times[pr_id] = event.get("timestamp", "")

        # Compute durations for completed PRs
        durations: list[float] = []
        for event in completed_events + rejected_events:
            pr_id = event.get("pr_identifier", "")
            if pr_id in creation_times:
                try:
                    created_at = datetime.fromisoformat(creation_times[pr_id])
                    completed_at = datetime.fromisoformat(event.get("timestamp", ""))
                    duration = (completed_at - created_at).total_seconds()
                    if duration > 0:
                        durations.append(duration)
                except (ValueError, TypeError):
                    continue

        if not durations:
            return 0.0
        return round(sum(durations) / len(durations), 1)

    def get_rejection_rate(self, window_days: int = 7) -> float:
        """
        Compute review rejection rate as a percentage.

        Returns:
            Rejection rate (0-100).
        """
        merged = len(self._query_events("pr_merged", window_days))
        rejected = len(self._query_events("pr_rejected", window_days))
        total = merged + rejected
        if total == 0:
            return 0.0
        return round((rejected / total) * 100, 2)

    def get_snapshot(self) -> VerificationSnapshot:
        """
        Get current verification pipeline state with bottleneck detection.

        Returns:
            VerificationSnapshot with metrics and alert flags.
        """
        queue_depth = self.get_queue_depth()
        avg_review_time = self.get_avg_time_in_review()
        rejection_rate = self.get_rejection_rate()

        bottleneck = (
            queue_depth >= _QUEUE_DEPTH_WARNING
            or avg_review_time > _TIME_IN_REVIEW_SLA_SECONDS
        )
        scaling = queue_depth >= _QUEUE_DEPTH_SCALING_TRIGGER

        snapshot = VerificationSnapshot(
            queue_depth=queue_depth,
            avg_time_in_review_seconds=avg_review_time,
            rejection_rate_percent=rejection_rate,
            bottleneck_detected=bottleneck,
            scaling_recommended=scaling,
        )

        # Emit CloudWatch metrics for alerting
        self._emit_cloudwatch_metrics(snapshot)

        return snapshot

    def _record_event(self, event: VerificationEvent) -> None:
        """Persist a verification event to DynamoDB."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"verification#{event.event_type}#{event.timestamp}",
                    "metric_type": "verification",
                    "task_id": event.task_id,
                    "recorded_at": event.timestamp,
                    "data": json.dumps(
                        {
                            "event_type": event.event_type,
                            "pr_identifier": event.pr_identifier,
                            "timestamp": event.timestamp,
                            "metadata": event.metadata or {},
                        }
                    ),
                }
            )
        except ClientError as e:
            logger.warning("Failed to record verification event: %s", str(e))

    def _query_events(self, event_type: str, window_days: int) -> list[dict[str, Any]]:
        """Query verification events by type within a time window."""
        if not self._metrics_table:
            return []

        table = self._dynamodb.Table(self._metrics_table)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        prefix = f"verification#{event_type}#"

        try:
            response = table.query(
                KeyConditionExpression=(
                    "project_id = :pid AND begins_with(metric_key, :prefix)"
                ),
                FilterExpression="recorded_at >= :cutoff",
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": prefix,
                    ":cutoff": cutoff,
                },
            )

            results = []
            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                results.append(data)
            return results

        except ClientError as e:
            logger.warning("Failed to query verification events: %s", str(e))
            return []

    def _emit_cloudwatch_metrics(self, snapshot: VerificationSnapshot) -> None:
        """Emit verification metrics to CloudWatch for alerting."""
        try:
            self._cloudwatch.put_metric_data(
                Namespace="FDE/Factory",
                MetricData=[
                    {
                        "MetricName": "EvaluationQueueDepth",
                        "Value": snapshot.queue_depth,
                        "Unit": "Count",
                        "Dimensions": [
                            {"Name": "ProjectId", "Value": self._project_id},
                        ],
                    },
                    {
                        "MetricName": "AvgTimeInReview",
                        "Value": snapshot.avg_time_in_review_seconds,
                        "Unit": "Seconds",
                        "Dimensions": [
                            {"Name": "ProjectId", "Value": self._project_id},
                        ],
                    },
                ],
            )
        except ClientError as e:
            logger.warning("Failed to emit verification CloudWatch metrics: %s", str(e))
