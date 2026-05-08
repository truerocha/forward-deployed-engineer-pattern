"""
Value Stream Mapping Tracker — Stage Transition Timestamps.

Tracks timestamps at each stage boundary in the value stream:
  idea -> spec -> intake -> implementation -> review -> PR -> merge -> deploy

Computes:
  - Wait-time between stages (where work waits)
  - Flow efficiency (active time / total time)
  - Bottleneck identification (stage with highest wait-time)
  - Lead time decomposition (which portion is active vs waiting)

Maps to DORA lead time decomposition and enables the portal
ValueStreamCard visualization.

DynamoDB SK pattern: vsm#{task_id}#{stage}

Ref: docs/design/fde-core-brain-development.md Section 7.4
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Ordered stages in the value stream
VSM_STAGES = [
    "idea",
    "spec",
    "intake",
    "implementation",
    "review",
    "pr_created",
    "merge",
    "deploy",
]


@dataclass
class StageTransition:
    """A single stage transition event in the value stream."""

    task_id: str
    stage: str
    timestamp: str = ""
    metadata: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def stage_index(self) -> int:
        """Index of this stage in the ordered pipeline."""
        try:
            return VSM_STAGES.index(self.stage)
        except ValueError:
            return -1


@dataclass
class WaitTimeAnalysis:
    """Wait-time analysis between consecutive stages."""

    from_stage: str
    to_stage: str
    wait_seconds: float
    is_bottleneck: bool = False


@dataclass
class FlowMetrics:
    """Complete flow metrics for a task's value stream journey."""

    task_id: str
    total_duration_seconds: float = 0.0
    active_time_seconds: float = 0.0
    wait_time_seconds: float = 0.0
    flow_efficiency_percent: float = 0.0
    stage_durations: dict[str, float] = field(default_factory=dict)
    wait_times: list[WaitTimeAnalysis] = field(default_factory=list)
    bottleneck_stage: str = ""
    stages_completed: int = 0


