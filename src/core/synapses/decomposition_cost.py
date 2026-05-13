"""
Synapse 4: Modularization Cost Awareness (Homay 2025).

Evaluates whether decomposing a task into multiple agents is cost-justified
using the Fundamental Theorem of Software Engineering:

  C(P) > c(1/2 p) + c(1/2 p)

Decomposition is only beneficial if sub-problems can be addressed
independently. Otherwise, introducing interfaces between sub-problems
could increase overall cost ABOVE the original problem.

The evaluator:
  - Computes decomposition cost ratio before Conductor generates plans
  - Detects over-decomposition (too many agents for the task)
  - Detects under-decomposition (god agent handling all concerns)
  - Provides the decomposition_cost_ratio signal (#15) to the Risk Engine

Academic source: Homay, A. (2025). The Mythical Good Software.
                 arXiv:2507.09596.

Priority: P0 (LOW effort, HIGH impact — prevents over-engineering)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("fde.synapses.decomposition")


@dataclass
class DecompositionAssessment:
    """Result of decomposition cost evaluation."""

    cost_ratio: float
    recommended_agents: int
    proposed_agents: int
    recommendation: str
    reasoning: str
    shared_state_ratio: float = 0.0
    independence_score: float = 0.0
    cost_breakdown: dict[str, float] = field(default_factory=dict)

    @property
    def decomposition_cost_signal(self) -> float:
        """Normalized signal for Risk Engine integration.

        Returns value in [0, 1] where:
          0.0 = decomposition is clearly beneficial (low cost ratio)
          1.0 = decomposition is clearly harmful (high cost ratio)

        This becomes signal #15 in the extended risk vector.
        The weight is positive (+1.0): high cost ratio increases risk.
        """
        if self.cost_ratio <= 0.5:
            return 0.0
        elif self.cost_ratio >= 1.5:
            return 1.0
        return (self.cost_ratio - 0.5) / 1.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize for observability and Conductor injection."""
        return {
            "cost_ratio": round(self.cost_ratio, 4),
            "decomposition_cost_signal": round(self.decomposition_cost_signal, 4),
            "recommended_agents": self.recommended_agents,
            "proposed_agents": self.proposed_agents,
            "recommendation": self.recommendation,
            "reasoning": self.reasoning,
            "shared_state_ratio": round(self.shared_state_ratio, 4),
            "independence_score": round(self.independence_score, 4),
            "cost_breakdown": self.cost_breakdown,
        }


