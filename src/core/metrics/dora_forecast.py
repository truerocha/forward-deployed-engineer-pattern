"""
DORA Forecast Engine — Predictive DORA metrics for the FDE pipeline.

Implements PEC Blueprint Chapter 11 ("DORA Sun"):
  "The Lambda de integração cruzando métricas de RAG, probabilidade de risco
   e telemetria para pulsar a interface."

The forecast engine:
  1. Reads historical DORA metrics (rolling window from DoraMetrics)
  2. Computes trend direction per metric (improving/stable/degrading)
  3. Projects future values using EWMA (Exponential Weighted Moving Average)
  4. Classifies projected DORA level at T+7d and T+30d
  5. Identifies the "weakest link" metric dragging the team down
  6. Integrates with Risk Engine (risk trend feeds into CFR forecast)

Integration:
  - Reads from DoraMetrics (src/core/metrics/dora_metrics.py)
  - Reads from RiskInferenceEngine (src/core/risk/) for risk trend signal
  - Emits forecast events for portal "DORA Sun" visualization
  - Consumed by anti-instability loop for proactive autonomy adjustment

Feature flag: DORA_FORECAST_ENABLED (default: true)

Source: PEC Blueprint Chapter 11 + Chapter 2 (DORA-Driven AI Mathematical Engineering)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger("fde.metrics.dora_forecast")


class TrendDirection(str, Enum):
    IMPROVING = "improving"
    STABLE = "stable"
    DEGRADING = "degrading"


class DoraLevel(str, Enum):
    ELITE = "Elite"
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


_LEVEL_THRESHOLDS = {
    "lead_time_seconds": {DoraLevel.ELITE: 3600, DoraLevel.HIGH: 86400, DoraLevel.MEDIUM: 604800},
    "deploy_frequency_per_week": {DoraLevel.ELITE: 7.0, DoraLevel.HIGH: 1.0, DoraLevel.MEDIUM: 0.25},
    "change_fail_rate_percent": {DoraLevel.ELITE: 5.0, DoraLevel.HIGH: 10.0, DoraLevel.MEDIUM: 15.0},
    "mttr_seconds": {DoraLevel.ELITE: 3600, DoraLevel.HIGH: 86400, DoraLevel.MEDIUM: 604800},
}


@dataclass
class MetricTrend:
    metric_name: str
    current_value: float
    projected_7d: float
    projected_30d: float
    trend_direction: TrendDirection
    trend_velocity: float
    current_level: DoraLevel
    projected_level_7d: DoraLevel
    projected_level_30d: DoraLevel
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "current_value": round(self.current_value, 2),
            "projected_7d": round(self.projected_7d, 2),
            "projected_30d": round(self.projected_30d, 2),
            "trend_direction": self.trend_direction.value,
            "trend_velocity": round(self.trend_velocity, 4),
            "current_level": self.current_level.value,
            "projected_level_7d": self.projected_level_7d.value,
            "projected_level_30d": self.projected_level_30d.value,
            "confidence": round(self.confidence, 2),
        }


@dataclass
class DoraForecast:
    project_id: str
    autonomy_level: int
    generated_at: str = ""
    lead_time: MetricTrend | None = None
    deploy_frequency: MetricTrend | None = None
    change_fail_rate: MetricTrend | None = None
    mttr: MetricTrend | None = None
    current_level: DoraLevel = DoraLevel.MEDIUM
    projected_level_7d: DoraLevel = DoraLevel.MEDIUM
    projected_level_30d: DoraLevel = DoraLevel.MEDIUM
    weakest_metric: str = ""
    weakest_reason: str = ""
    risk_adjusted_cfr: float = 0.0
    health_pulse: int = 50

    def __post_init__(self):
        if not self.generated_at:
            self.generated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "autonomy_level": self.autonomy_level,
            "generated_at": self.generated_at,
            "current_level": self.current_level.value,
            "projected_level_7d": self.projected_level_7d.value,
            "projected_level_30d": self.projected_level_30d.value,
            "weakest_metric": self.weakest_metric,
            "weakest_reason": self.weakest_reason,
            "health_pulse": self.health_pulse,
            "risk_adjusted_cfr": round(self.risk_adjusted_cfr, 2),
            "metrics": {
                "lead_time": self.lead_time.to_dict() if self.lead_time else None,
                "deploy_frequency": self.deploy_frequency.to_dict() if self.deploy_frequency else None,
                "change_fail_rate": self.change_fail_rate.to_dict() if self.change_fail_rate else None,
                "mttr": self.mttr.to_dict() if self.mttr else None,
            },
        }

    def to_portal_summary(self) -> str:
        direction_emoji = {TrendDirection.IMPROVING: "↗", TrendDirection.STABLE: "→", TrendDirection.DEGRADING: "↘"}
        parts = [f"DORA: {self.current_level.value} → {self.projected_level_7d.value} (7d)"]
        if self.weakest_metric:
            parts.append(f"Weakest: {self.weakest_metric}")
        if self.lead_time:
            parts.append(f"LT {direction_emoji[self.lead_time.trend_direction]}")
        if self.change_fail_rate:
            parts.append(f"CFR {direction_emoji[self.change_fail_rate.trend_direction]}")
        return " | ".join(parts)


class DoraForecastEngine:
    """Predictive DORA metrics engine using EWMA projection.

    EWMA formula: S_t = α · x_t + (1 - α) · S_{t-1}
    Where α (smoothing factor) controls reactivity to recent data.

    Usage:
        engine = DoraForecastEngine()
        forecast = engine.generate_forecast(
            snapshots=[week1, week2, week3, week4],
            project_id="my-service",
            autonomy_level=4,
            current_risk_score=0.12,
        )
    """

    def __init__(self, alpha: float = 0.3, min_samples: int = 3, enabled: bool | None = None):
        self._alpha = alpha
        self._min_samples = min_samples
        self._enabled = enabled if enabled is not None else os.environ.get("DORA_FORECAST_ENABLED", "true").lower() == "true"

    @property
    def enabled(self) -> bool:
        return self._enabled

    def generate_forecast(
        self,
        snapshots: list[dict[str, float]],
        project_id: str = "",
        autonomy_level: int = 4,
        current_risk_score: float = 0.0,
    ) -> DoraForecast:
        if not self._enabled:
            return self._disabled_forecast(project_id, autonomy_level)

        if len(snapshots) < self._min_samples:
            return self._insufficient_data_forecast(project_id, autonomy_level, len(snapshots))

        lt_trend = self._compute_trend("lead_time_seconds", snapshots, lower_is_better=True)
        df_trend = self._compute_trend("deploy_frequency_per_week", snapshots, lower_is_better=False)
        cfr_trend = self._compute_trend("change_fail_rate_percent", snapshots, lower_is_better=True)
        mttr_trend = self._compute_trend("mttr_seconds", snapshots, lower_is_better=True)

        risk_adjusted_cfr = self._risk_adjust_cfr(cfr_trend, current_risk_score)

        current_level = self._classify_overall_level(lt_trend.current_value, df_trend.current_value, cfr_trend.current_value, mttr_trend.current_value)
        projected_7d = self._classify_overall_level(lt_trend.projected_7d, df_trend.projected_7d, cfr_trend.projected_7d, mttr_trend.projected_7d)
        projected_30d = self._classify_overall_level(lt_trend.projected_30d, df_trend.projected_30d, cfr_trend.projected_30d, mttr_trend.projected_30d)

        weakest_metric, weakest_reason = self._find_weakest_link(lt_trend, df_trend, cfr_trend, mttr_trend)
        health_pulse = self._compute_health_pulse(lt_trend, df_trend, cfr_trend, mttr_trend)

        forecast = DoraForecast(
            project_id=project_id, autonomy_level=autonomy_level,
            lead_time=lt_trend, deploy_frequency=df_trend,
            change_fail_rate=cfr_trend, mttr=mttr_trend,
            current_level=current_level, projected_level_7d=projected_7d,
            projected_level_30d=projected_30d,
            weakest_metric=weakest_metric, weakest_reason=weakest_reason,
            risk_adjusted_cfr=risk_adjusted_cfr, health_pulse=health_pulse,
        )

        logger.info(
            "DORA forecast: project=%s level=%s->%s(7d)->%s(30d) weakest=%s pulse=%d",
            project_id, current_level.value, projected_7d.value, projected_30d.value, weakest_metric, health_pulse,
        )
        return forecast

    def _compute_trend(self, metric_name: str, snapshots: list[dict[str, float]], lower_is_better: bool) -> MetricTrend:
        values = [s.get(metric_name, 0.0) for s in snapshots]
        values = [v for v in values if v is not None]

        if not values:
            return self._empty_trend(metric_name)

        current = values[-1]
        smoothed = self._ewma(values)

        if len(smoothed) >= 2:
            total_change = smoothed[-1] - smoothed[0]
            days_observed = max(1, (len(smoothed) - 1) * 7)
            velocity = total_change / days_observed
        else:
            velocity = 0.0

        projected_7d = max(0.0, smoothed[-1] + velocity * 7)
        projected_30d = max(0.0, smoothed[-1] + velocity * 30)

        direction = self._classify_direction(velocity, lower_is_better)
        current_level = self._classify_metric_level(metric_name, current)
        level_7d = self._classify_metric_level(metric_name, projected_7d)
        level_30d = self._classify_metric_level(metric_name, projected_30d)
        confidence = min(1.0, len(values) / 8.0)

        return MetricTrend(
            metric_name=metric_name, current_value=current,
            projected_7d=projected_7d, projected_30d=projected_30d,
            trend_direction=direction, trend_velocity=velocity,
            current_level=current_level, projected_level_7d=level_7d,
            projected_level_30d=level_30d, confidence=confidence,
        )

    def _ewma(self, values: list[float]) -> list[float]:
        if not values:
            return []
        smoothed = [values[0]]
        for i in range(1, len(values)):
            s = self._alpha * values[i] + (1 - self._alpha) * smoothed[-1]
            smoothed.append(s)
        return smoothed

    def _classify_direction(self, velocity: float, lower_is_better: bool) -> TrendDirection:
        stability_threshold = 0.01
        if abs(velocity) < stability_threshold:
            return TrendDirection.STABLE
        if lower_is_better:
            return TrendDirection.IMPROVING if velocity < 0 else TrendDirection.DEGRADING
        else:
            return TrendDirection.IMPROVING if velocity > 0 else TrendDirection.DEGRADING

    def _classify_metric_level(self, metric_name: str, value: float) -> DoraLevel:
        thresholds = _LEVEL_THRESHOLDS.get(metric_name, {})
        if not thresholds:
            return DoraLevel.MEDIUM

        if metric_name in ("lead_time_seconds", "change_fail_rate_percent", "mttr_seconds"):
            if value <= thresholds[DoraLevel.ELITE]:
                return DoraLevel.ELITE
            if value <= thresholds[DoraLevel.HIGH]:
                return DoraLevel.HIGH
            if value <= thresholds[DoraLevel.MEDIUM]:
                return DoraLevel.MEDIUM
            return DoraLevel.LOW

        if metric_name == "deploy_frequency_per_week":
            if value >= thresholds[DoraLevel.ELITE]:
                return DoraLevel.ELITE
            if value >= thresholds[DoraLevel.HIGH]:
                return DoraLevel.HIGH
            if value >= thresholds[DoraLevel.MEDIUM]:
                return DoraLevel.MEDIUM
            return DoraLevel.LOW

        return DoraLevel.MEDIUM

    def _classify_overall_level(self, lead_time: float, deploy_freq: float, cfr: float, mttr: float) -> DoraLevel:
        levels = [
            self._classify_metric_level("lead_time_seconds", lead_time),
            self._classify_metric_level("deploy_frequency_per_week", deploy_freq),
            self._classify_metric_level("change_fail_rate_percent", cfr),
            self._classify_metric_level("mttr_seconds", mttr),
        ]
        level_order = [DoraLevel.LOW, DoraLevel.MEDIUM, DoraLevel.HIGH, DoraLevel.ELITE]
        min_index = min(level_order.index(l) for l in levels)
        return level_order[min_index]

    def _find_weakest_link(self, lt: MetricTrend, df: MetricTrend, cfr: MetricTrend, mttr: MetricTrend) -> tuple[str, str]:
        level_order = [DoraLevel.LOW, DoraLevel.MEDIUM, DoraLevel.HIGH, DoraLevel.ELITE]
        metrics = [("lead_time", lt), ("deploy_frequency", df), ("change_fail_rate", cfr), ("mttr", mttr)]

        def sort_key(item):
            _, trend = item
            level_idx = level_order.index(trend.current_level)
            trend_penalty = 0 if trend.trend_direction == TrendDirection.DEGRADING else 1
            return (level_idx, trend_penalty)

        sorted_metrics = sorted(metrics, key=sort_key)
        weakest_name, weakest_trend = sorted_metrics[0]

        reasons = {
            "lead_time": f"Lead time at {weakest_trend.current_level.value} ({weakest_trend.current_value:.0f}s)",
            "deploy_frequency": f"Deploy frequency at {weakest_trend.current_level.value} ({weakest_trend.current_value:.1f}/week)",
            "change_fail_rate": f"CFR at {weakest_trend.current_level.value} ({weakest_trend.current_value:.1f}%)",
            "mttr": f"MTTR at {weakest_trend.current_level.value} ({weakest_trend.current_value:.0f}s)",
        }
        reason = reasons.get(weakest_name, "")
        if weakest_trend.trend_direction == TrendDirection.DEGRADING:
            reason += " and degrading"
        return weakest_name, reason

    def _risk_adjust_cfr(self, cfr_trend: MetricTrend, risk_score: float) -> float:
        historical_cfr = cfr_trend.projected_7d
        risk_cfr = risk_score * 100
        return 0.7 * historical_cfr + 0.3 * risk_cfr

    def _compute_health_pulse(self, lt: MetricTrend, df: MetricTrend, cfr: MetricTrend, mttr: MetricTrend) -> int:
        level_scores = {DoraLevel.ELITE: 100, DoraLevel.HIGH: 75, DoraLevel.MEDIUM: 50, DoraLevel.LOW: 25}
        metrics = [lt, df, cfr, mttr]
        base = sum(level_scores[m.current_level] for m in metrics) / 4
        trend_adjustment = 0
        for m in metrics:
            if m.trend_direction == TrendDirection.IMPROVING:
                trend_adjustment += 5
            elif m.trend_direction == TrendDirection.DEGRADING:
                trend_adjustment -= 10
        return int(max(0, min(100, base + trend_adjustment)))

    def _disabled_forecast(self, project_id: str, autonomy_level: int) -> DoraForecast:
        return DoraForecast(project_id=project_id, autonomy_level=autonomy_level, weakest_reason="Forecast engine disabled", health_pulse=50)

    def _insufficient_data_forecast(self, project_id: str, autonomy_level: int, sample_count: int) -> DoraForecast:
        return DoraForecast(project_id=project_id, autonomy_level=autonomy_level, weakest_reason=f"Insufficient data ({sample_count}/{self._min_samples} samples needed)", health_pulse=50)

    def _empty_trend(self, metric_name: str) -> MetricTrend:
        return MetricTrend(metric_name=metric_name, current_value=0.0, projected_7d=0.0, projected_30d=0.0, trend_direction=TrendDirection.STABLE, trend_velocity=0.0, current_level=DoraLevel.MEDIUM, projected_level_7d=DoraLevel.MEDIUM, projected_level_30d=DoraLevel.MEDIUM, confidence=0.0)
