"""
A2A Squad Bridge — Connects A2A Protocol to Conductor Squad Composition.

This module bridges two execution paths in the FDE factory:
  1. Conductor Path (ADR-020): Composes squads dynamically based on task complexity
  2. A2A Path (ADR-034): Executes tasks via decoupled microservice agents

The bridge enables the Conductor to:
  - Discover A2A agents via their Agent Cards
  - Delegate specific workflow phases to the A2A pipeline
  - Receive structured results conforming to the squad's SCD (Shared Context Document)
  - Route tasks to A2A when the topology requires decoupled execution

Design Decisions:
  - The Conductor remains the authority on WHAT to do (squad composition)
  - The A2A orchestrator handles HOW to do it (agent coordination)
  - The bridge translates between Conductor's WorkflowPlan and A2A's ContextoWorkflow
  - SCD updates flow bidirectionally: Conductor → A2A (input) and A2A → SCD (output)

When to use A2A vs Conductor-direct:
  - A2A: Long-running research/writing tasks that benefit from feedback loops
  - Conductor-direct: Fast tasks (code context, planning) that run in-process

Ref: ADR-019 (Agentic Squad Architecture), ADR-020 (Conductor Orchestration),
     ADR-034 (A2A Protocol Integration)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

from src.core.a2a.agent_cards import (
    AGENT_CARD_REGISTRY,
    ESCRITA_CARD,
    PESQUISA_CARD,
    REVISAO_CARD,
    get_card,
    list_cards,
)
from src.core.a2a.contracts import (
    ConteudoBruto,
    ContextoWorkflow,
    FeedbackRevisao,
    RelatorioFinal,
)

logger = logging.getLogger(__name__)


# ─── Squad Role Mapping ──────────────────────────────────────────────────────
# Maps Conductor squad roles (ADR-019) to A2A agent capabilities.
# The Conductor uses role names; the A2A layer uses agent card names.

SQUAD_ROLE_TO_A2A_AGENT: dict[str, str] = {
    # Research/reconnaissance maps to Pesquisa agent
    "reconnaissance": "fde-research-agent",
    "researcher": "fde-research-agent",
    "swe-code-context-agent": "fde-research-agent",
    # Engineering/implementation maps to Escrita agent
    "engineering": "fde-engineering-agent",
    "implementer": "fde-engineering-agent",
    "swe-developer-agent": "fde-engineering-agent",
    "swe-architect-agent": "fde-engineering-agent",
    "swe-tech-writer-agent": "fde-engineering-agent",
    # Review/adversarial maps to Revisão agent
    "reviewer": "fde-review-agent",
    "adversarial": "fde-review-agent",
    "swe-adversarial-agent": "fde-review-agent",
    "fde-pr-reviewer-agent": "fde-review-agent",
}


class SquadBridge:
    """Bridge between Conductor squad composition and A2A execution.

    The Conductor produces a WorkflowPlan with stages and agent assignments.
    This bridge translates those assignments into A2A workflow executions,
    handling the mapping between squad roles and A2A agent capabilities.

    Usage (from Conductor):
        bridge = SquadBridge()

        # Check if a stage should use A2A
        if bridge.should_use_a2a(stage):
            result = await bridge.delegate_to_a2a(task_context)
        else:
            # Execute in-process via Conductor-direct
            ...
    """

    def __init__(self):
        """Initialize the squad bridge with A2A agent discovery."""
        self._available_agents = AGENT_CARD_REGISTRY
        logger.info(
            "SquadBridge initialized with %d A2A agents: %s",
            len(self._available_agents),
            list(self._available_agents.keys()),
        )

    def should_use_a2a(self, stage_config: dict[str, Any]) -> bool:
        """Determine if a workflow stage should be delegated to A2A.

        A2A is preferred for:
          - Long-running tasks (research, document generation)
          - Tasks requiring feedback loops (write → review → rework)
          - Tasks that benefit from independent scaling
          - Tasks with explicit A2A routing in the WorkflowPlan

        A2A is NOT used for:
          - Fast in-process tasks (code context lookup, planning)
          - Tasks requiring shared memory access (in-process state)
          - Tasks with sub-second latency requirements

        Args:
            stage_config: Stage configuration from the Conductor's WorkflowPlan.
                Expected keys: "agents", "topology", "phase", "a2a_eligible"

        Returns:
            True if the stage should be delegated to A2A execution.
        """
        # Explicit routing override
        if "a2a_eligible" in stage_config:
            return stage_config["a2a_eligible"]

        # Check if any assigned agent has an A2A counterpart
        agents = stage_config.get("agents", [])
        for agent_role in agents:
            if agent_role in SQUAD_ROLE_TO_A2A_AGENT:
                a2a_name = SQUAD_ROLE_TO_A2A_AGENT[agent_role]
                if a2a_name in self._available_agents:
                    return True

        # Topology-based heuristic: feedback loops benefit from A2A
        topology = stage_config.get("topology", "sequential")
        if topology in ("feedback_loop", "iterative", "debate"):
            return True

        # Phase-based heuristic: Phases 1-4 map naturally to A2A
        phase = stage_config.get("phase", "")
        if phase in ("research", "engineering", "review", "reporting"):
            return True

        return False

    def resolve_a2a_agent(self, squad_role: str) -> Optional[dict[str, Any]]:
        """Resolve a squad role to its A2A agent card.

        Args:
            squad_role: Role name from the Conductor's squad manifest.

        Returns:
            Agent card dict if an A2A agent handles this role, None otherwise.
        """
        a2a_name = SQUAD_ROLE_TO_A2A_AGENT.get(squad_role)
        if not a2a_name:
            return None
        return get_card(a2a_name)

    def translate_scd_to_a2a_context(
        self,
        scd: dict[str, Any],
        task_description: str,
    ) -> ContextoWorkflow:
        """Translate a Conductor SCD (Shared Context Document) to A2A ContextoWorkflow.

        The SCD is the Conductor's state format (DynamoDB: task_id + section_key).
        The ContextoWorkflow is the A2A orchestrator's state format.

        This translation enables seamless handoff between execution paths.

        Args:
            scd: Shared Context Document from the Conductor.
                Expected sections: "spec", "constraints", "context", "research"
            task_description: Human-readable task description.

        Returns:
            ContextoWorkflow ready for A2A orchestrator execution.
        """
        workflow_id = f"wf-{scd.get('task_id', 'unknown')}"

        contexto = ContextoWorkflow(
            workflow_id=workflow_id,
            input_usuario=task_description,
        )

        # If the Conductor already has research data, inject it
        research_section = scd.get("research", {})
        if research_section and research_section.get("fatos_encontrados"):
            try:
                contexto.dados_pesquisa = ConteudoBruto.model_validate(research_section)
                contexto.no_atual = "ESCRITA"  # Skip research — already done
                logger.info(
                    "[%s] SCD contains research data — starting at ESCRITA",
                    workflow_id,
                )
            except Exception as e:
                logger.warning(
                    "[%s] SCD research data invalid, starting from PESQUISA: %s",
                    workflow_id, str(e)[:100],
                )

        # Inject constraints from SCD into the context
        constraints = scd.get("constraints", {})
        if constraints:
            contexto.metricas_execucao["scd_constraints"] = constraints

        return contexto

    def translate_a2a_result_to_scd(
        self,
        result: dict[str, Any],
        task_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Translate A2A execution result back to SCD sections for the Conductor.

        After A2A execution completes, the result must be written back to the
        SCD so downstream Conductor stages can consume it.

        Args:
            result: Execution result from SquadOrchestrator.executar().
            task_id: The Conductor's task ID (DynamoDB PK).

        Returns:
            Dict of SCD section updates keyed by section_key.
            Ready for batch DynamoDB PutItem operations.
        """
        sections: dict[str, dict[str, Any]] = {}

        # Write the final report as the "deliverable" section
        relatorio = result.get("relatorio")
        if relatorio:
            sections["deliverable"] = {
                "task_id": task_id,
                "section_key": "deliverable",
                "data": relatorio,
                "source": "a2a-pipeline",
                "workflow_id": result.get("workflow_id", ""),
            }

        # Write execution metrics as the "a2a_metrics" section
        metricas = result.get("metricas", {})
        if metricas:
            sections["a2a_metrics"] = {
                "task_id": task_id,
                "section_key": "a2a_metrics",
                "data": metricas,
                "status": result.get("status", "unknown"),
                "tentativas": result.get("tentativas_revisao", 0),
            }

        # Write errors (if any) as the "a2a_errors" section
        erros = result.get("erros", [])
        if erros:
            sections["a2a_errors"] = {
                "task_id": task_id,
                "section_key": "a2a_errors",
                "data": {"errors": erros},
                "workflow_id": result.get("workflow_id", ""),
            }

        return sections

    def estimate_cost(self, stage_config: dict[str, Any]) -> float:
        """Estimate the token cost of running a stage via A2A.

        Uses the cost_weight from agent cards to provide a rough estimate.
        The Conductor uses this for budget-aware squad composition.

        Args:
            stage_config: Stage configuration with agent assignments.

        Returns:
            Estimated cost weight (relative units, not dollars).
        """
        total_weight = 0.0
        agents = stage_config.get("agents", [])

        for agent_role in agents:
            card = self.resolve_a2a_agent(agent_role)
            if card:
                total_weight += card.get("x-fde", {}).get("cost_weight", 0.5)

        # Feedback loops multiply cost by expected iterations
        topology = stage_config.get("topology", "sequential")
        if topology in ("feedback_loop", "iterative"):
            total_weight *= 2.0  # Average 2 iterations

        return total_weight

    def get_a2a_health(self) -> dict[str, Any]:
        """Get health status of all A2A agents (for portal/monitoring).

        Returns:
            Dict with agent names as keys and health info as values.
        """
        health = {}
        for name, card in self._available_agents.items():
            health[name] = {
                "endpoint": card["url"],
                "version": card["version"],
                "model_tier": card["x-fde"]["model_tier"],
                "capabilities": card["capabilities"]["tasks"],
                "status": "configured",  # Would be "healthy" after ping
            }
        return health

    @staticmethod
    def get_topology_recommendation(
        complexity_score: float,
        has_feedback_requirement: bool = False,
    ) -> str:
        """Recommend A2A topology based on task complexity.

        Maps the Cognitive Autonomy Model's capability_depth to
        the optimal A2A execution topology.

        Args:
            complexity_score: Task complexity (0.0-1.0) from the Router.
            has_feedback_requirement: Whether the task requires review cycles.

        Returns:
            Recommended topology: "sequential" | "feedback_loop" | "parallel"
        """
        if has_feedback_requirement or complexity_score >= 0.5:
            return "feedback_loop"  # Full pesquisa → escrita → revisão → rework
        elif complexity_score >= 0.3:
            return "sequential"  # pesquisa → escrita (no review)
        else:
            return "sequential"  # Simple pass-through


