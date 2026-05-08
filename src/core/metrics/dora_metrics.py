"""
DORA Metrics — Four Key Metrics with Autonomy Level Dimension.

Tracks the four DORA metrics (Lead Time, Deploy Frequency, Change Fail Rate,
Mean Time to Recovery) with an additional dimension: autonomy level (L1-L5).

This enables the DORA 2025 insight: correlating instability with autonomy level.
If L5 CFR > L3 CFR, calibration is wrong and autonomy should be reduced.

Metrics tracked:
  - lead_time: Time from first commit to production deploy (per autonomy level)
  - deploy_frequency: Deploys per day/week (per autonomy level)
  - change_fail_rate: % of deployments causing failure (per autonomy level)
  - mttr: Mean time to recovery from failure (per autonomy level)

DynamoDB SK pattern: dora#{metric}#{autonomy_level}#{date}

Ref: docs/design/fde-core-brain-development.md Section 4.4
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


@dataclass
class DoraDataPoint:
    """A single DORA metric data point."""

    metric: str  # lead_time | deploy_frequency | change_fail_rate | mttr
    autonomy_level: int  # L1-L5
    value: float
    unit: str  # seconds | count | percentage | seconds
    task_id: str = ""
    metadata: dict[str, Any] | None = None

    @property
    def date(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")


@dataclass
class DoraSnapshot:
    """Snapshot of all four DORA metrics for a given autonomy level."""

    autonomy_level: int
    lead_time_seconds: float = 0.0
    deploy_frequency_per_week: float = 0.0
    change_fail_rate_percent: float = 0.0
    mttr_seconds: float = 0.0
    sample_size: int = 0
    window_days: int = 7


class DoraMetrics:
    """
    Records and queries DORA metrics with autonomy level as a dimension.

    The autonomy level dimension enables:
      - CFR comparison across levels (calibration validation)
      - Anti-instability loop input (CFR per level triggers adjustments)
      - Weekly calibration reports (anomaly detection)
      - Portal per-level breakdown view

    Usage:
        dora = DoraMetrics(project_id="my-repo")
        dora.record_lead_time(task_id="t-123", autonomy_level=4, seconds=900)
        dora.record_change_failure(task_id="t-456", autonomy_level=5, is_failure=True)
        snapshot = dora.get_snapshot(autonomy_level=4, window_days=7)
    """

    def __init__(
        self,
        project_id: str = "",
        metrics_table: str | None = None,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._dynamodb = boto3.resource("dynamodb")

    def record_lead_time(
        self, task_id: str, autonomy_level: int, seconds: float
    ) -> None:
        """
        Record lead time (first commit to production deploy).

        Args:
            task_id: The task that was deployed.
            autonomy_level: L1-L5 autonomy level of the task.
            seconds: Lead time in seconds.
        """
        self._record(
            DoraDataPoint(
                metric="lead_time",
                autonomy_level=autonomy_level,
                value=seconds,
                unit="seconds",
                task_id=task_id,
            )
        )

    def record_deployment(self, task_id: str, autonomy_level: int) -> None:
        """
        Record a successful deployment (for deploy frequency calculation).

        Args:
            task_id: The task that was deployed.
            autonomy_level: L1-L5 autonomy level.
        """
        self._record(
            DoraDataPoint(
                metric="deploy_frequency",
                autonomy_level=autonomy_level,
                value=1.0,
                unit="count",
                task_id=task_id,
            )
        )

    def record_change_failure(
        self, task_id: str, autonomy_level: int, is_failure: bool
    ) -> None:
        """
        Record whether a deployment resulted in failure (for CFR calculation).

        Args:
            task_id: The task that was deployed.
            autonomy_level: L1-L5 autonomy level.
            is_failure: True if the deployment caused a failure.
        """
        self._record(
            DoraDataPoint(
                metric="change_fail_rate",
                autonomy_level=autonomy_level,
                value=1.0 if is_failure else 0.0,
                unit="boolean",
                task_id=task_id,
                metadata={"is_failure": is_failure},
            )
        )

    def record_recovery(
        self, task_id: str, autonomy_level: int, seconds: float
    ) -> None:
        """
        Record mean time to recovery from a failure.

        Args:
            task_id: The task that recovered.
            autonomy_level: L1-L5 autonomy level.
            seconds: Time to recovery in seconds.
        """
        self._record(
            DoraDataPoint(
                metric="mttr",
                autonomy_level=autonomy_level,
                value=seconds,
                unit="seconds",
                task_id=task_id,
            )
        )

    def get_cfr(self, autonomy_level: int, window_days: int = 7) -> float:
        """
        Compute Change Fail Rate for a given autonomy level over a time window.

        This is the primary input for the anti-instability loop.

        Args:
            autonomy_level: L1-L5 to query.
            window_days: Rolling window in days.

        Returns:
            CFR as a percentage (0-100). Returns 0.0 if no data.
        """
        records = self._query_metric("change_fail_rate", autonomy_level, window_days)
        if not records:
            return 0.0

        failures = sum(1 for r in records if r.get("value", 0) == 1.0)
        return round((failures / len(records)) * 100, 2)

    def get_snapshot(self, autonomy_level: int, window_days: int = 7) -> DoraSnapshot:
        """
        Get a complete DORA snapshot for a given autonomy level.

        Args:
            autonomy_level: L1-L5 to query.
            window_days: Rolling window in days.

        Returns:
            DoraSnapshot with all four metrics.
        """
        # Lead time (average)
        lt_records = self._query_metric("lead_time", autonomy_level, window_days)
        avg_lead_time = (
            sum(r.get("value", 0) for r in lt_records) / len(lt_records)
            if lt_records
            else 0.0
        )

        # Deploy frequency (count per week)
        df_records = self._query_metric("deploy_frequency", autonomy_level, window_days)
        deploy_freq = len(df_records) * (7 / max(window_days, 1))

        # CFR
        cfr = self.get_cfr(autonomy_level, window_days)

        # MTTR (average)
        mttr_records = self._query_metric("mttr", autonomy_level, window_days)
        avg_mttr = (
            sum(r.get("value", 0) for r in mttr_records) / len(mttr_records)
            if mttr_records
            else 0.0
        )

        total_samples = len(lt_records) + len(df_records) + len(mttr_records)

        return DoraSnapshot(
            autonomy_level=autonomy_level,
            lead_time_seconds=round(avg_lead_time, 1),
            deploy_frequency_per_week=round(deploy_freq, 1),
            change_fail_rate_percent=cfr,
            mttr_seconds=round(avg_mttr, 1),
            sample_size=total_samples,
            window_days=window_days,
        )

    def get_calibration_report(self) -> dict[str, Any]:
        """
        Generate weekly calibration report comparing CFR across autonomy levels.

        Anomaly: If higher autonomy produces worse stability, calibration is wrong.

        Returns:
            Dict with per-level CFR and anomaly flags.
        """
        report: dict[str, Any] = {"levels": {}, "anomalies": []}

        cfr_by_level: dict[int, float] = {}
        for level in range(1, 6):
            cfr = self.get_cfr(level, window_days=7)
            cfr_by_level[level] = cfr
            report["levels"][f"L{level}"] = {"cfr_percent": cfr}

        # Detect anomalies: higher level should not have higher CFR
        for level in range(2, 6):
            if cfr_by_level[level] > cfr_by_level[level - 1] and cfr_by_level[level] > 0:
                report["anomalies"].append(
                    {
                        "type": "calibration_inversion",
                        "higher_level": level,
                        "higher_cfr": cfr_by_level[level],
                        "lower_level": level - 1,
                        "lower_cfr": cfr_by_level[level - 1],
                        "message": (
                            f"L{level} CFR ({cfr_by_level[level]}%) > "
                            f"L{level-1} CFR ({cfr_by_level[level-1]}%). "
                            f"Autonomy calibration may be wrong."
                        ),
                    }
                )

        return report

    def _record(self, data_point: DoraDataPoint) -> None:
        """Persist a DORA data point to DynamoDB."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()

        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": (
                        f"dora#{data_point.metric}#L{data_point.autonomy_level}#{now}"
                    ),
                    "metric_type": f"dora_{data_point.metric}",
                    "task_id": data_point.task_id,
                    "recorded_at": now,
                    "data": json.dumps(
                        {
                            "metric": data_point.metric,
                            "autonomy_level": data_point.autonomy_level,
                            "value": data_point.value,
                            "unit": data_point.unit,
                            "metadata": data_point.metadata or {},
                        }
                    ),
                }
            )
        except ClientError as e:
            logger.warning("Failed to record DORA metric %s: %s", data_point.metric, str(e))

    def _query_metric(
        self, metric: str, autonomy_level: int, window_days: int
    ) -> list[dict[str, Any]]:
        """Query metric records for a given level and time window."""
        if not self._metrics_table:
            return []

        table = self._dynamodb.Table(self._metrics_table)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
        prefix = f"dora#{metric}#L{autonomy_level}#"

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
            logger.warning("Failed to query DORA metric %s: %s", metric, str(e))
            return []
