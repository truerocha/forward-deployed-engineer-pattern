"""
Tests for the Risk Inference Engine — PEC Blueprint Chapter 1.

Validates:
  1. Signal extraction produces normalized [0, 1] values
  2. Weighted sum + sigmoid produces valid risk scores
  3. Threshold classification works correctly
  4. Explanation generation identifies top contributors
  5. Weight update (Recursive Optimizer) adjusts correctly
  6. Feature flag disables the engine gracefully
  7. Edge cases (empty data, missing fields) are handled
"""

import math
import pytest

from src.core.risk.inference_engine import (
    RiskInferenceEngine,
    RiskAssessment,
    RiskExplanation,
)
from src.core.risk.risk_signals import RiskSignalExtractor, RiskSignals
from src.core.risk.risk_config import RiskConfig, RiskThresholds, SignalWeights


# ─── Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def default_engine():
    """Engine with default configuration."""
    return RiskInferenceEngine()


@pytest.fixture
def strict_engine():
    """Engine with strict thresholds for testing escalation/block."""
    config = RiskConfig(
        thresholds=RiskThresholds(tau_warn=0.05, tau_escalate=0.10, tau_block=0.30),
    )
    return RiskInferenceEngine(config=config)


@pytest.fixture
def disabled_engine():
    """Engine with feature flag disabled."""
    config = RiskConfig(enabled=False)
    return RiskInferenceEngine(config=config)


@pytest.fixture
def low_risk_contract():
    """Data contract for a simple, low-risk task."""
    return {
        "repo": "simple-service",
        "type": "bugfix",
        "estimated_files": 2,
        "organism_level": "O1",
        "affected_modules": ["utils"],
        "target_files": ["src/utils/helper.py"],
    }


@pytest.fixture
def high_risk_contract():
    """Data contract for a complex, high-risk task."""
    return {
        "repo": "payment-service",
        "type": "feature",
        "estimated_files": 12,
        "organism_level": "O4",
        "affected_modules": ["auth", "payments", "notifications"],
        "target_files": ["src/auth/jwt.py", "src/payments/processor.py"],
    }


@pytest.fixture
def healthy_dora_metrics():
    """DORA metrics from a healthy project."""
    return {
        "change_failure_rate": {"failure_rate_pct": 3.0},
        "dora_metrics": {
            "lead_time_avg_ms": 1800000,  # 30 min
            "deployment_frequency": {"deploys_per_day": 2.5},
        },
        "historical_lead_time_avg_ms": 2000000,
    }


@pytest.fixture
def unhealthy_dora_metrics():
    """DORA metrics from a struggling project."""
    return {
        "change_failure_rate": {"failure_rate_pct": 18.0},
        "dora_metrics": {
            "lead_time_avg_ms": 7200000,  # 2 hours
            "deployment_frequency": {"deploys_per_day": 0.1},
        },
        "historical_lead_time_avg_ms": 3600000,  # was 1 hour
    }


@pytest.fixture
def failure_history():
    """Recent failure history for a repo."""
    return [
        {"code": "FM-06", "task_type": "feature", "repo": "payment-service", "files_involved": ["src/auth/jwt.py"]},
        {"code": "FM-05", "task_type": "feature", "repo": "payment-service", "files_involved": ["src/payments/processor.py"]},
        {"code": "FM-06", "task_type": "bugfix", "repo": "other-service", "files_involved": []},
    ]


@pytest.fixture
def good_catalog():
    """Catalog metadata for a well-understood repo."""
    return {
        "confidence": 0.92,
        "complexity_avg": 8,
        "max_dependency_depth": 3,
        "test_coverage_pct": 85,
    }


@pytest.fixture
def poor_catalog():
    """Catalog metadata for a poorly-understood repo."""
    return {
        "confidence": 0.3,
        "complexity_avg": 18,
        "max_dependency_depth": 6,
        "test_coverage_pct": 20,
    }


# ─── Signal Extraction Tests ───────────────────────────────────