# ─── Convenience Functions ───────────────────────────────────────────────────


def create_bridge() -> SquadBridge:
    """Factory function for creating a SquadBridge instance.

    Returns:
        Configured SquadBridge ready for Conductor integration.
    """
    return SquadBridge()


def get_a2a_capabilities_for_conductor() -> dict[str, Any]:
    """Return A2A capabilities summary for the Conductor's planning phase.

    The Conductor calls this during squad composition to understand
    what the A2A layer can handle. This informs the WorkflowPlan
    generation — stages that A2A can handle are marked as delegatable.

    Returns:
        Capabilities summary including agents, topologies, and constraints.
    """
    return {
        "available_agents": [
            {
                "name": card["name"],
                "capabilities": card["capabilities"]["tasks"],
                "model_tier": card["x-fde"]["model_tier"],
                "cost_weight": card["x-fde"]["cost_weight"],
            }
            for card in list_cards()
        ],
        "supported_topologies": [
            "sequential",       # pesquisa → escrita
            "feedback_loop",    # pesquisa → escrita → revisão → rework (max 3)
        ],
        "constraints": {
            "max_feedback_iterations": 3,
            "default_timeout_seconds": 120,
            "checkpoint_storage": "dynamodb",
            "resilience": "sqs_dlq_after_3_retries",
        },
        "squad_role_mapping": SQUAD_ROLE_TO_A2A_AGENT,
    }
