"""
Risk Inference Engine — Bayesian risk scoring for the FDE pipeline.

Implements the PEC Blueprint's core equation:
  Risk Score = σ(Σ w_i · x_i)

Where:
  - σ is the sigmoid function (maps to [0, 1])
  - w_i are learned weights (from SignalWeights)
  - x_i are normalized signals (from RiskSignalExtractor)

The engine:
  1. Extracts signals from task context (Contextual Encoder)
  2. Computes weighted sum (Risk Inference)
  3. Applies sigmoid activation (Explanatory Gatekeeper)
  4. Classifies into action category (pass/warn/escalate/block)
  5. Provides SHAP-like explanations (XAI Gateway)

Source: PEC Blueprint Chapters 1-2
  "Utilizes Bayesian Inference to calculate P(Failure|Context).
   If the risk exceeds τ = 0.15, the system blocks the merge preventively."

Integration:
  - Called by orchestrator between scope_check and conductor
  - Emits risk metrics to DORACollector
  - Updates portal via task_queue events
  - Feeds into autonomy level resolution

Feature flag: RISK_ENGINE_ENABLED (default: true)
"""

from __future__ import annotations

import json
import logging
import math
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .risk_config import RiskConfig, RiskThresholds, SignalWeights
from .risk_signals import RiskSignalExtractor, RiskSignals

logger = logging.getLogger("fde.risk.inference_engine")


