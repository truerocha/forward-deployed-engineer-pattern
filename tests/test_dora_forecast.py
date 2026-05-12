"""
Tests for the DORA Forecast Engine — PEC Blueprint Chapter 11.

Validates:
  1. EWMA computation produces correct smoothed values
  2. Trend direction classification (improving/stable/degrading)
  3. DORA level classification per metric
  4. Overall level = weakest metric
  5. Weakest link identification
  6. Health pulse computation (0-100)
  7. Risk-adjusted CFR blending
  8. Feature flag disables gracefully
  9. Insufficient data handled
  10. End-to-end scenarios (Elite team, degrading team, recovering team)
"""

import pytest

from src.core.metrics.dora_forecast import (
    DoraForecastEngine,
    DoraForecast,
    DoraLevel,
    MetricTrend,
    TrendDirection,
)


@pytest.fixture
def engine():
    return DoraForecastEngine(enabled=True)


@pytest.fixture
def disabled_engine():
    return DoraForecastEngine(enabled=False)


@pytest.fixture
def elite_snapshots():
    return [
        {"lead_time_seconds": 1800, "deploy_frequency_per_week": 14, "change_fail_rate_percent": 2.0, "mttr_seconds": 900},
        {"lead_time_seconds": 1600, "deploy_frequency_per_week": 15, "change_fail_rate_percent": 1.8, "mttr_seconds": 800},
        {"lead_time_seconds": 1500, "deploy_frequency_per_week": 16, "change_fail_rate_percent": 1.5, "mttr_seconds": 750},
        {"lead_time_seconds": 1400, "deploy_frequency_per_week": 17, "change_fail_rate_percent": 1.2, "mttr_seconds": 700},
    ]


@pytest.fixture
def degrading_snapshots():
    return [
        {"lead_time_seconds": 43200, "deploy_frequency_per_week": 5, "change_fail_rate_percent": 6.0, "mttr_seconds": 7200},
        {"lead_time_seconds": 50000, "deploy_frequency_per_week": 4, "change_fail_rate_percent": 8.0, "mttr_seconds": 10000},
        {"lead_time_seconds": 60000, "deploy_frequency_per_week": 3, "change_fail_rate_percent": 11.0, "mttr_seconds": 14000},
        {"lead_time_seconds": 72000, "deploy_frequency_per_week": 2, "change_fail_rate_percent": 13.0, "mttr_seconds": 20000},
    ]


@pytest.fixture
def recovering_snapshots():
    return [
        {"lead_time_seconds": 700000, "deploy_frequency_per_week": 0.1, "change_fail_rate_percent": 25.0, "mttr_seconds": 700000},
        {"lead_time_seconds": 500000, "deploy_frequency_per_week": 0.3, "change_fail_rate_percent": 18.0, "mttr_seconds": 500000},
        {"lead_time_seconds": 300000, "deploy_frequency_per_week": 0.5, "change_fail_rate_percent": 12.0, "mttr_seconds": 300000},
        {"lead_time_seconds": 150000, "deploy_frequency_per_week": 0.8, "change_fail_rate_percent": 8.0, "mttr_seconds": 150000},
    ]


class TestEWMA:
    def test_single_value(self, engine):
        assert engine._ewma([10.0]) == [10.0]

    def test_constant_series(self, engine):
        result = engine._ewma([5.0, 5.0, 5.0, 5.0])
        assert all(abs(v - 5.0) < 0.01 for v in result)

    def test_increasing_series_smoothed(self, engine):
        result = engine._ewma([1.0, 2.0, 3.0, 4.0, 5.0])
        assert result[-1] < 5.0
        assert result[-1] > result[0]

    def test_empty_series(self, engine):
        assert engine._ewma([]) == []


