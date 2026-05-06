"""
Observability Emitter — Cross-cutting structured logging, CloudWatch metrics,
and failure reporting for all onboarding pipeline stages.

Design ref: §3.10 Observability Emitter
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger("fde-onboarding.observability")

NAMESPACE = "fde/onboarding"


@dataclass
class StageMetrics:
    """Metrics collected during a single pipeline stage."""

    stage_name: str
    start_time: float = field(default_factory=time.time)
    end_time: float = 0.0
    duration_ms: int = 0
    files_processed: int = 0
    modules_found: int = 0
    edges_found: int = 0
    conventions_found: int = 0
    errors_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    extra: dict = field(default_factory=dict)

    def complete(self) -> "StageMetrics":
        self.end_time = time.time()
        self.duration_ms = int((self.end_time - self.start_time) * 1000)
        return self


@dataclass
class OnboardingFailureReport:
    """Failure report written to S3 on unrecoverable error."""

    correlation_id: str
    repo_url: Optional[str]
    mode: str
    failed_stage: str
    error_type: str
    error_message: str
    partial_results: dict
    stages_completed: list[str]
    stages_remaining: list[str]
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_duration_ms: int = 0


class ObservabilityEmitter:
    """Emits structured logs, CloudWatch metrics, and failure reports."""

    def __init__(
        self,
        correlation_id: str,
        mode: str,
        repo_owner: str = "",
        repo_name: str = "",
        environment: str = "dev",
    ):
        self.correlation_id = correlation_id
        self.mode = mode
        self.repo_owner = repo_owner
        self.repo_name = repo_name
        self.environment = environment
        self._stages_completed: list[str] = []
        self._pipeline_start = time.time()
        self._cloudwatch = None

        if mode == "cloud":
            try:
                self._cloudwatch = boto3.client(
                    "cloudwatch",
                    region_name=os.environ.get("AWS_REGION", "us-east-1"),
                )
            except Exception as e:
                logger.warning("CloudWatch client unavailable: %s", e)

    def emit_stage_start(self, stage_name: str) -> StageMetrics:
        """Log stage start and return a StageMetrics tracker."""
        self._log("stage_start", stage_name)
        return StageMetrics(stage_name=stage_name)

    def emit_stage_complete(self, metrics: StageMetrics) -> None:
        """Log stage completion and publish CloudWatch metrics."""
        metrics.complete()
        self._stages_completed.append(metrics.stage_name)
        self._log("stage_complete", metrics.stage_name, metrics)
        self._publish_metric("stage_duration", metrics.duration_ms, "Milliseconds", {
            "stage_name": metrics.stage_name,
            "mode": self.mode,
        })
        if metrics.errors_count > 0:
            self._publish_metric("error_count", metrics.errors_count, "Count", {
                "stage_name": metrics.stage_name,
            })

    def emit_stage_error(self, stage_name: str, error: Exception) -> None:
        """Log a stage error."""
        self._log("stage_error", stage_name, extra={
            "error_type": type(error).__name__,
            "error_message": str(error),
        })

    def emit_pipeline_complete(self) -> None:
        """Log pipeline completion with total duration."""
        total_ms = int((time.time() - self._pipeline_start) * 1000)
        self._log("pipeline_complete", "all", extra={"total_duration_ms": total_ms})
        self._publish_metric("total_duration", total_ms, "Milliseconds", {
            "mode": self.mode,
            "repo_owner": self.repo_owner,
        })

    def build_failure_report(
        self,
        failed_stage: str,
        error: Exception,
        partial_results: dict,
        all_stages: list[str],
        repo_url: Optional[str] = None,
    ) -> OnboardingFailureReport:
        """Build a structured failure report."""
        remaining = [s for s in all_stages if s not in self._stages_completed and s != failed_stage]
        total_ms = int((time.time() - self._pipeline_start) * 1000)
        return OnboardingFailureReport(
            correlation_id=self.correlation_id,
            repo_url=repo_url,
            mode=self.mode,
            failed_stage=failed_stage,
            error_type=type(error).__name__,
            error_message=str(error),
            partial_results=partial_results,
            stages_completed=list(self._stages_completed),
            stages_remaining=remaining,
            total_duration_ms=total_ms,
        )

    @property
    def stages_completed(self) -> list[str]:
        return list(self._stages_completed)

    def _log(self, event: str, stage_name: str, metrics: Optional[StageMetrics] = None, extra: Optional[dict] = None) -> None:
        """Emit a structured JSON log line."""
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "correlation_id": self.correlation_id,
            "stage_name": stage_name,
            "event": event,
            "mode": self.mode,
            "repo_owner": self.repo_owner,
            "repo_name": self.repo_name,
        }
        if metrics:
            record["duration_ms"] = metrics.duration_ms
            record["files_processed"] = metrics.files_processed
            record["errors_count"] = metrics.errors_count
        if extra:
            record.update(extra)
        logger.info(json.dumps(record))

    def _publish_metric(self, name: str, value: float, unit: str, dimensions: dict) -> None:
        """Publish a metric to CloudWatch (cloud mode only)."""
        if not self._cloudwatch:
            return
        try:
            self._cloudwatch.put_metric_data(
                Namespace=NAMESPACE,
                MetricData=[{
                    "MetricName": name,
                    "Value": value,
                    "Unit": unit,
                    "Dimensions": [
                        {"Name": k, "Value": v} for k, v in dimensions.items()
                    ],
                }],
            )
        except ClientError as e:
            logger.warning("Failed to publish metric %s: %s", name, e)