class DecompositionCostEvaluator:
    """Evaluates whether task decomposition is cost-justified.

    Implements the Fundamental Theorem from fde-design-swe-sinapses.md
    Section 6.3: decomposition is only beneficial if sub-problems are
    truly independent.

    Usage:
        evaluator = DecompositionCostEvaluator()
        assessment = evaluator.evaluate(
            organism_level="O3",
            proposed_agents=6,
            estimated_complexity_cost=0.15,
            shared_scd_fields=8,
            total_scd_fields=12,
        )
        if assessment.recommendation == "consolidate":
            # Use fewer agents
            ...
    """

    _AGENT_OVERHEAD_COST = 0.02
    _COMMUNICATION_COST_PER_EDGE = 0.005
    _CONTEXT_SWITCH_PENALTY = 0.01
    _CONSOLIDATION_THRESHOLD = 0.8
    _DECOMPOSITION_THRESHOLD = 0.3
    _MAX_SHARED_STATE_RATIO = 0.5

    _ORGANISM_MAX_AGENTS = {"O1": 2, "O2": 3, "O3": 5, "O4": 7, "O5": 8}

    def evaluate(
        self,
        organism_level: str,
        proposed_agents: int,
        estimated_complexity_cost: float = 0.10,
        shared_scd_fields: int = 0,
        total_scd_fields: int = 0,
        cross_module_edges: int = 0,
        task_independence_signals: list[bool] | None = None,
    ) -> DecompositionAssessment:
        """Evaluate whether the proposed decomposition is cost-justified."""
        edges = proposed_agents * (proposed_agents - 1) / 2
        decomposition_cost = (
            proposed_agents * self._AGENT_OVERHEAD_COST
            + edges * self._COMMUNICATION_COST_PER_EDGE
            + (proposed_agents - 1) * self._CONTEXT_SWITCH_PENALTY
        )

        monolithic_cost = max(0.01, estimated_complexity_cost)
        cost_ratio = decomposition_cost / monolithic_cost

        shared_state_ratio = 0.0
        if total_scd_fields > 0:
            shared_state_ratio = shared_scd_fields / total_scd_fields

        independence_score = self._compute_independence(
            proposed_agents, shared_scd_fields, cross_module_edges,
            task_independence_signals,
        )

        max_agents = self._ORGANISM_MAX_AGENTS.get(organism_level, 5)
        recommended = self._compute_recommended_agents(
            organism_level, proposed_agents, cost_ratio,
            shared_state_ratio, independence_score, max_agents,
        )

        recommendation, reasoning = self._generate_recommendation(
            cost_ratio, proposed_agents, recommended,
            shared_state_ratio, independence_score, organism_level,
        )

        cost_breakdown = {
            "agent_overhead": round(proposed_agents * self._AGENT_OVERHEAD_COST, 4),
            "communication": round(edges * self._COMMUNICATION_COST_PER_EDGE, 4),
            "context_switch": round((proposed_agents - 1) * self._CONTEXT_SWITCH_PENALTY, 4),
            "total_decomposition": round(decomposition_cost, 4),
            "monolithic_estimate": round(monolithic_cost, 4),
        }

        assessment = DecompositionAssessment(
            cost_ratio=cost_ratio,
            recommended_agents=recommended,
            proposed_agents=proposed_agents,
            recommendation=recommendation,
            reasoning=reasoning,
            shared_state_ratio=shared_state_ratio,
            independence_score=independence_score,
            cost_breakdown=cost_breakdown,
        )

        logger.info(
            "Decomposition cost: ratio=%.2f proposed=%d recommended=%d recommendation=%s",
            cost_ratio, proposed_agents, recommended, recommendation,
        )
        return assessment

    def _compute_independence(
        self, proposed_agents: int, shared_scd_fields: int,
        cross_module_edges: int, task_independence_signals: list[bool] | None,
    ) -> float:
        """Compute how independent the proposed sub-problems are."""
        if proposed_agents <= 1:
            return 1.0

        max_possible_shared = proposed_agents * 3
        state_independence = 1.0 - min(1.0, shared_scd_fields / max(max_possible_shared, 1))

        max_edges = proposed_agents * (proposed_agents - 1) / 2
        coupling_independence = 1.0 - min(1.0, cross_module_edges / max(max_edges, 1))

        signal_independence = 1.0
        if task_independence_signals:
            independent_count = sum(1 for s in task_independence_signals if s)
            signal_independence = independent_count / max(len(task_independence_signals), 1)

        return (
            state_independence * 0.4
            + coupling_independence * 0.3
            + signal_independence * 0.3
        )

    def _compute_recommended_agents(
        self, organism_level: str, proposed: int, cost_ratio: float,
        shared_state_ratio: float, independence_score: float, max_agents: int,
    ) -> int:
        """Compute the recommended number of agents."""
        recommended = min(proposed, max_agents)

        if cost_ratio > self._CONSOLIDATION_THRESHOLD:
            reduction = max(1, int(proposed * (cost_ratio - self._CONSOLIDATION_THRESHOLD)))
            recommended = max(2, proposed - reduction)

        if shared_state_ratio > self._MAX_SHARED_STATE_RATIO:
            recommended = max(2, int(proposed * (1.0 - shared_state_ratio)))

        if independence_score < 0.4:
            recommended = max(2, int(proposed * independence_score * 1.5))

        return max(2, min(recommended, proposed))

    def _generate_recommendation(
        self, cost_ratio: float, proposed: int, recommended: int,
        shared_state_ratio: float, independence_score: float, organism_level: str,
    ) -> tuple[str, str]:
        """Generate recommendation and reasoning."""
        if recommended < proposed:
            parts = []
            if cost_ratio > self._CONSOLIDATION_THRESHOLD:
                parts.append(f"cost_ratio={cost_ratio:.2f} exceeds {self._CONSOLIDATION_THRESHOLD}")
            if shared_state_ratio > self._MAX_SHARED_STATE_RATIO:
                parts.append(f"shared_state={shared_state_ratio:.2f} indicates entanglement")
            if independence_score < 0.4:
                parts.append(f"independence={independence_score:.2f} is low")
            reasoning = (
                f"CONSOLIDATE: Reduce from {proposed} to {recommended} agents. "
                + "; ".join(parts)
                + ". Fundamental Theorem: decomposition is only beneficial "
                "if sub-problems are truly independent."
            )
            return "consolidate", reasoning

        elif cost_ratio < self._DECOMPOSITION_THRESHOLD and independence_score > 0.7:
            reasoning = (
                f"DECOMPOSE: {proposed} agents is cost-justified. "
                f"cost_ratio={cost_ratio:.2f}, independence={independence_score:.2f}."
            )
            return "decompose", reasoning

        reasoning = (
            f"PROCEED: {proposed} agents is acceptable for {organism_level}. "
            f"cost_ratio={cost_ratio:.2f}, independence={independence_score:.2f}."
        )
        return "proceed", reasoning