class TestTrendDirection:
    def test_improving_lower_is_better(self, engine):
        assert engine._classify_direction(-100.0, lower_is_better=True) == TrendDirection.IMPROVING

    def test_degrading_lower_is_better(self, engine):
        assert engine._classify_direction(100.0, lower_is_better=True) == TrendDirection.DEGRADING

    def test_improving_higher_is_better(self, engine):
        assert engine._classify_direction(0.5, lower_is_better=False) == TrendDirection.IMPROVING

    def test_degrading_higher_is_better(self, engine):
        assert engine._classify_direction(-0.5, lower_is_better=False) == TrendDirection.DEGRADING

    def test_stable_near_zero(self, engine):
        assert engine._classify_direction(0.005, lower_is_better=True) == TrendDirection.STABLE


class TestLevelClassification:
    def test_elite_lead_time(self, engine):
        assert engine._classify_metric_level("lead_time_seconds", 1800) == DoraLevel.ELITE

    def test_high_lead_time(self, engine):
        assert engine._classify_metric_level("lead_time_seconds", 43200) == DoraLevel.HIGH

    def test_medium_lead_time(self, engine):
        assert engine._classify_metric_level("lead_time_seconds", 300000) == DoraLevel.MEDIUM

    def test_low_lead_time(self, engine):
        assert engine._classify_metric_level("lead_time_seconds", 700000) == DoraLevel.LOW

    def test_elite_deploy_frequency(self, engine):
        assert engine._classify_metric_level("deploy_frequency_per_week", 14) == DoraLevel.ELITE

    def test_low_deploy_frequency(self, engine):
        assert engine._classify_metric_level("deploy_frequency_per_week", 0.1) == DoraLevel.LOW

    def test_elite_cfr(self, engine):
        assert engine._classify_metric_level("change_fail_rate_percent", 2.0) == DoraLevel.ELITE

    def test_low_cfr(self, engine):
        assert engine._classify_metric_level("change_fail_rate_percent", 20.0) == DoraLevel.LOW

    def test_overall_level_is_weakest(self, engine):
        level = engine._classify_overall_level(1800, 14, 12.0, 1800)
        assert level == DoraLevel.MEDIUM


class TestForecastGeneration:
    def test_elite_team_stays_elite(self, engine, elite_snapshots):
        forecast = engine.generate_forecast(elite_snapshots, project_id="elite-svc", autonomy_level=5)
        assert forecast.current_level == DoraLevel.ELITE
        assert forecast.projected_level_7d == DoraLevel.ELITE
        assert forecast.health_pulse >= 80

    def test_degrading_team_projects_lower(self, engine, degrading_snapshots):
        forecast = engine.generate_forecast(degrading_snapshots, project_id="degrading-svc", autonomy_level=4)
        assert forecast.current_level in (DoraLevel.HIGH, DoraLevel.MEDIUM)
        level_order = [DoraLevel.LOW, DoraLevel.MEDIUM, DoraLevel.HIGH, DoraLevel.ELITE]
        assert level_order.index(forecast.projected_level_30d) <= level_order.index(forecast.current_level)

    def test_recovering_team_projects_higher(self, engine, recovering_snapshots):
        forecast = engine.generate_forecast(recovering_snapshots, project_id="recovering-svc", autonomy_level=3)
        assert forecast.lead_time.trend_direction == TrendDirection.IMPROVING
        assert forecast.change_fail_rate.trend_direction == TrendDirection.IMPROVING

    def test_disabled_engine_returns_neutral(self, disabled_engine, elite_snapshots):
        forecast = disabled_engine.generate_forecast(elite_snapshots, project_id="x")
        assert forecast.health_pulse == 50
        assert forecast.current_level == DoraLevel.MEDIUM
        assert "disabled" in forecast.weakest_reason.lower()

    def test_insufficient_data(self, engine):
        forecast = engine.generate_forecast([{"lead_time_seconds": 1000}], project_id="x")
        assert "Insufficient" in forecast.weakest_reason
        assert forecast.health_pulse == 50