@dataclass
class RiskExplanation:
    """SHAP-like explanation of which signals contributed most to the risk score.

    Implements the PEC Blueprint's "Explanatory Gatekeeper":
      "If it fails the threshold, it provides a Safety Prescription."

    Each contribution shows:
      - signal_name: which signal
      - signal_value: the raw normalized value [0, 1]
      - weight: the weight applied
      - contribution: signal_value * weight (before sigmoid)
      - direction: "increases_risk" or "decreases_risk"
    """

    contributions: list[dict[str, Any]] = field(default_factory=list)
    top_risk_factors: list[str] = field(default_factory=list)
    top_protective_factors: list[str] = field(default_factory=list)
    prescription: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for portal display and event logging."""
        return {
            "contributions": self.contributions,
            "top_risk_factors": self.top_risk_factors,
            "top_protective_factors": self.top_protective_factors,
            "prescription": self.prescription,
        }

    def to_summary(self) -> str:
        """Human-readable summary for issue comments and portal."""
        parts = []
        if self.top_risk_factors:
            parts.append(f"Risk factors: {', '.join(self.top_risk_factors)}")
        if self.top_protective_factors:
            parts.append(f"Protective factors: {', '.join(self.top_protective_factors)}")
        if self.prescription:
            parts.append(f"Prescription: {self.prescription}")
        return " | ".join(parts) if parts else "No significant risk factors detected."


@dataclass
class RiskAssessment:
    """Complete risk assessment result.

    Contains the score, classification, explanation, and metadata
    needed for the orchestrator to make gate decisions.
    """

    risk_score: float                      # [0, 1] — probability of failure
    classification: str                    # "pass" | "warn" | "escalate" | "block"
    explanation: RiskExplanation           # SHAP-like breakdown
    signals: RiskSignals                   # Raw signal values used
    config_snapshot: dict = field(default_factory=dict)  # Config at assessment time
    assessed_at: str = ""
    task_id: str = ""

    def __post_init__(self):
        if not self.assessed_at:
            self.assessed_at = datetime.now(timezone.utc).isoformat()

    @property
    def should_block(self) -> bool:
        """Whether this assessment should block pipeline execution."""
        return self.classification == "block"

    @property
    def should_escalate(self) -> bool:
        """Whether this assessment should escalate autonomy gates."""
        return self.classification in ("escalate", "block")

    def to_dict(self) -> dict[str, Any]:
        """Full serialization for persistence and observability."""
        return {
            "risk_score": round(self.risk_score, 4),
            "classification": self.classification,
            "explanation": self.explanation.to_dict(),
            "signals": self.signals.to_dict(),
            "assessed_at": self.assessed_at,
            "task_id": self.task_id,
        }

    def to_event_summary(self) -> str:
        """Compact summary for task_queue event logging."""
        return (
            f"Risk={self.risk_score:.2f} ({self.classification}) — "
            f"{self.explanation.to_summary()}"
        )


class RiskInferenceEngine:
    """Core risk inference engine implementing the PEC Blueprint.

    Pipeline:
      1. Signal extraction (Contextual Encoder)
      2. Weighted summation (Risk Inference)
      3. Sigmoid activation (Gatekeeper)
      4. Classification (Action Decision)
      5. Explanation generation (XAI Gateway)

    Usage:
        engine = RiskInferenceEngine()
        assessment = engine.assess(
            data_contract={"repo": "my-service", "type": "feature"},
            dora_metrics=collector.compute_change_failure_rate(),
            failure_history=recent_failures,
            catalog_metadata=catalog_data,
        )

        if assessment.should_block:
            # Eject to Staff Engineer
            ...
        elif assessment.should_escalate:
            # Tighten autonomy gates
            ...
    """

    def __init__(self, config: RiskConfig | None = None):
        self._config = config or RiskConfig()
        self._extractor = RiskSignalExtractor(
            history_window_days=self._config.max_history_window_days,
        )

    @property
    def enabled(self) -> bool:
        """Whether the risk engine is active."""
        return self._config.enabled

    def assess(
        self,
        data_contract: dict[str, Any],
        task_id: str = "",
        dora_metrics: dict[str, Any] | None = None,
        failure_history: list[dict[str, Any]] | None = None,
        catalog_metadata: dict[str, Any] | None = None,
    ) -> RiskAssessment:
        """Perform a complete risk assessment for a task.

        This is the main entry point. It:
          1. Extracts signals from all available context
          2. Computes the risk score via weighted sigmoid
          3. Classifies the score against thresholds
          4. Generates an explanation with top contributors

        Args:
            data_contract: Canonical task data contract.
            task_id: Task identifier for correlation.
            dora_metrics: Recent DORA metrics (from DORACollector).
            failure_history: Recent failure classifications for this repo.
            catalog_metadata: Onboarding catalog data.

        Returns:
            RiskAssessment with score, classification, and explanation.
        """
        if not self._config.enabled:
            return self._disabled_assessment(task_id)

        # Step 1: Extract signals
        signals = self._extractor.extract(
            data_contract=data_contract,
            dora_metrics=dora_metrics,
            failure_history=failure_history,
            catalog_metadata=catalog_metadata,
        )

        # Step 2: Compute weighted sum
        weighted_sum = self._compute_weighted_sum(signals)

        # Step 3: Apply sigmoid activation
        risk_score = self._sigmoid(weighted_sum)

        # Step 4: Classify
        classification = self._config.thresholds.classify(risk_score)

        # Step 5: Generate explanation
        explanation = self._explain(signals, risk_score, classification)

        assessment = RiskAssessment(
            risk_score=risk_score,
            classification=classification,
            explanation=explanation,
            signals=signals,
            config_snapshot=self._config.to_dict(),
            task_id=task_id,
        )

        logger.info(
            "Risk assessment: task=%s score=%.4f classification=%s top_factors=%s",
            task_id, risk_score, classification,
            explanation.top_risk_factors[:3],
        )

        return assessment

    def update_weights_from_outcome(
        self,
        assessment: RiskAssessment,
        actual_outcome: str,
    ) -> SignalWeights:
        """Recursive Optimizer — adjust weights based on actual outcome.

        Implements PEC Blueprint Chapter 1 (Gradient Descent):
          "When a failure occurs, the Loss is calculated. The system uses
           Gradient Descent to adjust the Weights."

        If the engine predicted low risk but the task failed (false negative),
        weights for the contributing signals are increased.
        If the engine predicted high risk but the task succeeded (false positive),
        weights are decreased.

        Args:
            assessment: The original risk assessment.
            actual_outcome: "completed" | "failed" | "blocked"

        Returns:
            Updated SignalWeights (also persisted internally).
        """
        # Compute loss: difference between predicted and actual
        actual_failure = 1.0 if actual_outcome in ("failed", "blocked") else 0.0
        prediction_error = actual_failure - assessment.risk_score

        if abs(prediction_error) < 0.01:
            # Prediction was accurate — no adjustment needed
            return self._config.weights

        # Gradient descent: adjust each weight proportional to its signal contribution
        signals_vector = assessment.signals.to_vector()
        weights = self._config.weights
        lr = self._config.learning_rate
        decay = self._config.weight_decay
        max_mag = self._config.max_weight_magnitude

        weight_names = list(weights.to_dict().keys())
        current_weights = list(weights.to_dict().values())

        updated = {}
        for i, (name, w, x) in enumerate(zip(weight_names, current_weights, signals_vector)):
            # Gradient: error * signal_value (chain rule through sigmoid)
            gradient = prediction_error * x * assessment.risk_score * (1 - assessment.risk_score)
            # Update with learning rate and weight decay
            new_w = w + lr * gradient - decay * w
            # Clamp to prevent instability
            new_w = max(-max_mag, min(max_mag, new_w))
            updated[name] = new_w

        self._config.weights = SignalWeights.from_dict(updated)

        logger.info(
            "Weights updated: task=%s error=%.4f outcome=%s",
            assessment.task_id, prediction_error, actual_outcome,
        )

        return self._config.weights

    # ─── Internal Methods ───────────────────────────────────────

    def _compute_weighted_sum(self, signals: RiskSignals) -> float:
        """Compute Σ w_i · x_i (the logit before sigmoid)."""
        signal_vector = signals.to_vector()
        weight_vector = list(self._config.weights.to_dict().values())

        if len(signal_vector) != len(weight_vector):
            logger.error(
                "Signal/weight dimension mismatch: %d signals vs %d weights",
                len(signal_vector), len(weight_vector),
            )
            return 0.0

        return sum(w * x for w, x in zip(weight_vector, signal_vector))

    @staticmethod
    def _sigmoid(x: float) -> float:
        """Sigmoid activation function σ(x) = 1 / (1 + e^(-x)).

        Maps any real number to [0, 1].
        Clamped input to [-20, 20] to prevent overflow.
        """
        x = max(-20.0, min(20.0, x))
        return 1.0 / (1.0 + math.exp(-x))

    def _explain(
        self,
        signals: RiskSignals,
        risk_score: float,
        classification: str,
    ) -> RiskExplanation:
        """Generate SHAP-like explanation of the risk score.

        Computes each signal's contribution to the final score and
        identifies the top risk factors and protective factors.
        """
        signal_dict = signals.to_dict()
        weight_dict = self._config.weights.to_dict()

        # Map signal names to weight names
        signal_to_weight = {
            "historical_cfr": "w_historical_cfr",
            "failure_recurrence": "w_failure_recurrence",
            "repo_hotspot": "w_repo_hotspot",
            "file_count": "w_file_count",
            "cyclomatic_complexity": "w_cyclomatic_complexity",
            "dependency_depth": "w_dependency_depth",
            "cross_module": "w_cross_module",
            "lead_time_trend": "w_lead_time_trend",
            "deployment_frequency": "w_deployment_frequency",
            "organism_level": "w_organism_level",
            "test_coverage": "w_test_coverage",
            "prior_success": "w_prior_success",
            "catalog_confidence": "w_catalog_confidence",
            "interface_depth_ratio": "w_interface_depth_ratio",
            "decomposition_cost_ratio": "w_decomposition_cost_ratio",
            "paradigm_fit_score": "w_paradigm_fit_score",
            "reasoning_divergence": "w_reasoning_divergence",
            "coordination_overhead_ratio": "w_coordination_overhead_ratio",
        }

        contributions = []
        for signal_name, signal_value in signal_dict.items():
            weight_name = signal_to_weight.get(signal_name, "")
            weight = weight_dict.get(weight_name, 0.0)
            contribution = signal_value * weight

            contributions.append({
                "signal_name": signal_name,
                "signal_value": round(signal_value, 4),
                "weight": round(weight, 4),
                "contribution": round(contribution, 4),
                "direction": "decreases_risk" if contribution < 0 else "increases_risk",
            })

        # Sort by absolute contribution (most impactful first)
        contributions.sort(key=lambda c: abs(c["contribution"]), reverse=True)

        # Identify top factors
        top_risk = [
            c["signal_name"] for c in contributions
            if c["contribution"] > 0.1
        ][:3]

        top_protective = [
            c["signal_name"] for c in contributions
            if c["contribution"] < -0.1
        ][:3]

        # Generate prescription based on classification
        prescription = self._generate_prescription(classification, top_risk, risk_score)

        return RiskExplanation(
            contributions=contributions,
            top_risk_factors=top_risk,
            top_protective_factors=top_protective,
            prescription=prescription,
        )

    def _generate_prescription(
        self,
        classification: str,
        top_risk_factors: list[str],
        risk_score: float,
    ) -> str:
        """Generate a Safety Prescription based on the risk assessment.

        Implements the PEC Blueprint's XAI Gateway:
          "Access Denied. Risk is 0.82. Reason: High coupling in Auth Module.
           Action: Refactor lines 40-60 into a separate utility."
        """
        if classification == "pass":
            return ""

        factor_descriptions = {
            "historical_cfr": "high change failure rate in this project",
            "failure_recurrence": "recurring failure pattern for this task type",
            "repo_hotspot": "target files are in known failure hotspots",
            "file_count": "large number of files affected",
            "cyclomatic_complexity": "high code complexity in target area",
            "dependency_depth": "deep dependency chain at risk",
            "cross_module": "changes span multiple modules",
            "lead_time_trend": "lead time is trending upward",
            "organism_level": "high task complexity (novel problem)",
        }

        reasons = [
            factor_descriptions.get(f, f)
            for f in top_risk_factors[:2]
        ]
        reason_text = " and ".join(reasons) if reasons else "elevated risk signals"

        if classification == "block":
            return (
                f"BLOCKED (risk={risk_score:.2f}). Reason: {reason_text}. "
                f"Action: Staff Engineer review required before execution. "
                f"Consider decomposing into smaller tasks or adding test coverage."
            )
        elif classification == "escalate":
            return (
                f"ESCALATED (risk={risk_score:.2f}). Reason: {reason_text}. "
                f"Action: Autonomy gates tightened. Agent will proceed with "
                f"additional checkpoints and human validation at key milestones."
            )
        else:  # warn
            return (
                f"WARNING (risk={risk_score:.2f}). Reason: {reason_text}. "
                f"Action: Proceed with monitoring. Consider reviewing output carefully."
            )

    def _disabled_assessment(self, task_id: str) -> RiskAssessment:
        """Return a pass-through assessment when the engine is disabled."""
        return RiskAssessment(
            risk_score=0.0,
            classification="pass",
            explanation=RiskExplanation(prescription="Risk engine disabled"),
            signals=RiskSignals(),
            config_snapshot={"enabled": False},
            task_id=task_id,
        )