class TestRiskSignalExtractor:
    """Tests for the Contextual Encoder (signal extraction)."""

    def test_all_signals_normalized_0_to_1(self, low_risk_contract, healthy_dora_metrics, good_catalog):
        extractor = RiskSignalExtractor()
        signals = extractor.extract(
            data_contract=low_risk_contract,
            dora_metrics=healthy_dora_metrics,
            catalog_metadata=good_catalog,
        )
        for name, value in signals.to_dict().items():
            assert 0.0 <= value <= 1.0, f"Signal {name}={value} out of [0,1] range"

    def test_empty_inputs_produce_zero_signals(self):
        extractor = RiskSignalExtractor()
        signals = extractor.extract(data_contract={})
        # Most signals should be 0 or near-0 with empty input
        vector = signals.to_vector()
        assert all(0.0 <= v <= 1.0 for v in vector)

    def test_high_cfr_produces_high_signal(self, low_risk_contract, unhealthy_dora_metrics):
        extractor = RiskSignalExtractor()
        signals = extractor.extract(
            data_contract=low_risk_contract,
            dora_metrics=unhealthy_dora_metrics,
        )
        assert signals.historical_cfr >= 0.8  # 18% CFR / 20% max = 0.9

    def test_organism_level_mapping(self):
        extractor = RiskSignalExtractor()
        for level, expected in [("O1", 0.0), ("O2", 0.25), ("O3", 0.5), ("O4", 0.75), ("O5", 1.0)]:
            signals = extractor.extract(data_contract={"organism_level": level})
            assert signals.organism_level == expected, f"O-level {level} should map to {expected}"

    def test_file_count_normalization(self):
        extractor = RiskSignalExtractor()
        # 1 file = 0.0
        signals = extractor.extract(data_contract={"estimated_files": 1})
        assert signals.file_count == 0.0
        # 15 files = ~1.0
        signals = extractor.extract(data_contract={"estimated_files": 15})
        assert signals.file_count == 1.0

    def test_protective_signals_from_good_catalog(self, low_risk_contract, good_catalog):
        extractor = RiskSignalExtractor()
        signals = extractor.extract(
            data_contract=low_risk_contract,
            catalog_metadata=good_catalog,
        )
        assert signals.test_coverage >= 0.8
        assert signals.catalog_confidence >= 0.9

    def test_failure_recurrence_counts_matching_tasks(self, high_risk_contract, failure_history):
        extractor = RiskSignalExtractor()
        signals = extractor.extract(
            data_contract=high_risk_contract,
            failure_history=failure_history,
        )
        # 2 failures match payment-service repo
        assert signals.failure_recurrence >= 0.6

    def test_hotspot_detection(self, high_risk_contract, failure_history):
        extractor = RiskSignalExtractor()
        signals = extractor.extract(
            data_contract=high_risk_contract,
            failure_history=failure_history,
        )
        # src/auth/jwt.py is in failure history
        assert signals.repo_hotspot > 0.0


# ─── Inference Engine Tests ─────────────────────────────────────