class VsmTracker:
    """
    Tracks value stream stage transitions and computes flow metrics.

    Usage:
        vsm = VsmTracker(project_id="my-repo")
        vsm.record_transition(task_id="t-123", stage="idea")
        vsm.record_transition(task_id="t-123", stage="spec")
        vsm.record_transition(task_id="t-123", stage="intake")
        # ... later ...
        metrics = vsm.get_flow_metrics("t-123")
    """

    def __init__(
        self,
        project_id: str = "",
        metrics_table: str | None = None,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")

    def record_transition(
        self, task_id: str, stage: str, timestamp: str | None = None
    ) -> None:
        """
        Record a stage transition in the value stream.

        Args:
            task_id: The task moving through the pipeline.
            stage: The stage being entered (must be in VSM_STAGES).
            timestamp: Optional explicit timestamp (defaults to now).
        """
        if stage not in VSM_STAGES:
            logger.warning("Unknown VSM stage '%s' for task %s", stage, task_id)

        transition = StageTransition(
            task_id=task_id,
            stage=stage,
            timestamp=timestamp or datetime.now(timezone.utc).isoformat(),
        )
        self._persist_transition(transition)

    def get_flow_metrics(self, task_id: str) -> FlowMetrics:
        """
        Compute complete flow metrics for a task.

        Retrieves all stage transitions for the task, computes durations
        between stages, identifies wait times, and calculates flow efficiency.

        Args:
            task_id: The task to analyze.

        Returns:
            FlowMetrics with durations, wait times, and bottleneck identification.
        """
        transitions = self._load_transitions(task_id)
        if not transitions:
            return FlowMetrics(task_id=task_id)

        # Sort by timestamp
        transitions.sort(key=lambda t: t.get("timestamp", ""))

        # Compute stage durations and wait times
        stage_timestamps: dict[str, str] = {}
        for t in transitions:
            stage = t.get("stage", "")
            ts = t.get("timestamp", "")
            if stage and ts:
                stage_timestamps[stage] = ts

        # Calculate metrics
        metrics = FlowMetrics(task_id=task_id, stages_completed=len(stage_timestamps))

        # Compute time between consecutive stages
        ordered_stages = [s for s in VSM_STAGES if s in stage_timestamps]
        wait_times: list[WaitTimeAnalysis] = []

        for i in range(1, len(ordered_stages)):
            from_stage = ordered_stages[i - 1]
            to_stage = ordered_stages[i]

            try:
                from_ts = datetime.fromisoformat(stage_timestamps[from_stage])
                to_ts = datetime.fromisoformat(stage_timestamps[to_stage])
                duration = (to_ts - from_ts).total_seconds()

                metrics.stage_durations[f"{from_stage}_to_{to_stage}"] = duration

                # Classify as active or wait time
                # Active stages: implementation, review (actual work happening)
                # Wait stages: transitions between other stages
                is_active = to_stage in ("implementation", "review")
                if is_active:
                    metrics.active_time_seconds += duration
                else:
                    metrics.wait_time_seconds += duration

                wait_times.append(
                    WaitTimeAnalysis(
                        from_stage=from_stage,
                        to_stage=to_stage,
                        wait_seconds=duration,
                    )
                )
            except (ValueError, TypeError):
                continue

        # Total duration (first to last stage)
        if len(ordered_stages) >= 2:
            try:
                first_ts = datetime.fromisoformat(stage_timestamps[ordered_stages[0]])
                last_ts = datetime.fromisoformat(stage_timestamps[ordered_stages[-1]])
                metrics.total_duration_seconds = (last_ts - first_ts).total_seconds()
            except (ValueError, TypeError):
                pass

        # Flow efficiency
        if metrics.total_duration_seconds > 0:
            metrics.flow_efficiency_percent = round(
                (metrics.active_time_seconds / metrics.total_duration_seconds) * 100, 1
            )

        # Identify bottleneck (longest wait time)
        if wait_times:
            max_wait = max(wait_times, key=lambda w: w.wait_seconds)
            max_wait.is_bottleneck = True
            metrics.bottleneck_stage = f"{max_wait.from_stage}_to_{max_wait.to_stage}"

        metrics.wait_times = wait_times
        return metrics

    def get_aggregate_bottleneck(self, window_days: int = 7) -> dict[str, Any]:
        """
        Identify the most common bottleneck across all recent tasks.

        Returns:
            Dict with bottleneck stage and frequency.
        """
        if not self._metrics_table:
            return {"bottleneck": "unknown", "frequency": 0}

        table = self._dynamodb.Table(self._metrics_table)

        try:
            response = table.query(
                KeyConditionExpression=(
                    "project_id = :pid AND begins_with(metric_key, :prefix)"
                ),
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "vsm#",
                },
                Limit=200,
                ScanIndexForward=False,  # Most recent first
            )

            # Count bottleneck stages across tasks
            bottleneck_counts: dict[str, int] = {}
            seen_tasks: set[str] = set()

            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                task_id = data.get("task_id", "")
                if task_id in seen_tasks:
                    continue
                seen_tasks.add(task_id)

                # Get flow metrics for this task
                flow = self.get_flow_metrics(task_id)
                if flow.bottleneck_stage:
                    bottleneck_counts[flow.bottleneck_stage] = (
                        bottleneck_counts.get(flow.bottleneck_stage, 0) + 1
                    )

            if not bottleneck_counts:
                return {"bottleneck": "none_detected", "frequency": 0}

            top_bottleneck = max(bottleneck_counts, key=bottleneck_counts.get)  # type: ignore[arg-type]
            return {
                "bottleneck": top_bottleneck,
                "frequency": bottleneck_counts[top_bottleneck],
                "total_tasks_analyzed": len(seen_tasks),
            }

        except ClientError as e:
            logger.warning("Failed to compute aggregate bottleneck: %s", str(e))
            return {"bottleneck": "error", "frequency": 0}

    def _persist_transition(self, transition: StageTransition) -> None:
        """Persist a stage transition to DynamoDB."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"vsm#{transition.task_id}#{transition.stage}",
                    "metric_type": "vsm",
                    "task_id": transition.task_id,
                    "recorded_at": transition.timestamp,
                    "data": json.dumps(
                        {
                            "task_id": transition.task_id,
                            "stage": transition.stage,
                            "timestamp": transition.timestamp,
                            "metadata": transition.metadata or {},
                        }
                    ),
                }
            )
        except ClientError as e:
            logger.warning("Failed to persist VSM transition: %s", str(e))

    def _load_transitions(self, task_id: str) -> list[dict[str, Any]]:
        """Load all stage transitions for a task from DynamoDB."""
        if not self._metrics_table:
            return []

        table = self._dynamodb.Table(self._metrics_table)
        prefix = f"vsm#{task_id}#"

        try:
            response = table.query(
                KeyConditionExpression=(
                    "project_id = :pid AND begins_with(metric_key, :prefix)"
                ),
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": prefix,
                },
            )

            results = []
            for item in response.get("Items", []):
                data = json.loads(item.get("data", "{}"))
                results.append(data)
            return results

        except ClientError as e:
            logger.warning("Failed to load VSM transitions for task %s: %s", task_id, str(e))
            return []
