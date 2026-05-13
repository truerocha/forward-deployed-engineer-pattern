"""
Synapse 5: Epistemic Stance Awareness (King & Kimble 2004).

Decomposes catalog_confidence into sub-signals that capture what the
system actually knows about the problem domain.

Academic source: King, D. & Kimble, C. (2004). arXiv:cs/0406022.

Priority: P2 (HIGH effort, MEDIUM impact — long-term knowledge quality)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("fde.synapses.epistemic")


@dataclass
class EpistemicSignals:
    """Decomposed epistemic confidence signals."""

    structural_confidence: float = 0.5
    behavioral_confidence: float = 0.5
    domain_confidence: float = 0.5
    change_confidence: float = 0.5

    @property
    def composite(self) -> float:
        """Weighted composite epistemic confidence."""
        return (
            self.structural_confidence * 0.25
            + self.behavioral_confidence * 0.30
            + self.domain_confidence * 0.25
            + self.change_confidence * 0.20
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "structural_confidence": round(self.structural_confidence, 4),
            "behavioral_confidence": round(self.behavioral_confidence, 4),
            "domain_confidence": round(self.domain_confidence, 4),
            "change_confidence": round(self.change_confidence, 4),
            "composite": round(self.composite, 4),
        }


@dataclass
class EpistemicAssessment:
    """Result of epistemic stance assessment."""

    signals: EpistemicSignals
    artifact_type: str
    requires_domain_validation: bool = False
    assumptions_to_document: list[str] = field(default_factory=list)
    recommended_approach: str = ""
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "signals": self.signals.to_dict(),
            "artifact_type": self.artifact_type,
            "requires_domain_validation": self.requires_domain_validation,
            "assumptions_to_document": self.assumptions_to_document,
            "recommended_approach": self.recommended_approach,
            "reasoning": self.reasoning,
        }


class EpistemicStanceAssessor:
    """Assesses epistemic stance for a task and enforces hygiene rules.

    Usage:
        assessor = EpistemicStanceAssessor()
        assessment = assessor.assess(catalog_confidence=0.85, ...)
    """

    _KNOWLEDGE_ARTIFACT_PATTERNS = [
        "config/mappings/", "templates/", "_corpus.py", ".yaml", ".yml", "recommendation",
    ]

    def assess(
        self, catalog_confidence: float = 0.5,
        catalog_metadata: dict[str, Any] | None = None,
        data_contract: dict[str, Any] | None = None,
        target_files: list[str] | None = None,
    ) -> EpistemicAssessment:
        """Assess epistemic stance for a task."""
        catalog = catalog_metadata or {}
        contract = data_contract or {}
        files = target_files or contract.get("target_files", [])

        signals = self._decompose_confidence(catalog_confidence, catalog, contract)
        artifact_type = self._classify_artifact_type(files, contract)

        requires_domain_validation = (
            artifact_type == "knowledge"
            or (artifact_type == "mixed" and signals.domain_confidence < 0.6)
        )

        assumptions = self._identify_assumptions(signals, contract)
        recommended_approach = self._recommend_approach(signals, artifact_type)
        reasoning = self._generate_reasoning(signals, artifact_type, requires_domain_validation, recommended_approach)

        assessment = EpistemicAssessment(
            signals=signals, artifact_type=artifact_type,
            requires_domain_validation=requires_domain_validation,
            assumptions_to_document=assumptions,
            recommended_approach=recommended_approach, reasoning=reasoning,
        )

        logger.info(
            "Epistemic: composite=%.2f artifact=%s approach=%s",
            signals.composite, artifact_type, recommended_approach,
        )
        return assessment

    def _decompose_confidence(
        self, catalog_confidence: float, catalog: dict[str, Any], contract: dict[str, Any],
    ) -> EpistemicSignals:
        """Decompose aggregate confidence into sub-signals."""
        has_call_graph = catalog.get("has_call_graph", False)
        has_module_map = catalog.get("has_module_map", False)
        structural = min(1.0, catalog_confidence * 0.6 + (0.2 if has_call_graph else 0) + (0.2 if has_module_map else 0))

        test_coverage = catalog.get("test_coverage_pct", 0) / 100.0
        has_integration_tests = catalog.get("has_integration_tests", False)
        behavioral = min(1.0, test_coverage * 0.6 + (0.2 if has_integration_tests else 0) + catalog_confidence * 0.2)

        has_adrs = catalog.get("has_adrs", False)
        has_docs = catalog.get("has_documentation", False)
        domain = min(1.0, catalog_confidence * 0.4 + (0.3 if has_adrs else 0) + (0.3 if has_docs else 0))

        prior_success = contract.get("prior_success_rate", 0.5)
        change = prior_success * 0.5 + catalog_confidence * 0.5

        return EpistemicSignals(
            structural_confidence=round(structural, 4),
            behavioral_confidence=round(behavioral, 4),
            domain_confidence=round(domain, 4),
            change_confidence=round(change, 4),
        )

    def _classify_artifact_type(self, files: list[str], contract: dict[str, Any]) -> str:
        """Classify whether the task modifies code, knowledge, or both."""
        if not files:
            task_type = contract.get("type", "")
            if task_type in ("documentation", "config", "mapping"):
                return "knowledge"
            return "code"

        knowledge_files = sum(
            1 for f in files
            if any(pattern in f for pattern in self._KNOWLEDGE_ARTIFACT_PATTERNS)
        )
        code_files = len(files) - knowledge_files

        if knowledge_files > 0 and code_files == 0:
            return "knowledge"
        elif knowledge_files > 0:
            return "mixed"
        return "code"

    def _identify_assumptions(self, signals: EpistemicSignals, contract: dict[str, Any]) -> list[str]:
        """Identify assumptions that should be documented in the SCD."""
        assumptions: list[str] = []
        if signals.structural_confidence < 0.5:
            assumptions.append("Low structural confidence: code structure may not be fully understood")
        if signals.behavioral_confidence < 0.5:
            assumptions.append("Low behavioral confidence: runtime behavior may differ from expectations")
        if signals.domain_confidence < 0.5:
            assumptions.append("Low domain confidence: business rules may not be fully captured")
        if signals.change_confidence < 0.5:
            assumptions.append("Low change confidence: impact of modifications may be underestimated")

        affected_modules = contract.get("affected_modules", [])
        if len(affected_modules) > 2:
            assumptions.append(f"Cross-module change ({len(affected_modules)} modules): inter-module contracts may be affected")

        return assumptions

    def _recommend_approach(self, signals: EpistemicSignals, artifact_type: str) -> str:
        """Recommend execution approach based on epistemic stance."""
        composite = signals.composite
        if composite >= 0.8 and artifact_type == "code":
            return "rational"
        elif composite < 0.4 or artifact_type == "knowledge":
            return "exploratory"
        return "cautious"

    def _generate_reasoning(
        self, signals: EpistemicSignals, artifact_type: str,
        requires_domain_validation: bool, recommended_approach: str,
    ) -> str:
        parts = [
            f"Epistemic composite: {signals.composite:.2f}",
            f"Artifact type: {artifact_type}",
            f"Approach: {recommended_approach}",
        ]
        if requires_domain_validation:
            parts.append("Domain validation REQUIRED before modification")
        if signals.behavioral_confidence < 0.5:
            parts.append("WARNING: behavioral understanding is low")
        return ". ".join(parts)