class TestRiskInferenceEngine:
    """Tests for the core risk scoring engine."""

    def test_low_risk_task_passes(self, default_engine, low_risk_contract, healthy_dora_metrics, good_catalog):
        assessment = default_engine.assess(
            data_contract=low_risk_contract,
            task_id="TASK-001",
            dora_metrics=healthy_dora_metrics,
            catalog_metadata=good_catalog,
        )
        assert assessment.risk_score < 0.15
        assert assessment.classification == "pass"
        assert not assessment.should_block
        assert not assessment.should_escalate

    def test_high_risk_task_escalates_or_blocks(
        self, default_engine, high_risk_contract, unhealthy_dora_metrics, failure_history, poor_catalog,
    ):
        assessment = default_engine.assess(
            data_contract=high_risk_contract,
            task_id="TASK-002",
            dora_metrics=unhealthy_dora_metrics,
            failure_history=failure_history,
            catalog_metadata=poor_catalog,
        )
        assert assessment.risk_score > 0.15
        assert assessment.classification in ("escalate", "block")
        assert assessment.should_escalate

    def test_risk_score_always_between_0_and_1(self, default_engine):
        # Even with extreme inputs, sigmoid keeps score in [0, 1]
        extreme_contract = {
            "repo": "x", "type": "feature",
            "estimated_files": 100,
            "organism_level": "O5",
            "affected_modules": ["a", "b", "c", "d", "e"],
        }
        assessment = default_engine.assess(data_contract=extreme_contract, task_id="TASK-X")
        assert 0.0 <= assessment.risk_score <= 1.0

    def test_disabled_engine_always_passes(self, disabled_engine, high_risk_contract):
        assessment = disabled_engine.assess(
            data_contract=high_risk_contract,
            task_id="TASK-003",
        )
        assert assessment.risk_score == 0.0
        assert assessment.classification == "pass"
        assert not assessment.should_block

    def test_assessment_has_task_id(self, default_engine, low_risk_contract):
        assessment = default_engine.assess(
            data_contract=low_risk_contract,
            task_id="MY-TASK-42",
        )
        assert assessment.task_id == "MY-TASK-42"

    def test_assessment_has_timestamp(self, default_engine, low_risk_contract):
        assessment = default_engine.assess(
            data_contract=low_risk_contract,
            task_id="TASK-T",
        )
        assert assessment.assessed_at != ""
        # Should be ISO format
        assert "T" in assessment.assessed_at


# ─── Threshold Classification Tests ────────────────────────────


class TestRiskThresholds:
    """Tests for threshold-based classification."""

    def test_pass_classification(self):
        thresholds = RiskThresholds()
        assert thresholds.classify(0.0) == "pass"
        assert thresholds.classify(0.07) == "pass"

    def test_warn_classification(self):
        thresholds = RiskThresholds()
        assert thresholds.classify(0.08) == "warn"
        assert thresholds.classify(0.14) == "warn"

    def test_escalate_classification(self):
        thresholds = RiskThresholds()
        assert thresholds.classify(0.15) == "escalate"
        assert thresholds.classify(0.39) == "escalate"

    def test_block_classification(self):
        thresholds = RiskThresholds()
        assert thresholds.classify(0.40) == "block"
        assert thresholds.classify(0.99) == "block"

    def test_custom_thresholds(self):
        strict = RiskThresholds(tau_warn=0.01, tau_escalate=0.05, tau_block=0.10)
        assert strict.classify(0.005) == "pass"
        assert strict.classify(0.03) == "warn"
        assert strict.classify(0.07) == "escalate"
        assert strict.classify(0.15) == "block"


# ─── Explanation Tests ──────────────────────────────────────────


class TestRiskExplanation:
    """Tests for the XAI Gateway (explanation generation)."""

    def test_explanation_has_contributions(
        self, default_engine, high_risk_contract, unhealthy_dora_metrics, failure_history,
    ):
        assessment = default_engine.assess(
            data_contract=high_risk_contract,
            task_id="TASK-E",
            dora_metrics=unhealthy_dora_metrics,
            failure_history=failure_history,
        )
        assert len(assessment.explanation.contributions) == 13  # All 13 signals

    def test_contributions_sorted_by_impact(
        self, default_engine, high_risk_contract, unhealthy_dora_metrics,
    ):
        assessment = default_engine.assess(
            data_contract=high_risk_contract,
            task_id="TASK-S",
            dora_metrics=unhealthy_dora_metrics,
        )
        contributions = assessment.explanation.contributions
        # Should be sorted by absolute contribution (descending)
        abs_values = [abs(c["contribution"]) for c in contributions]
        assert abs_values == sorted(abs_values, reverse=True)

    def test_blocked_assessment_has_prescription(
        self, strict_engine, high_risk_contract, unhealthy_dora_metrics, failure_history, poor_catalog,
    ):
        assessment = strict_engine.assess(
            data_contract=high_risk_contract,
            task_id="TASK-B",
            dora_metrics=unhealthy_dora_metrics,
            failure_history=failure_history,
            catalog_metadata=poor_catalog,
        )
        if assessment.classification == "block":
            assert "BLOCKED" in assessment.explanation.prescription
            assert "Staff Engineer" in assessment.explanation.prescription

    def test_pass_assessment_has_no_prescription(
        self, default_engine, low_risk_contract, healthy_dora_metrics, good_catalog,
    ):
        assessment = default_engine.assess(
            data_contract=low_risk_contract,
            task_id="TASK-P",
            dora_metrics=healthy_dora_metrics,
            catalog_metadata=good_catalog,
        )
        assert assessment.explanation.prescription == ""


