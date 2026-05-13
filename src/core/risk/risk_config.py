"""
Risk Configuration — Thresholds, priors, and weight vectors.

This is a KNOWLEDGE ARTIFACT, not just code. Changes to thresholds
and weights require domain validation against historical failure data.

Source: PEC Blueprint Chapter 1 (Bayesian Inference)
  - τ = 0.15 (default risk threshold for gate escalation)
  - τ_block = 0.40 (hard block threshold — eject to Staff Engineer)
  - Priors derived from DORA Elite benchmarks

Domain Source of Truth:
  - Historical failure_modes.py classifications (FM-01 through FM-99)
  - DORA metrics from dora_metrics.py (change_failure_rate, lead_time)
  - Organism ladder complexity classifications (O1-O5)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

logger = logging.getLogger("fde.risk.config")


@dataclass(frozen=True)
class RiskThresholds:
    """Risk decision thresholds.

    tau_escalate: Risk above this triggers autonomy gate escalation.
                  Agent still proceeds but with tighter supervision.
    tau_block:    Risk above this blocks execution entirely.
                  Task is ejected to Staff Engineer for manual review.
    tau_warn:     Risk above this emits a warning to the portal.
                  No behavioral change, just visibility.

    These values are calibrated against DORA Elite benchmarks:
      - Elite teams have CFR < 5%, so tau_escalate = 0.15 gives 3x margin
      - tau_block = 0.40 means "more likely to fail than succeed"
    """

    tau_warn: float = 0.08
    tau_escalate: float = 0.15
    tau_block: float = 0.40

    def classify(self, risk_score: float) -> str:
        """Classify a risk score into an action category.

        Returns:
            "pass"     — risk is acceptable, proceed normally
            "warn"     — risk is elevated, emit warning
            "escalate" — risk is high, escalate autonomy gates
            "block"    — risk is critical, eject to human
        """
        if risk_score >= self.tau_block:
            return "block"
        if risk_score >= self.tau_escalate:
            return "escalate"
        if risk_score >= self.tau_warn:
            return "warn"
        return "pass"


@dataclass
class SignalWeights:
    """Weights for each risk signal in the inference equation.

    Risk Score = σ(Σ w_i · x_i) where:
      - x_i are normalized signal values [0, 1]
      - w_i are these weights (can be negative for protective signals)
      - σ is the sigmoid function

    Weights are initialized from domain knowledge and adjusted via
    the Recursive Optimizer (gradient descent on failure outcomes).

    Positive weights INCREASE risk. Negative weights DECREASE risk.
    """

    # Historical failure signals (from failure_modes.py data)
    w_historical_cfr: float = 2.5          # Change Failure Rate trend
    w_failure_recurrence: float = 3.0      # Same failure mode recurring
    w_repo_hotspot: float = 1.8            # Files in known failure hotspots

    # Complexity signals (from onboarding catalog / data contract)
    w_file_count: float = 1.2              # Number of files to modify
    w_cyclomatic_complexity: float = 1.5   # Average complexity of target files
    w_dependency_depth: float = 1.0        # Depth of dependency chain affected
    w_cross_module: float = 2.0            # Changes spanning multiple modules

    # DORA trend signals (from dora_metrics.py)
    w_lead_time_trend: float = 0.8         # Lead time increasing = higher risk
    w_deployment_frequency: float = -0.5   # High deploy freq = lower risk (team is healthy)

    # Organism complexity (from brain_sim/organism_ladder.py)
    w_organism_level: float = 1.5          # O5 novel = higher risk than O1 trivial

    # Protective signals (reduce risk)
    w_test_coverage: float = -1.5          # High test coverage = lower risk
    w_prior_success: float = -2.0          # Same task type succeeded before
    w_catalog_confidence: float = -1.0     # High onboarding catalog confidence

    # SWE Synapse signals (fde-design-swe-sinapses.md Section 8.2)
    w_interface_depth_ratio: float = -1.2  # Synapse 1: deep modules reduce risk (protective)
    w_decomposition_cost_ratio: float = 1.0  # Synapse 4: high cost ratio increases risk
    w_paradigm_fit_score: float = -0.8     # Synapse 3: good paradigm fit reduces risk (protective)

    # Synapse 6: Agent Thought Transparency (fde-design-swe-sinapses.md Section 8.5)
    w_reasoning_divergence: float = 1.5    # High divergence = hidden motivation risk

    # Synapse 7: Deterministic Harness (fde-design-swe-sinapses.md Section 9.5)
    w_coordination_overhead_ratio: float = 1.3  # High overhead = coordination saturation risk

    def to_dict(self) -> dict[str, float]:
        """Serialize weights for persistence and observability."""
        return {
            "w_historical_cfr": self.w_historical_cfr,
            "w_failure_recurrence": self.w_failure_recurrence,
            "w_repo_hotspot": self.w_repo_hotspot,
            "w_file_count": self.w_file_count,
            "w_cyclomatic_complexity": self.w_cyclomatic_complexity,
            "w_dependency_depth": self.w_dependency_depth,
            "w_cross_module": self.w_cross_module,
            "w_lead_time_trend": self.w_lead_time_trend,
            "w_deployment_frequency": self.w_deployment_frequency,
            "w_organism_level": self.w_organism_level,
            "w_test_coverage": self.w_test_coverage,
            "w_prior_success": self.w_prior_success,
            "w_catalog_confidence": self.w_catalog_confidence,
            "w_interface_depth_ratio": self.w_interface_depth_ratio,
            "w_decomposition_cost_ratio": self.w_decomposition_cost_ratio,
            "w_paradigm_fit_score": self.w_paradigm_fit_score,
            "w_reasoning_divergence": self.w_reasoning_divergence,
            "w_coordination_overhead_ratio": self.w_coordination_overhead_ratio,
        }

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> SignalWeights:
        """Deserialize weights from persistence."""
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


@dataclass
class RiskConfig:
    """Complete risk engine configuration.

    Combines thresholds, weights, and operational parameters.
    Feature-flagged via RISK_ENGINE_ENABLED environment variable.
    """

    thresholds: RiskThresholds = field(default_factory=RiskThresholds)
    weights: SignalWeights = field(default_factory=SignalWeights)

    # Operational parameters
    enabled: bool = field(default_factory=lambda: os.environ.get("RISK_ENGINE_ENABLED", "true").lower() == "true")
    max_history_window_days: int = 30
    min_samples_for_inference: int = 3
    fallback_risk_score: float = 0.05     # When insufficient data, assume low risk

    # Recursive Optimizer parameters (Chapter 1: Gradient Descent)
    learning_rate: float = 0.01           # How fast weights adjust after failures
    weight_decay: float = 0.001           # Regularization to prevent overfitting
    max_weight_magnitude: float = 5.0     # Clamp weights to prevent instability

    def to_dict(self) -> dict:
        """Serialize full config for observability."""
        return {
            "enabled": self.enabled,
            "thresholds": {
                "tau_warn": self.thresholds.tau_warn,
                "tau_escalate": self.thresholds.tau_escalate,
                "tau_block": self.thresholds.tau_block,
            },
            "weights": self.weights.to_dict(),
            "operational": {
                "max_history_window_days": self.max_history_window_days,
                "min_samples_for_inference": self.min_samples_for_inference,
                "fallback_risk_score": self.fallback_risk_score,
                "learning_rate": self.learning_rate,
            },
        }
