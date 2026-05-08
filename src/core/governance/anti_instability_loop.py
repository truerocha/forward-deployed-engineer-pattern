"""
Anti-Instability Feedback Loop — DORA A11 Implementation.

Mechanical implementation of DORA 2025's central thesis:
"Speed without stability is a trap."

When Change Fail Rate (CFR) rises above threshold, the factory automatically
reduces autonomy level. This prevents the speed-stability paradox where
increased throughput creates instability.

Triggers:
  - CFR > 15% over 7-day window: reduce autonomy by 1 level
  - CFR > 30% over 3-day window: reduce by 2 levels + alert Staff Engineer
  - CFR = 0% over 30-day window: eligible for promotion (3 consecutive clean windows)

Restoration:
  - Auto-restore after 14 days of CFR < 10% (for 1-level reductions)
  - Manual restore only for 2-level reductions (requires Staff Engineer review)

Audit trail:
  - Every adjustment recorded in DynamoDB metrics table
  - SK pattern: autonomy_adjustment#{timestamp}
  - Includes: reason, old_level, new_level, cfr_data, trigger_type

Ref: docs/design/fde-core-brain-development.md Section 4.3
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.core.metrics.dora_metrics import DoraMetrics

logger = logging.getLogger(__name__)

# Threshold configuration (configurable via environment)
_CFR_THRESHOLD_MODERATE = 15.0  # % over 7-day window -> reduce by 1
_CFR_THRESHOLD_SEVERE = 30.0  # % over 3-day window -> reduce by 2
_CFR_CLEAN_THRESHOLD = 10.0  # % below which is considered "clean"
_CFR_PROMOTION_THRESHOLD = 0.0  # % for promotion eligibility
_RESTORATION_WINDOW_DAYS = 14  # Days of clean CFR before auto-restore
_PROMOTION_CONSECUTIVE_WINDOWS = 3  # Clean 30-day windows needed for promotion
_OBSERVE_ONLY_DAYS = 30  # Initial observe-only period (no auto-adjustments)


class AdjustmentType(Enum):
    """Type of autonomy adjustment."""

    MODERATE_REDUCTION = "moderate_reduction"  # -1 level
    SEVERE_REDUCTION = "severe_reduction"  # -2 levels
    AUTO_RESTORATION = "auto_restoration"  # +1 level (auto)
    MANUAL_RESTORATION = "manual_restoration"  # +N levels (Staff Engineer)
    PROMOTION = "promotion"  # +1 level (earned)
    MANUAL_OVERRIDE = "manual_override"  # Any direction (Staff Engineer)


@dataclass
class AutonomyAdjustment:
    """Record of an autonomy level adjustment."""

    project_id: str
    adjustment_type: AdjustmentType
    old_level: int
    new_level: int
    reason: str
    cfr_data: dict[str, float]
    trigger_window_days: int
    timestamp: str = ""
    requires_manual_restore: bool = False
    staff_engineer_notified: bool = False

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


@dataclass
class LoopState:
    """Current state of the anti-instability loop for a project."""

    project_id: str
    current_autonomy_level: int
    observe_only: bool  # True during initial 30-day period
    last_adjustment: AutonomyAdjustment | None = None
    cfr_by_level: dict[int, float] | None = None
    restoration_eligible: bool = False
    promotion_eligible: bool = False
    days_since_last_adjustment: int = 0


class AntiInstabilityLoop:
    """
    Monitors CFR and automatically adjusts autonomy levels.

    The loop runs on a schedule (daily via EventBridge) or can be
    invoked on-demand by the orchestrator before dispatching a task.

    Modes:
      - observe_only: Logs recommendations but does not auto-adjust (first 30 days)
      - active: Auto-adjusts autonomy level based on CFR thresholds

    Usage:
        loop = AntiInstabilityLoop(project_id="my-repo")
        state = loop.evaluate()
        # state.current_autonomy_level reflects any adjustments made
    """

    def __init__(
        self,
        project_id: str = "",
        metrics_table: str | None = None,
        observe_only: bool | None = None,
        cfr_threshold_moderate: float = _CFR_THRESHOLD_MODERATE,
        cfr_threshold_severe: float = _CFR_THRESHOLD_SEVERE,
    ):
        self._project_id = project_id or os.environ.get("PROJECT_ID", "global")
        self._metrics_table = metrics_table or os.environ.get("METRICS_TABLE", "")
        self._cfr_moderate = cfr_threshold_moderate
        self._cfr_severe = cfr_threshold_severe
        self._dynamodb = boto3.resource("dynamodb")
        self._cloudwatch = boto3.client("cloudwatch")
        self._dora = DoraMetrics(project_id=self._project_id, metrics_table=self._metrics_table)

        # Determine observe-only mode
        if observe_only is not None:
            self._observe_only = observe_only
        else:
            self._observe_only = os.environ.get("ANTI_INSTABILITY_OBSERVE_ONLY", "true").lower() == "true"

    def evaluate(self) -> LoopState:
        """
        Evaluate current CFR and determine if autonomy adjustment is needed.

        This is the main entry point. Call daily or before task dispatch.

        Returns:
            LoopState with current level and any adjustments made.
        """
        current_level = self._get_current_autonomy_level()
        state = LoopState(
            project_id=self._project_id,
            current_autonomy_level=current_level,
            observe_only=self._observe_only,
        )

        # Compute CFR for all levels
        cfr_by_level = {}
        for level in range(1, 6):
            cfr_by_level[level] = self._dora.get_cfr(level, window_days=7)
        state.cfr_by_level = cfr_by_level

        # Check severe threshold (3-day window, current level)
        cfr_3day = self._dora.get_cfr(current_level, window_days=3)
        if cfr_3day > self._cfr_severe:
            adjustment = self._reduce_autonomy(
                current_level=current_level,
                reduction=2,
                reason=f"CFR {cfr_3day:.1f}% > {self._cfr_severe}% over 3-day window",
                cfr_data={"cfr_3day": cfr_3day, "threshold": self._cfr_severe},
                trigger_window=3,
                requires_manual_restore=True,
            )
            state.current_autonomy_level = adjustment.new_level
            state.last_adjustment = adjustment
            return state

        # Check moderate threshold (7-day window, current level)
        cfr_7day = cfr_by_level.get(current_level, 0.0)
        if cfr_7day > self._cfr_moderate:
            adjustment = self._reduce_autonomy(
                current_level=current_level,
                reduction=1,
                reason=f"CFR {cfr_7day:.1f}% > {self._cfr_moderate}% over 7-day window",
                cfr_data={"cfr_7day": cfr_7day, "threshold": self._cfr_moderate},
                trigger_window=7,
                requires_manual_restore=False,
            )
            state.current_autonomy_level = adjustment.new_level
            state.last_adjustment = adjustment
            return state

        # Check restoration eligibility (14 days of clean CFR)
        if self._check_restoration_eligible(current_level):
            state.restoration_eligible = True
            if not self._observe_only:
                last_adj = self._get_last_adjustment()
                if last_adj and not last_adj.requires_manual_restore:
                    adjustment = self._restore_autonomy(current_level)
                    if adjustment:
                        state.current_autonomy_level = adjustment.new_level
                        state.last_adjustment = adjustment

        # Check promotion eligibility (30-day zero CFR)
        if self._check_promotion_eligible(current_level):
            state.promotion_eligible = True

        return state

    def get_current_level(self) -> int:
        """Get the current autonomy level for this project."""
        return self._get_current_autonomy_level()

    def manual_override(self, new_level: int, reason: str) -> AutonomyAdjustment:
        """
        Staff Engineer manual override of autonomy level.

        Args:
            new_level: Target autonomy level (1-5).
            reason: Justification for the override.

        Returns:
            The adjustment record.
        """
        current_level = self._get_current_autonomy_level()
        adjustment = AutonomyAdjustment(
            project_id=self._project_id,
            adjustment_type=AdjustmentType.MANUAL_OVERRIDE,
            old_level=current_level,
            new_level=max(1, min(5, new_level)),
            reason=f"Manual override by Staff Engineer: {reason}",
            cfr_data={},
            trigger_window_days=0,
        )
        self._persist_adjustment(adjustment)
        self._update_autonomy_level(adjustment.new_level)
        return adjustment

    def _reduce_autonomy(
        self,
        current_level: int,
        reduction: int,
        reason: str,
        cfr_data: dict[str, float],
        trigger_window: int,
        requires_manual_restore: bool,
    ) -> AutonomyAdjustment:
        """Reduce autonomy level and persist the adjustment."""
        new_level = max(1, current_level - reduction)
        adj_type = (
            AdjustmentType.SEVERE_REDUCTION
            if reduction >= 2
            else AdjustmentType.MODERATE_REDUCTION
        )

        adjustment = AutonomyAdjustment(
            project_id=self._project_id,
            adjustment_type=adj_type,
            old_level=current_level,
            new_level=new_level,
            reason=reason,
            cfr_data=cfr_data,
            trigger_window_days=trigger_window,
            requires_manual_restore=requires_manual_restore,
            staff_engineer_notified=requires_manual_restore,
        )

        if self._observe_only:
            logger.warning(
                "[OBSERVE-ONLY] Would reduce autonomy L%d -> L%d: %s",
                current_level,
                new_level,
                reason,
            )
        else:
            logger.warning(
                "Reducing autonomy L%d -> L%d: %s",
                current_level,
                new_level,
                reason,
            )
            self._persist_adjustment(adjustment)
            self._update_autonomy_level(new_level)

            if requires_manual_restore:
                self._notify_staff_engineer(adjustment)

        return adjustment

    def _restore_autonomy(self, current_level: int) -> AutonomyAdjustment | None:
        """Restore autonomy by 1 level after clean period."""
        if current_level >= 5:
            return None

        new_level = current_level + 1
        adjustment = AutonomyAdjustment(
            project_id=self._project_id,
            adjustment_type=AdjustmentType.AUTO_RESTORATION,
            old_level=current_level,
            new_level=new_level,
            reason=f"CFR < {_CFR_CLEAN_THRESHOLD}% for {_RESTORATION_WINDOW_DAYS} days",
            cfr_data={"cfr_14day": self._dora.get_cfr(current_level, window_days=14)},
            trigger_window_days=_RESTORATION_WINDOW_DAYS,
        )

        logger.info(
            "Auto-restoring autonomy L%d -> L%d (clean CFR for %d days)",
            current_level,
            new_level,
            _RESTORATION_WINDOW_DAYS,
        )
        self._persist_adjustment(adjustment)
        self._update_autonomy_level(new_level)
        return adjustment

    def _check_restoration_eligible(self, current_level: int) -> bool:
        """Check if CFR has been below threshold for restoration window."""
        cfr_14day = self._dora.get_cfr(current_level, window_days=_RESTORATION_WINDOW_DAYS)
        return cfr_14day < _CFR_CLEAN_THRESHOLD

    def _check_promotion_eligible(self, current_level: int) -> bool:
        """Check if CFR has been zero for promotion eligibility."""
        if current_level >= 5:
            return False
        cfr_30day = self._dora.get_cfr(current_level, window_days=30)
        return cfr_30day == _CFR_PROMOTION_THRESHOLD

    def _get_current_autonomy_level(self) -> int:
        """Read current autonomy level from DynamoDB."""
        if not self._metrics_table:
            return 3  # Default to L3

        table = self._dynamodb.Table(self._metrics_table)
        try:
            response = table.get_item(
                Key={
                    "project_id": self._project_id,
                    "metric_key": "autonomy#current_level",
                }
            )
            if "Item" in response:
                data = json.loads(response["Item"].get("data", "{}"))
                return data.get("level", 3)
            return 3  # Default
        except ClientError as e:
            logger.warning("Failed to read autonomy level: %s", str(e))
            return 3

    def _update_autonomy_level(self, new_level: int) -> None:
        """Write new autonomy level to DynamoDB."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        now = datetime.now(timezone.utc).isoformat()
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": "autonomy#current_level",
                    "metric_type": "autonomy",
                    "task_id": "",
                    "recorded_at": now,
                    "data": json.dumps({"level": new_level, "updated_at": now}),
                }
            )
        except ClientError as e:
            logger.error("Failed to update autonomy level: %s", str(e))

    def _persist_adjustment(self, adjustment: AutonomyAdjustment) -> None:
        """Persist adjustment to audit trail in DynamoDB."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"autonomy_adjustment#{adjustment.timestamp}",
                    "metric_type": "autonomy_adjustment",
                    "task_id": "",
                    "recorded_at": adjustment.timestamp,
                    "data": json.dumps(
                        {
                            "adjustment_type": adjustment.adjustment_type.value,
                            "old_level": adjustment.old_level,
                            "new_level": adjustment.new_level,
                            "reason": adjustment.reason,
                            "cfr_data": adjustment.cfr_data,
                            "trigger_window_days": adjustment.trigger_window_days,
                            "requires_manual_restore": adjustment.requires_manual_restore,
                            "staff_engineer_notified": adjustment.staff_engineer_notified,
                        }
                    ),
                }
            )
        except ClientError as e:
            logger.error("Failed to persist autonomy adjustment: %s", str(e))

    def _get_last_adjustment(self) -> AutonomyAdjustment | None:
        """Get the most recent autonomy adjustment."""
        if not self._metrics_table:
            return None

        table = self._dynamodb.Table(self._metrics_table)
        try:
            response = table.query(
                KeyConditionExpression=(
                    "project_id = :pid AND begins_with(metric_key, :prefix)"
                ),
                ExpressionAttributeValues={
                    ":pid": self._project_id,
                    ":prefix": "autonomy_adjustment#",
                },
                ScanIndexForward=False,
                Limit=1,
            )
            items = response.get("Items", [])
            if not items:
                return None

            data = json.loads(items[0].get("data", "{}"))
            return AutonomyAdjustment(
                project_id=self._project_id,
                adjustment_type=AdjustmentType(data.get("adjustment_type", "moderate_reduction")),
                old_level=data.get("old_level", 3),
                new_level=data.get("new_level", 3),
                reason=data.get("reason", ""),
                cfr_data=data.get("cfr_data", {}),
                trigger_window_days=data.get("trigger_window_days", 7),
                requires_manual_restore=data.get("requires_manual_restore", False),
                timestamp=items[0].get("recorded_at", ""),
            )
        except ClientError as e:
            logger.warning("Failed to get last adjustment: %s", str(e))
            return None

    def _notify_staff_engineer(self, adjustment: AutonomyAdjustment) -> None:
        """Emit CloudWatch alarm for severe autonomy reduction."""
        try:
            self._cloudwatch.put_metric_data(
                Namespace="FDE/Factory",
                MetricData=[
                    {
                        "MetricName": "AutonomyLevelReduced",
                        "Value": float(adjustment.new_level),
                        "Unit": "None",
                        "Dimensions": [
                            {"Name": "ProjectId", "Value": self._project_id},
                            {"Name": "AdjustmentType", "Value": adjustment.adjustment_type.value},
                        ],
                    }
                ],
            )
        except ClientError as e:
            logger.warning("Failed to notify Staff Engineer via CloudWatch: %s", str(e))