# ─── Recursive Optimizer Tests ──────────────────────────────────


class TestRecursiveOptimizer:
    """Tests for weight adjustment (Gradient Descent)."""

    def test_false_negative_increases_weights(self, default_engine, low_risk_contract, healthy_dora_metrics):
        """If we predicted low risk but task failed, weights should increase."""
        assessment = default_engine.assess(
            data_contract=low_risk_contract,
            task_id="TASK-FN",
            dora_metrics=healthy_dora_metrics,
        )
        original_weights = default_engine._config.weights.to_dict().copy()

        # Task actually failed
        default_engine.update_weights_from_outcome(assessment, "failed")

        updated_weights = default_engine._config.weights.to_dict()
        # At least some weights should have changed
        changes = sum(
            1 for k in original_weights
            if abs(original_weights[k] - updated_weights[k]) > 0.0001
        )
        assert changes > 0, "Weights should adjust after false negative"

    def test_accurate_prediction_no_change(self, default_engine, high_risk_contract, unhealthy_dora_metrics, failure_history, poor_catalog):
        """If prediction matches outcome, weights should not change significantly."""
        assessment = default_engine.assess(
            data_contract=high_risk_contract,
            task_id="TASK-AC",
            dora_metrics=unhealthy_dora_metrics,
            failure_history=failure_history,
            catalog_metadata=poor_catalog,
        )

        # If risk was high and task actually failed — prediction was correct
        if assessment.risk_score > 0.9:
            original_weights = default_engine._config.weights.to_dict().copy()
            default_engine.update_weights_from_outcome(assessment, "failed")
            updated_weights = default_engine._config.weights.to_dict()
            # Changes should be minimal
            max_change = max(
                abs(original_weights[k] - updated_weights[k])
                for k in original_weights
            )
            assert max_change < 0.1, "Accurate predictions should not change weights much"

    def test_weights_clamped_to_max_magnitude(self):
        """Weights should never exceed max_weight_magnitude."""
        config = RiskConfig()
        config.weights.w_historical_cfr = 4.9  # Near max
        config.learning_rate = 1.0  # Aggressive learning
        engine = RiskInferenceEngine(config=config)

        assessment = engine.assess(
            data_contract={"repo": "x", "type": "feature", "organism_level": "O5"},
            task_id="TASK-CL",
            dora_metrics={"change_failure_rate": {"failure_rate_pct": 20.0}},
        )
        engine.update_weights_from_outcome(assessment, "failed")

        # Weight should be clamped
        assert abs(engine._config.weights.w_historical_cfr) <= config.max_weight_magnitude


# ─── Serialization Tests ────────────────────────────────────────


class TestSerialization:
    """Tests for to_dict and event summary methods."""

    def test_assessment_to_dict(self, default_engine, low_risk_contract):
        assessment = default_engine.assess(data_contract=low_risk_contract, task_id="TASK-D")
        d = assessment.to_dict()
        assert "risk_score" in d
        assert "classification" in d
        assert "explanation" in d
        assert "signals" in d
        assert isinstance(d["risk_score"], float)

    def test_assessment_event_summary(self, default_engine, low_risk_contract):
        assessment = default_engine.assess(data_contract=low_risk_contract, task_id="TASK-ES")
        summary = assessment.to_event_summary()
        assert "Risk=" in summary
        assert assessment.classification in summary

    def test_config_to_dict(self):
        config = RiskConfig()
        d = config.to_dict()
        assert "enabled" in d
        assert "thresholds" in d
        assert "weights" in d
        assert "operational" in d

    def test_signals_to_vector_length(self):
        signals = RiskSignals()
        vector = signals.to_vector()
        assert len(vector) == 13  # 13 signals total


