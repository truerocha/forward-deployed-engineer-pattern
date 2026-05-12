"""
Risk Inference Engine — Bayesian risk scoring for the FDE pipeline.

Implements the PEC Blueprint's "Risk Inference Engine" (Chapter 1):
  P(Failure | Context) = σ(Σ w_i · x_i)

The engine computes a risk score before agent execution begins,
using historical failure patterns, code complexity signals, and
DORA metrics trends as input signals.

Integration point: between Scope Check and Conductor in the orchestrator.

Modules:
  - inference_engine.py: Core Bayesian risk calculator
  - risk_signals.py: Signal extractors (complexity, history, DORA trend)
  - risk_config.py: Thresholds, priors, and weight configuration
"""

from .inference_engine import RiskInferenceEngine, RiskAssessment
from .risk_signals import RiskSignalExtractor, RiskSignals
from .risk_config import RiskConfig, RiskThresholds

__all__ = [
    "RiskInferenceEngine",
    "RiskAssessment",
    "RiskSignalExtractor",
    "RiskSignals",
    "RiskConfig",
    "RiskThresholds",
]
