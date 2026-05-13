"""
Synapse 3: Dual-Paradigm Design Awareness (Ralph 2013).

Selects the appropriate design paradigm based on task characteristics:
  - Rational: Methodical, plan-centered — for well-understood tasks
  - Alternative: Improvisational, exploratory — for novel problems
  - Hybrid: Start rational, switch to alternative if stuck

The paradigm selection directly influences:
  - Conductor topology choice (sequential vs recursive)
  - Agent execution strategy (plan-first vs explore-first)
  - Risk Engine behavior (paradigm_fit_score signal)
  - Emulation Classifier (paradigm mismatch detection)

Academic source: Ralph, P. (2013). The Two Paradigms of Software Design.
                 arXiv:1303.5938.

Priority: P0 (LOW effort, HIGH impact — prevents wrong approach)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("fde.synapses.paradigm")


class DesignParadigm(Enum):
    """Design paradigm classification per Ralph (2013)."""

    RATIONAL = "rational"
    ALTERNATIVE = "alternative"
    HYBRID = "hybrid"


@dataclass
class ParadigmAssessment:
    """Result of paradigm selection for a task.

    Contains the selected paradigm, confidence in the selection,
    and the reasoning that led to the choice.
    """

    paradigm: DesignParadigm
    confidence: float  # [0, 1] — how confident we are in this selection
    reasoning: str
    task_signals: dict[str, Any] = field(default_factory=dict)
    conductor_guidance: str = ""

    @property
    def paradigm_fit_score(self) -> float:
        """Normalized score for Risk Engine integration.

        Returns value in [0, 1] where:
          1.0 = paradigm perfectly matches task characteristics
          0.0 = paradigm is mismatched (wrong approach for the problem)

        This becomes signal #16 in the extended risk vector.
        The weight is protective (-0.8): good paradigm fit reduces risk.
        """
        return self.confidence

    def to_dict(self) -> dict[str, Any]:
        """Serialize for observability and SCD injection."""
        return {
            "paradigm": self.paradigm.value,
            "confidence": round(self.confidence, 4),
            "paradigm_fit_score": round(self.paradigm_fit_score, 4),
            "reasoning": self.reasoning,
            "conductor_guidance": self.conductor_guidance,
            "task_signals": self.task_signals,
        }


class ParadigmSelector:
    """Selects the appropriate design paradigm for a task.

    Implements the decision logic from fde-design-swe-sinapses.md Section 5.3:
      - Rational: stable requirements + prior success + low complexity
      - Alternative: novel + no prior success + unstable requirements
      - Hybrid: default for most real tasks

    The selector also generates conductor guidance that influences
    how the Conductor structures its WorkflowPlan.

    Usage:
        selector = ParadigmSelector()
        assessment = selector.assess(
            organism_level="O4",
            prior_success_rate=0.2,
            requirement_stability=0.4,
            catalog_confidence=0.3,
        )
        # assessment.paradigm == DesignParadigm.ALTERNATIVE
        # assessment.conductor_guidance contains topology recommendations
    """

    # Thresholds calibrated from COE-052 and COE-019 post-mortems
    _RATIONAL_MIN_PRIOR_SUCCESS = 0.7
    _RATIONAL_MIN_REQ_STABILITY = 0.8
    _ALTERNATIVE_MAX_PRIOR_SUCCESS = 0.3
    _ALTERNATIVE_MIN_ORGANISM = "O4"
    _HYBRID_CONFIDENCE_BOOST = 0.1

    def assess(
        self,
        organism_level: str,
        prior_success_rate: float = 0.5,
        requirement_stability: float = 0.5,
        catalog_confidence: float = 0.5,
        domain_novelty: float = 0.5,
        failure_recurrence: float = 0.0,
    ) -> ParadigmAssessment:
        """Assess which design paradigm fits the task.

        Args:
            organism_level: Task complexity (O1-O5).
            prior_success_rate: Rate of success for similar tasks [0, 1].
            requirement_stability: How stable/clear requirements are [0, 1].
            catalog_confidence: Onboarding catalog confidence [0, 1].
            domain_novelty: How novel the problem domain is [0, 1].
            failure_recurrence: Rate of recurring failures [0, 1].

        Returns:
            ParadigmAssessment with selected paradigm and conductor guidance.
        """
        task_signals = {
            "organism_level": organism_level,
            "prior_success_rate": prior_success_rate,
            "requirement_stability": requirement_stability,
            "catalog_confidence": catalog_confidence,
            "domain_novelty": domain_novelty,
            "failure_recurrence": failure_recurrence,
        }

        # Compute paradigm scores
        rational_score = self._compute_rational_score(
            organism_level, prior_success_rate, requirement_stability,
            catalog_confidence, domain_novelty,
        )
        alternative_score = self._compute_alternative_score(
            organism_level, prior_success_rate, requirement_stability,
            catalog_confidence, domain_novelty, failure_recurrence,
        )

        # Select paradigm based on scores
        paradigm, confidence, reasoning = self._select(
            rational_score, alternative_score, task_signals,
        )

        # Generate conductor guidance
        conductor_guidance = self._generate_conductor_guidance(paradigm, organism_level)

        assessment = ParadigmAssessment(
            paradigm=paradigm,
            confidence=confidence,
            reasoning=reasoning,
            task_signals=task_signals,
            conductor_guidance=conductor_guidance,
        )

        logger.info(
            "Paradigm selected: %s (confidence=%.2f) for organism=%s prior_success=%.2f",
            paradigm.value, confidence, organism_level, prior_success_rate,
        )

        return assessment

    def compute_fit_score(
        self,
        selected_paradigm: DesignParadigm,
        execution_outcome: str,
        retry_count: int = 0,
    ) -> float:
        """Compute paradigm fit score post-execution for Emulation Classifier.

        Detects paradigm mismatches:
          - Rational on novel problem -> low fit (agent followed plan without understanding)
          - Alternative on routine problem -> low fit (agent explored unnecessarily)
          - Correct match -> high fit

        Args:
            selected_paradigm: The paradigm that was used.
            execution_outcome: "completed" | "failed" | "retried"
            retry_count: Number of retries needed.

        Returns:
            Fit score [0, 1] for the Fidelity Score design_quality dimension.
        """
        if execution_outcome == "completed" and retry_count == 0:
            return 1.0
        elif execution_outcome == "completed" and retry_count <= 1:
            return 0.8
        elif execution_outcome == "completed":
            # Multiple retries suggest paradigm mismatch
            return max(0.3, 1.0 - (retry_count * 0.2))
        elif execution_outcome == "failed":
            # Failure strongly suggests paradigm mismatch
            return 0.2
        return 0.5

    # --- Private Methods ---

    def _compute_rational_score(
        self,
        organism_level: str,
        prior_success: float,
        req_stability: float,
        catalog_confidence: float,
        domain_novelty: float,
    ) -> float:
        """Score how well the rational paradigm fits this task.

        Rational paradigm is appropriate when:
          - Problem is well-understood (low novelty)
          - Requirements are stable and clear
          - Similar tasks have succeeded before
          - Catalog confidence is high (we know the codebase)
        """
        organism_penalty = {"O1": 0.0, "O2": 0.0, "O3": 0.2, "O4": 0.4, "O5": 0.6}
        penalty = organism_penalty.get(organism_level, 0.3)

        score = (
            prior_success * 0.30
            + req_stability * 0.25
            + catalog_confidence * 0.20
            + (1.0 - domain_novelty) * 0.25
            - penalty
        )
        return max(0.0, min(1.0, score))

    def _compute_alternative_score(
        self,
        organism_level: str,
        prior_success: float,
        req_stability: float,
        catalog_confidence: float,
        domain_novelty: float,
        failure_recurrence: float,
    ) -> float:
        """Score how well the alternative paradigm fits this task.

        Alternative paradigm is appropriate when:
          - Problem is novel (high novelty)
          - Requirements are unstable/ambiguous
          - No prior success for similar tasks
          - Recurring failures suggest the rational approach is not working
        """
        organism_boost = {"O1": 0.0, "O2": 0.0, "O3": 0.1, "O4": 0.3, "O5": 0.5}
        boost = organism_boost.get(organism_level, 0.2)

        score = (
            domain_novelty * 0.25
            + (1.0 - prior_success) * 0.25
            + (1.0 - req_stability) * 0.20
            + failure_recurrence * 0.15
            + (1.0 - catalog_confidence) * 0.15
            + boost
        )
        return max(0.0, min(1.0, score))

    def _select(
        self,
        rational_score: float,
        alternative_score: float,
        task_signals: dict[str, Any],
    ) -> tuple[DesignParadigm, float, str]:
        """Select paradigm based on computed scores."""
        organism = task_signals["organism_level"]
        prior_success = task_signals["prior_success_rate"]
        req_stability = task_signals["requirement_stability"]

        # Strong rational signal
        if (
            organism in ("O1", "O2")
            and prior_success >= self._RATIONAL_MIN_PRIOR_SUCCESS
            and req_stability >= self._RATIONAL_MIN_REQ_STABILITY
        ):
            confidence = min(1.0, rational_score + 0.1)
            reasoning = (
                f"Rational paradigm: organism={organism} (routine), "
                f"prior_success={prior_success:.2f} (high), "
                f"req_stability={req_stability:.2f} (stable). "
                f"Plan-and-execute is appropriate."
            )
            return DesignParadigm.RATIONAL, confidence, reasoning

        # Strong alternative signal
        if (
            organism in ("O4", "O5")
            and prior_success < self._ALTERNATIVE_MAX_PRIOR_SUCCESS
        ):
            confidence = min(1.0, alternative_score + 0.1)
            reasoning = (
                f"Alternative paradigm: organism={organism} (novel), "
                f"prior_success={prior_success:.2f} (low), "
                f"domain requires exploration before commitment. "
                f"Explore-and-refine with recursive refinement."
            )
            return DesignParadigm.ALTERNATIVE, confidence, reasoning

        # Default: hybrid (most real tasks)
        score_gap = abs(rational_score - alternative_score)
        if score_gap < 0.15:
            confidence = 0.8 + self._HYBRID_CONFIDENCE_BOOST
        else:
            confidence = 0.6 + (0.2 * (1.0 - score_gap))

        reasoning = (
            f"Hybrid paradigm: rational_score={rational_score:.2f}, "
            f"alternative_score={alternative_score:.2f}. "
            f"Start with rational approach, switch to alternative if first attempt fails."
        )
        return DesignParadigm.HYBRID, min(1.0, confidence), reasoning

    def _generate_conductor_guidance(
        self,
        paradigm: DesignParadigm,
        organism_level: str,
    ) -> str:
        """Generate guidance for the Conductor's WorkflowPlan generation.

        This guidance is injected into the Conductor's system prompt to
        influence topology selection and step composition.
        """
        if paradigm == DesignParadigm.RATIONAL:
            return (
                "PARADIGM: RATIONAL. Use sequential topology. "
                "Generate a plan step followed by implementation steps. "
                "Each step should have clear inputs and outputs. "
                "Do not use recursive refinement unless explicitly needed."
            )
        elif paradigm == DesignParadigm.ALTERNATIVE:
            return (
                "PARADIGM: ALTERNATIVE. Use recursive or debate topology. "
                "Start with an exploration step that frames the problem. "
                "Allow multiple approaches to be evaluated. "
                "Enable recursive refinement (confidence threshold 0.6). "
                "For O4-O5: generate a design subtask BEFORE implementation."
            )
        else:  # HYBRID
            return (
                "PARADIGM: HYBRID. Use tree or sequential topology. "
                "Start with a rational plan-then-implement approach. "
                "If confidence drops below 0.7 after first execution, "
                "switch to recursive refinement with exploration. "
                "Balance speed (rational) with correctness (alternative)."
            )
