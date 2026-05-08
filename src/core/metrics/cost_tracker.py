"""
Cost Tracker — Per-Agent, Per-Task Token and Cost Accounting.

Intercepts Bedrock invoke_model/converse responses, extracts token counts,
computes cost per model tier, and persists to the unified metrics table.

Features:
  - Per-agent cost tracking (which agent costs how much)
  - Per-task cost aggregation (total cost of a pipeline execution)
  - Per-gate cost tracking (cost of governance overhead)
  - Model tier distribution (what % of calls use fast vs reasoning vs deep)
  - Alert threshold detection (fires when task exceeds $2.00 default)
  - Historical cost trend (30-day rolling via DynamoDB queries)

Cost model (per 1K tokens, approximate):
  - fast (Haiku): $0.00025 input, $0.00125 output
  - reasoning (Sonnet): $0.003 input, $0.015 output
  - deep (Opus): $0.015 input, $0.075 output

Ref: docs/design/fde-core-brain-development.md Section 7.1
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)

# Cost per 1K tokens by model tier (USD)
_COST_PER_1K_TOKENS: dict[str, dict[str, float]] = {
    "fast": {"input": 0.00025, "output": 0.00125},
    "reasoning": {"input": 0.003, "output": 0.015},
    "deep": {"input": 0.015, "output": 0.075},
}

# Default alert threshold per task (USD)
_DEFAULT_TASK_COST_THRESHOLD = 2.00


@dataclass
class TokenUsage:
    """Token usage from a single Bedrock invocation."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @classmethod
    def from_bedrock_response(cls, response: dict[str, Any]) -> TokenUsage:
        """Extract token usage from a Bedrock Converse API response."""
        usage = response.get("usage", {})
        return cls(
            input_tokens=usage.get("inputTokens", 0),
            output_tokens=usage.get("outputTokens", 0),
        )


@dataclass
class CostRecord:
    """A single cost record for one Bedrock invocation."""

    agent_role: str
    model_tier: str
    task_id: str
    project_id: str
    input_tokens: int
    output_tokens: int
    input_cost_usd: float
    output_cost_usd: float
    total_cost_usd: float
    gate_name: str | None = None  # Set if this is a gate invocation
    timestamp: str = ""

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class TaskCostSummary:
    """Aggregated cost summary for a complete task execution."""

    task_id: str
    project_id: str
    total_cost_usd: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cost_by_agent: dict[str, float] = field(default_factory=dict)
    cost_by_tier: dict[str, float] = field(default_factory=dict)
    cost_by_gate: dict[str, float] = field(default_factory=dict)
    invocation_count: int = 0
    threshold_exceeded: bool = False