class TestWeakestLink:
    def test_identifies_low_metric(self, engine):
        snapshots = [
            {"lead_time_seconds": 1800, "deploy_frequency_per_week": 14, "change_fail_rate_percent": 18.0, "mttr_seconds": 1800},
            {"lead_time_seconds": 1700, "deploy_frequency_per_week": 15, "change_fail_rate_percent": 19.0, "mttr_seconds": 1700},
            {"lead_time_seconds": 1600, "deploy_frequency_per_week": 16, "change_fail_rate_percent": 20.0, "mttr_seconds": 1600},
        ]
        forecast = engine.generate_forecast(snapshots, project_id="x")
        assert forecast.weakest_metric == "change_fail_rate"

    def test_degrading_metric_prioritized(self, engine):
        snapshots = [
            {"lead_time_seconds": 300000, "deploy_frequency_per_week": 14, "change_fail_rate_percent": 12.0, "mttr_seconds": 1800},
            {"lead_time_seconds": 300000, "deploy_frequency_per_week": 14, "change_fail_rate_percent": 13.0, "mttr_seconds": 1800},
            {"lead_time_seconds": 300000, "deploy_frequency_per_week": 14, "change_fail_rate_percent": 14.0, "mttr_seconds": 1800},
        ]
        forecast = engine.generate_forecast(snapshots, project_id="x")
        assert forecast.weakest_metric == "change_fail_rate"
        assert "degrading" in forecast.weakest_reason


class TestHealthPulse:
    def test_all_elite_improving_near_100(self, engine, elite_snapshots):
        forecast = engine.generate_forecast(elite_snapshots, project_id="x")
        assert forecast.health_pulse >= 80

    def test_all_low_degrading_near_0(self, engine):
        snapshots = [
            {"lead_time_seconds": 700000, "deploy_frequency_per_week": 0.05, "change_fail_rate_percent": 30.0, "mttr_seconds": 700000},
            {"lead_time_seconds": 800000, "deploy_frequency_per_week": 0.04, "change_fail_rate_percent": 35.0, "mttr_seconds": 800000},
            {"lead_time_seconds": 900000, "deploy_frequency_per_week": 0.03, "change_fail_rate_percent": 40.0, "mttr_seconds": 900000},
        ]
        forecast = engine.generate_forecast(snapshots, project_id="x")
        assert forecast.health_pulse <= 30

    def test_pulse_bounded_0_100(self, engine, elite_snapshots, degrading_snapshots):
        for snapshots in [elite_snapshots, degrading_snapshots]:
            forecast = engine.generate_forecast(snapshots, project_id="x")
            assert 0 <= forecast.health_pulse <= 100


class TestRiskIntegration:
    def test_high_risk_increases_cfr_forecast(self, engine, elite_snapshots):
        forecast_no_risk = engine.generate_forecast(elite_snapshots, project_id="x", current_risk_score=0.0)
        forecast_high_risk = engine.generate_forecast(elite_snapshots, project_id="x", current_risk_score=0.5)
        assert forecast_high_risk.risk_adjusted_cfr > forecast_no_risk.risk_adjusted_cfr

    def test_zero_risk_no_adjustment(self, engine, elite_snapshots):
        forecast = engine.generate_forecast(elite_snapshots, project_id="x", current_risk_score=0.0)
        assert forecast.risk_adjusted_cfr < 5.0


class TestSerialization:
    def test_forecast_to_dict(self, engine, elite_snapshots):
        forecast = engine.generate_forecast(elite_snapshots, project_id="test-svc", autonomy_level=4)
        d = forecast.to_dict()
        assert "project_id" in d
        assert "current_level" in d
        assert "projected_level_7d" in d
        assert "health_pulse" in d
        assert "metrics" in d
        assert d["metrics"]["lead_time"] is not None

    def test_portal_summary(self, engine, elite_snapshots):
        forecast = engine.generate_forecast(elite_snapshots, project_id="x")
        summary = forecast.to_portal_summary()
        assert "DORA:" in summary
        assert "Elite" in summary

    def test_metric_trend_to_dict(self, engine, elite_snapshots):
        forecast = engine.generate_forecast(elite_snapshots, project_id="x")
        lt_dict = forecast.lead_time.to_dict()
        assert "metric_name" in lt_dict
        assert "current_value" in lt_dict
        assert "projected_7d" in lt_dict
        assert "trend_direction" in lt_dict
        assert "confidence" in lt_dict
