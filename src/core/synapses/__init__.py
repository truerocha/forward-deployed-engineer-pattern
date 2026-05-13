"""
SWE Synapses — Cognitive Design Principles for Agent Architecture.

Five cognitive dimensions extracted from peer-reviewed software engineering
theory that become operational signals in the CODE_FACTORY pipeline:

  Synapse 1 (Depth): Deep Module Principle (Ousterhout/APOSD)
  Synapse 2 (Harness): Agent Harness Architecture Bundles (Wei 2026)
  Synapse 3 (Paradigm): Dual-Paradigm Design Awareness (Ralph 2013)
  Synapse 4 (Cost): Modularization Cost Awareness (Homay 2025)
  Synapse 5 (Epistemic): Epistemic Stance Awareness (King & Kimble 2004)

Each synapse is:
  - Grounded in peer-reviewed software engineering theory
  - Measurable via the Risk Inference Engine (16 signals → sigmoid)
  - Actionable by the Conductor when composing WorkflowPlans
  - Observable via the Brain Simulation Ecosystem's Fidelity Score Engine

Ref: fde-design-swe-sinapses.md
Ref: ADR-020 (Conductor Orchestration Pattern)
Ref: ADR-022 (Risk Inference Engine)
"""

from src.core.synapses.paradigm_selector import (
    DesignParadigm,
    ParadigmSelector,
    ParadigmAssessment,
)
from src.core.synapses.decomposition_cost import (
    DecompositionCostEvaluator,
    DecompositionAssessment,
)
from src.core.synapses.interface_depth import (
    InterfaceDepthAnalyzer,
    DepthAssessment,
)
from src.core.synapses.bundle_coherence import (
    BundleCoherenceValidator,
    CoherenceAssessment,
)
from src.core.synapses.epistemic_stance import (
    EpistemicStanceAssessor,
    EpistemicAssessment,
    EpistemicSignals,
)
from src.core.synapses.synapse_engine import (
    SynapseEngine,
    SynapseAssessment,
)

__all__ = [
    "DesignParadigm",
    "ParadigmSelector",
    "ParadigmAssessment",
    "DecompositionCostEvaluator",
    "DecompositionAssessment",
    "InterfaceDepthAnalyzer",
    "DepthAssessment",
    "BundleCoherenceValidator",
    "CoherenceAssessment",
    "EpistemicStanceAssessor",
    "EpistemicAssessment",
    "EpistemicSignals",
    "SynapseEngine",
    "SynapseAssessment",
]