class CostTracker:
    """
    Tracks and persists cost metrics for all Bedrock invocations.

    Usage:
        tracker = CostTracker(project_id="my-repo")
        # After each Bedrock call:
        tracker.record(agent_role="swe-developer", model_tier="reasoning",
                       task_id="task-123", usage=TokenUsage(input_tokens=500, output_tokens=200))
        # At end of task:
        summary = tracker.get_task_summary("task-123")
    """

    def __init__(
        self,
        project_id: str = "",
        metrics_table: str | None = None,
        cost_threshold: float = _DEFAULT_TASK_COST_THRESHOLD,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._cost_threshold = cost_threshold
        self._dynamodb = boto3.resource("dynamodb")
        self._cloudwatch = boto3.client("cloudwatch")

        # In-memory accumulator for current task (flushed on get_task_summary)
        self._task_records: dict[str, list[CostRecord]] = {}

    def record(
        self,
        agent_role: str,
        model_tier: str,
        task_id: str,
        usage: TokenUsage,
        gate_name: str | None = None,
    ) -> CostRecord:
        """
        Record a single Bedrock invocation cost.

        Args:
            agent_role: The agent that made the call (e.g., "swe-developer")
            model_tier: Model tier used ("fast", "reasoning", "deep")
            task_id: Task execution identifier
            usage: Token usage from the response
            gate_name: If this was a gate invocation, the gate name

        Returns:
            The CostRecord created.
        """
        tier_costs = _COST_PER_1K_TOKENS.get(model_tier, _COST_PER_1K_TOKENS["reasoning"])
        input_cost = (usage.input_tokens / 1000) * tier_costs["input"]
        output_cost = (usage.output_tokens / 1000) * tier_costs["output"]

        record = CostRecord(
            agent_role=agent_role,
            model_tier=model_tier,
            task_id=task_id,
            project_id=self._project_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            input_cost_usd=round(input_cost, 8),
            output_cost_usd=round(output_cost, 8),
            total_cost_usd=round(input_cost + output_cost, 8),
            gate_name=gate_name,
        )

        # Accumulate in memory
        if task_id not in self._task_records:
            self._task_records[task_id] = []
        self._task_records[task_id].append(record)

        # Persist to DynamoDB
        self._persist_record(record)

        # Check threshold
        task_total = sum(r.total_cost_usd for r in self._task_records[task_id])
        if task_total > self._cost_threshold:
            self._emit_threshold_alarm(task_id, task_total)

        return record

    def get_task_summary(self, task_id: str) -> TaskCostSummary:
        """
        Compute aggregated cost summary for a task.

        Args:
            task_id: The task to summarize.

        Returns:
            TaskCostSummary with breakdowns by agent, tier, and gate.
        """
        records = self._task_records.get(task_id, [])

        summary = TaskCostSummary(
            task_id=task_id,
            project_id=self._project_id,
            invocation_count=len(records),
        )

        for record in records:
            summary.total_cost_usd += record.total_cost_usd
            summary.total_input_tokens += record.input_tokens
            summary.total_output_tokens += record.output_tokens

            # By agent
            summary.cost_by_agent[record.agent_role] = (
                summary.cost_by_agent.get(record.agent_role, 0.0) + record.total_cost_usd
            )

            # By tier
            summary.cost_by_tier[record.model_tier] = (
                summary.cost_by_tier.get(record.model_tier, 0.0) + record.total_cost_usd
            )

            # By gate (if applicable)
            if record.gate_name:
                summary.cost_by_gate[record.gate_name] = (
                    summary.cost_by_gate.get(record.gate_name, 0.0) + record.total_cost_usd
                )

        summary.total_cost_usd = round(summary.total_cost_usd, 6)
        summary.threshold_exceeded = summary.total_cost_usd > self._cost_threshold

        return summary

    def get_model_tier_distribution(self, task_id: str) -> dict[str, float]:
        """
        Compute the percentage distribution of invocations by model tier.

        Returns:
            Dict mapping tier name to percentage (0-100).
        """
        records = self._task_records.get(task_id, [])
        if not records:
            return {}

        tier_counts: dict[str, int] = {}
        for record in records:
            tier_counts[record.model_tier] = tier_counts.get(record.model_tier, 0) + 1

        total = len(records)
        return {tier: round((count / total) * 100, 1) for tier, count in tier_counts.items()}

    def _persist_record(self, record: CostRecord) -> None:
        """Persist a cost record to DynamoDB metrics table."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        try:
            item = {
                "project_id": record.project_id,
                "metric_key": f"cost#{record.agent_role}#{record.timestamp}",
                "metric_type": "cost",
                "task_id": record.task_id,
                "recorded_at": record.timestamp,
                "data": json.dumps(
                    {
                        "agent_role": record.agent_role,
                        "model_tier": record.model_tier,
                        "input_tokens": record.input_tokens,
                        "output_tokens": record.output_tokens,
                        "total_tokens": record.input_tokens + record.output_tokens,
                        "input_cost_usd": record.input_cost_usd,
                        "output_cost_usd": record.output_cost_usd,
                        "total_cost_usd": record.total_cost_usd,
                        "gate_name": record.gate_name,
                    }
                ),
            }
            table.put_item(Item=item)
        except ClientError as e:
            logger.warning("Failed to persist cost record: %s", str(e))

    def _emit_threshold_alarm(self, task_id: str, total_cost: float) -> None:
        """Emit CloudWatch metric when task cost exceeds threshold."""
        logger.warning(
            "Cost threshold exceeded: task=%s cost=$%.4f threshold=$%.2f",
            task_id,
            total_cost,
            self._cost_threshold,
        )
        try:
            self._cloudwatch.put_metric_data(
                Namespace="FDE/Factory",
                MetricData=[
                    {
                        "MetricName": "TaskCostThresholdExceeded",
                        "Value": total_cost,
                        "Unit": "None",
                        "Dimensions": [
                            {"Name": "ProjectId", "Value": self._project_id},
                            {"Name": "TaskId", "Value": task_id},
                        ],
                    }
                ],
            )
        except ClientError as e:
            logger.warning("Failed to emit cost alarm metric: %s", str(e))
