"""
Synapse Engine — Integrated Pre-Execution Synapse Chain.

Orchestrates all five SWE Synapses in the correct firing order:
  1. Synapse 5 (Epistemic): What do we KNOW about this domain?
  2. Synapse 3 (Paradigm): Should we plan or explore?
  3. Synapse 4 (Cost): Should we decompose or keep monolithic?
  4. Synapse 2 (Harness): Which architectural bundle fits?
  5. Synapse 1 (Depth): Are agent responsibilities deep enough?

Ref: fde-design-swe-sinapses.md Section 8 (Integrated Architecture)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from src.core.synapses.bundle_coherence import BundleCoherenceValidator, CoherenceAssessment
from src.core.synapses.decomposition_cost import DecompositionCostEvaluator, DecompositionAssessment
from src.core.synapses.epistemic_stance import EpistemicStanceAssessor, EpistemicAssessment
from src.core.synapses.interface_depth import InterfaceDepthAnalyzer, DepthAssessment
from src.core.synapses.paradigm_selector import DesignParadigm, ParadigmSelector, ParadigmAssessment

logger = logging.getLogger("fde.synapses.engine")


@dataclass
class SynapseAssessment:
    """Complete synapse assessment combining all five dimensions."""

    epistemic: EpistemicAssessment
    paradigm: ParadigmAssessment
    decomposition: DecompositionAssessment
    coherence: CoherenceAssessment
    depth: DepthAssessment

    interface_depth_ratio: float = 0.0
    decomposition_cost_ratio: float = 0.0
    paradigm_fit_score: float = 0.0
    design_quality_score: float = 0.0
    conductor_guidance: str = ""
    recommended_topology: str = ""
    recommended_agents: int = 0

    def __post_init__(self) -> None:
        self.interface_depth_ratio = self.depth.depth_signal
        self.decomposition_cost_ratio = self.decomposition.decomposition_cost_signal
        self.paradigm_fit_score = self.paradigm.paradigm_fit_score
        self.conductor_guidance = self.paradigm.conductor_guidance
        self.recommended_agents = self.decomposition.recommended_agents
        self.design_quality_score = self._compute_design_quality()
        self.recommended_topology = self._derive_topology()

    def risk_signals(self) -> dict[str, float]:
        """Return the 3 new signals for Risk Engine integration."""
        return {
            "interface_depth_ratio": self.interface_depth_ratio,
            "decomposition_cost_ratio": self.decomposition_cost_ratio,
            "paradigm_fit_score": self.paradigm_fit_score,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "risk_signals": self.risk_signals(),
            "design_quality_score": round(self.design_quality_score, 4),
            "conductor_guidance": self.conductor_guidance,
            "recommended_topology": self.recommended_topology,
            "recommended_agents": self.recommended_agents,
            "epistemic": self.epistemic.to_dict(),
            "paradigm": self.paradigm.to_dict(),
            "decomposition": self.decomposition.to_dict(),
            "coherence": self.coherence.to_dict(),
            "depth": self.depth.to_dict(),
        }

    def _compute_design_quality(self) -> float:
        """Compute design quality score for Fidelity Score integration."""
        return (
            self.depth.interface_depth_ratio * 0.25
            + self.coherence.coherence_score * 0.20
            + self.paradigm.confidence * 0.25
            + (1.0 - self.decomposition.decomposition_cost_signal) * 0.15
            + self.epistemic.signals.composite * 0.15
        )

    def _derive_topology(self) -> str:
        if self.paradigm.paradigm == DesignParadigm.RATIONAL:
            return "sequential"
        elif self.paradigm.paradigm == DesignParadigm.ALTERNATIVE:
            return "recursive"
        return "tree"


class SynapseEngine:
    """Orchestrates the pre-execution synapse chain.

    Usage:
        engine = SynapseEngine()
        assessment = engine.assess(organism_level="O4", ...)
        risk_signals = assessment.risk_signals()
    """

    def __init__(self) -> None:
        self._paradigm_selector = ParadigmSelector()
        self._decomposition_evaluator = DecompositionCostEvaluator()
        self._depth_analyzer = InterfaceDepthAnalyzer()
        self._bundle_validator = BundleCoherenceValidator()
        self._epistemic_assessor = EpistemicStanceAssessor()

    def assess(
        self,
        organism_level: str,
        data_contract: dict[str, Any] | None = None,
        catalog_metadata: dict[str, Any] | None = None,
        proposed_agents: int = 3,
        proposed_topology: str = "sequential",
        proposed_steps: list[dict[str, Any]] | None = None,
        scd_access_map: dict[str, list[str]] | None = None,
        prior_success_rate: float = 0.5,
        failure_recurrence: float = 0.0,
        estimated_complexity_cost: float = 0.10,
    ) -> SynapseAssessment:
        """Run the complete pre-execution synapse chain."""
        contract = data_contract or {}
        catalog = catalog_metadata or {}
        steps = proposed_steps or []

        catalog_confidence = catalog.get("confidence", 0.5)

        # Synapse 5: Epistemic Stance
        epistemic = self._epistemic_assessor.assess(
            catalog_confidence=catalog_confidence,
            catalog_metadata=catalog,
            data_contract=contract,
        )

        # Synapse 3: Paradigm Selection
        requirement_stability = 0.5
        if epistemic.signals.domain_confidence > 0.7:
            requirement_stability = 0.8
        elif epistemic.signals.domain_confidence < 0.3:
            requirement_stability = 0.3

        domain_novelty = 1.0 - epistemic.signals.domain_confidence

        paradigm = self._paradigm_selector.assess(
            organism_level=organism_level,
            prior_success_rate=prior_success_rate,
            requirement_stability=requirement_stability,
            catalog_confidence=catalog_confidence,
            domain_novelty=domain_novelty,
            failure_recurrence=failure_recurrence,
        )

        # Synapse 4: Decomposition Cost
        shared_scd_fields = 0
        total_scd_fields = 0
        if scd_access_map:
            all_fields: set[str] = set()
            shared_fields: set[str] = set()
            for fields in scd_access_map.values():
                field_set = set(fields)
                shared_fields.update(all_fields & field_set)
                all_fields.update(field_set)
            shared_scd_fields = len(shared_fields)
            total_scd_fields = len(all_fields)

        cross_module_edges = max(0, len(contract.get("affected_modules", [])) - 1)

        decomposition = self._decomposition_evaluator.evaluate(
            organism_level=organism_level,
            proposed_agents=proposed_agents,
            estimated_complexity_cost=estimated_complexity_cost,
            shared_scd_fields=shared_scd_fields,
            total_scd_fields=total_scd_fields,
            cross_module_edges=cross_module_edges,
        )

        # Synapse 2: Bundle Coherence
        if steps:
            plan_metadata = self._bundle_validator.extract_plan_metadata(
                topology=proposed_topology, steps=steps,
                organism_level=organism_level,
                has_recursive=proposed_topology == "recursive",
            )
        else:
            plan_metadata = {
                "topology": proposed_topology,
                "agent_count": proposed_agents,
                "has_recursive": proposed_topology == "recursive",
                "context_persistence": "durable" if proposed_agents >= 3 else "ephemeral",
                "safety_approval": "policy_based",
                "tool_surface": "standard",
                "max_depth": 2,
                "has_arbiter": proposed_topology == "debate",
                "has_verification": organism_level in ("O4", "O5"),
            }

        coherence = self._bundle_validator.validate(plan_metadata, organism_level)

        # Synapse 1: Interface Depth
        if steps:
            depth = self._depth_analyzer.analyze_agent_plan(steps, scd_access_map)
        else:
            depth = self._depth_analyzer.analyze_catalog(catalog)

        # Compose Final Assessment
        assessment = SynapseAssessment(
            epistemic=epistemic, paradigm=paradigm,
            decomposition=decomposition, coherence=coherence, depth=depth,
        )

        logger.info(
            "Synapse chain: organism=%s paradigm=%s agents=%d->%d depth=%.2f quality=%.2f",
            organism_level, paradigm.paradigm.value,
            proposed_agents, assessment.recommended_agents,
            assessment.interface_depth_ratio, assessment.design_quality_score,
        )

        return assessment