# ─── Integration Scenario Tests ─────────────────────────────────


class TestIntegrationScenarios:
    """End-to-end scenarios matching PEC Blueprint use cases."""

    def test_scenario_simple_bugfix_passes(self, default_engine, good_catalog):
        """PEC Blueprint: Simple bugfix in well-tested repo should pass."""
        assessment = default_engine.assess(
            data_contract={
                "repo": "stable-service",
                "type": "bugfix",
                "estimated_files": 1,
                "organism_level": "O1",
                "affected_modules": ["utils"],
            },
            task_id="BUGFIX-001",
            dora_metrics={
                "change_failure_rate": {"failure_rate_pct": 2.0},
                "dora_metrics": {
                    "lead_time_avg_ms": 900000,
                    "deployment_frequency": {"deploys_per_day": 3.0},
                },
                "historical_lead_time_avg_ms": 1000000,
            },
            catalog_metadata=good_catalog,
        )
        assert assessment.classification == "pass"

    def test_scenario_novel_cross_module_feature_escalates(self, default_engine, poor_catalog):
        """PEC Blueprint: Novel feature spanning modules with poor coverage should escalate."""
        assessment = default_engine.assess(
            data_contract={
                "repo": "legacy-monolith",
                "type": "feature",
                "estimated_files": 10,
                "organism_level": "O4",
                "affected_modules": ["auth", "billing", "notifications"],
            },
            task_id="FEAT-042",
            dora_metrics={
                "change_failure_rate": {"failure_rate_pct": 12.0},
                "dora_metrics": {
                    "lead_time_avg_ms": 5400000,
                    "deployment_frequency": {"deploys_per_day": 0.2},
                },
                "historical_lead_time_avg_ms": 3600000,
            },
            failure_history=[
                {"code": "FM-06", "task_type": "feature", "repo": "legacy-monolith", "files_involved": []},
                {"code": "FM-05", "task_type": "feature", "repo": "legacy-monolith", "files_involved": []},
            ],
            catalog_metadata=poor_catalog,
        )
        assert assessment.classification in ("escalate", "block")
        assert assessment.should_escalate

    def test_scenario_recurring_failure_blocks(self, strict_engine, poor_catalog):
        """PEC Blueprint: Recurring failures in same area should block."""
        assessment = strict_engine.assess(
            data_contract={
                "repo": "fragile-service",
                "type": "feature",
                "estimated_files": 8,
                "organism_level": "O4",
                "affected_modules": ["core", "api", "db"],
                "target_files": ["src/core/engine.py"],
            },
            task_id="FEAT-099",
            dora_metrics={
                "change_failure_rate": {"failure_rate_pct": 25.0},
                "dora_metrics": {
                    "lead_time_avg_ms": 10800000,
                    "deployment_frequency": {"deploys_per_day": 0.05},
                },
                "historical_lead_time_avg_ms": 3600000,
            },
            failure_history=[
                {"code": "FM-06", "task_type": "feature", "repo": "fragile-service", "files_involved": ["src/core/engine.py"]},
                {"code": "FM-05", "task_type": "feature", "repo": "fragile-service", "files_involved": ["src/core/engine.py"]},
                {"code": "FM-04", "task_type": "feature", "repo": "fragile-service", "files_involved": ["src/core/engine.py"]},
            ],
            catalog_metadata=poor_catalog,
        )
        assert assessment.classification == "block"
        assert assessment.should_block
        assert "BLOCKED" in assessment.explanation.prescription
