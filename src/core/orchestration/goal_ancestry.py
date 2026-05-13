"""
Goal Ancestry — Trace Every Subtask Back to Original Request.

Implements Paperclip's goal ancestry pattern: every agent can answer
"why am I doing this?" by tracing its work back to the original user
request through the task decomposition tree.

This prevents the anti-pattern of agents doing work that no longer
serves the original goal (goal drift).

Academic basis:
  - Paperclip (Baby, 2026): goal ancestry via org tree
  - Liu et al. (2604.14228): append-only durable state
  - "The Era of Agentic Organization" (2510.26658): explicit
    coordination primitives

Integration:
  - AtomicTaskOwnership computes ancestry at assignment time
  - Adversarial gate validates ancestry at write time (Phase 3.a)
  - Conductor enriches WorkflowPlan steps with ancestry context
  - Observability portal displays ancestry for debugging

Ref: fde-design-swe-sinapses.md Section 9.4 (Goal Ancestry)
Ref: fde-design-swe-sinapses.md Section 9.8 (Adversarial Gate Enhancement)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("fde.orchestration.goal_ancestry")


@dataclass
class GoalNode:
    """A single node in the goal decomposition tree.

    Represents one level of task decomposition from the original
    user request down to the current subtask.
    """

    node_id: str
    description: str
    level: int  # 0 = original request, 1 = first decomposition, etc.
    parent_id: str | None = None
    agent_role: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "description": self.description,
            "level": self.level,
            "parent_id": self.parent_id,
            "agent_role": self.agent_role,
            "metadata": self.metadata,
        }


@dataclass
class GoalAncestryChain:
    """Complete ancestry chain from original request to current task.

    The chain is ordered from root (original request) to leaf (current task).
    Used by the adversarial gate to validate that proposed actions serve
    the original goal.
    """

    chain: list[GoalNode] = field(default_factory=list)
    original_request: str = ""
    current_task_id: str = ""

    @property
    def depth(self) -> int:
        """How many levels of decomposition from root to current."""
        return len(self.chain)

    @property
    def is_valid(self) -> bool:
        """Whether the chain has a valid root and is non-empty."""
        return len(self.chain) > 0 and self.original_request != ""

    @property
    def root(self) -> GoalNode | None:
        """The original request node."""
        return self.chain[0] if self.chain else None

    @property
    def leaf(self) -> GoalNode | None:
        """The current task node."""
        return self.chain[-1] if self.chain else None

    def to_prompt_context(self) -> str:
        """Format ancestry as context for agent prompts.

        Injected into agent system prompts so they always know
        WHY they are doing what they're doing.
        """
        if not self.chain:
            return "Goal ancestry: [not available]"

        lines = ["Goal ancestry (why you are doing this):"]
        for node in self.chain:
            indent = "  " * node.level
            prefix = "\u2192" if node.level > 0 else "\u25cf"
            lines.append(f"{indent}{prefix} L{node.level}: {node.description}")

        return "\n".join(lines)

    def to_adversarial_context(self) -> str:
        """Format ancestry for adversarial gate validation.

        The adversarial gate uses this to challenge whether a proposed
        action serves the original goal.
        """
        if not self.chain:
            return "No goal ancestry available \u2014 cannot validate goal alignment."

        parts = [
            f"Original request: {self.original_request}",
            f"Decomposition depth: {self.depth}",
            f"Current task: {self.leaf.description if self.leaf else 'unknown'}",
            "Full chain:",
        ]
        for node in self.chain:
            parts.append(f"  L{node.level} [{node.agent_role or 'system'}]: {node.description}")

        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_request": self.original_request,
            "current_task_id": self.current_task_id,
            "depth": self.depth,
            "chain": [n.to_dict() for n in self.chain],
        }


class GoalAncestryTracker:
    """Tracks the full goal decomposition tree for a workflow.

    Maintains the tree structure so that any node can compute its
    full ancestry chain back to the root (original user request).

    Usage:
        tracker = GoalAncestryTracker(original_request="Build login feature")
        tracker.register_decomposition(
            parent_id="root",
            child_id="subtask-1",
            description="Implement JWT validation",
            agent_role="swe-developer-agent",
        )
        chain = tracker.get_ancestry("subtask-1")
        # chain.to_prompt_context() -> injected into agent prompt
    """

    ROOT_NODE_ID = "__root__"

    def __init__(self, original_request: str, workflow_plan_id: str = ""):
        """Initialize tracker with the original user request.

        Args:
            original_request: The original task description from the user.
            workflow_plan_id: The WorkflowPlan this tracker belongs to.
        """
        self._original_request = original_request
        self._plan_id = workflow_plan_id
        self._nodes: dict[str, GoalNode] = {}

        # Register root node
        root = GoalNode(
            node_id=self.ROOT_NODE_ID,
            description=original_request,
            level=0,
            parent_id=None,
            agent_role="user",
        )
        self._nodes[self.ROOT_NODE_ID] = root

    @property
    def original_request(self) -> str:
        return self._original_request

    @property
    def total_nodes(self) -> int:
        return len(self._nodes)

    @property
    def max_depth(self) -> int:
        """Maximum decomposition depth in the tree."""
        if not self._nodes:
            return 0
        return max(n.level for n in self._nodes.values())

    def register_decomposition(
        self,
        parent_id: str,
        child_id: str,
        description: str,
        agent_role: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> GoalNode:
        """Register a task decomposition (parent -> child).

        Args:
            parent_id: The parent task that was decomposed.
            child_id: The new subtask created from decomposition.
            description: Human-readable description of the subtask.
            agent_role: Which agent role will handle this subtask.
            metadata: Additional context.

        Returns:
            The newly created GoalNode.
        """
        parent = self._nodes.get(parent_id)
        parent_level = parent.level if parent else 0

        node = GoalNode(
            node_id=child_id,
            description=description,
            level=parent_level + 1,
            parent_id=parent_id,
            agent_role=agent_role,
            metadata=metadata or {},
        )

        self._nodes[child_id] = node

        logger.debug(
            "Goal decomposition: parent=%s -> child=%s level=%d agent=%s",
            parent_id, child_id, node.level, agent_role,
        )

        return node

    def get_ancestry(self, task_id: str) -> GoalAncestryChain:
        """Compute the full ancestry chain for a task.

        Walks from the given task up to the root, then reverses
        to produce a root-to-leaf chain.

        Args:
            task_id: The task to compute ancestry for.

        Returns:
            GoalAncestryChain from root to the given task.
        """
        chain: list[GoalNode] = []
        current_id: str | None = task_id
        visited: set[str] = set()

        while current_id and current_id not in visited:
            visited.add(current_id)
            node = self._nodes.get(current_id)
            if node:
                chain.append(node)
                current_id = node.parent_id
            else:
                break

        # Reverse to get root-to-leaf order
        chain.reverse()

        return GoalAncestryChain(
            chain=chain,
            original_request=self._original_request,
            current_task_id=task_id,
        )

    def validate_goal_alignment(self, task_id: str, proposed_action: str) -> GoalAlignmentResult:
        """Validate whether a proposed action aligns with the goal ancestry.

        Used by the adversarial gate (Phase 3.a) to detect goal drift.
        An action is considered aligned if it can be traced back to the
        original request through a clear causal chain.

        Args:
            task_id: The task proposing the action.
            proposed_action: Description of what the agent wants to do.

        Returns:
            GoalAlignmentResult with alignment assessment.
        """
        ancestry = self.get_ancestry(task_id)

        if not ancestry.is_valid:
            return GoalAlignmentResult(
                is_aligned=False,
                confidence=0.0,
                reason="No valid goal ancestry found \u2014 cannot validate alignment.",
                ancestry=ancestry,
            )

        # Heuristic alignment check:
        # The proposed action should share semantic content with at least
        # one node in the ancestry chain.
        action_words = set(proposed_action.lower().split())
        ancestry_words: set[str] = set()
        for node in ancestry.chain:
            ancestry_words.update(node.description.lower().split())

        # Remove common stop words
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "to", "for",
                      "in", "on", "at", "by", "with", "from", "and", "or", "not",
                      "this", "that", "it", "of", "as", "be", "has", "have", "do"}
        action_meaningful = action_words - stop_words
        ancestry_meaningful = ancestry_words - stop_words

        if not action_meaningful:
            return GoalAlignmentResult(
                is_aligned=True,
                confidence=0.5,
                reason="Action description too short for semantic validation.",
                ancestry=ancestry,
            )

        overlap = action_meaningful & ancestry_meaningful
        overlap_ratio = len(overlap) / len(action_meaningful) if action_meaningful else 0.0

        is_aligned = overlap_ratio >= 0.15  # At least 15% word overlap
        confidence = min(1.0, overlap_ratio * 2.0)  # Scale to [0, 1]

        if is_aligned:
            reason = (
                f"Action aligns with goal ancestry "
                f"(overlap={overlap_ratio:.0%}, shared terms: {sorted(list(overlap))[:5]})"
            )
        else:
            reason = (
                f"Potential goal drift detected. Action has low overlap with ancestry "
                f"(overlap={overlap_ratio:.0%}). Original request: '{self._original_request}'"
            )

        return GoalAlignmentResult(
            is_aligned=is_aligned,
            confidence=confidence,
            reason=reason,
            ancestry=ancestry,
        )

    def get_node(self, node_id: str) -> GoalNode | None:
        """Get a specific node by ID."""
        return self._nodes.get(node_id)

    def get_children(self, parent_id: str) -> list[GoalNode]:
        """Get all direct children of a node."""
        return [
            n for n in self._nodes.values()
            if n.parent_id == parent_id
        ]

    def to_dict(self) -> dict[str, Any]:
        """Serialize full tree for observability."""
        return {
            "original_request": self._original_request,
            "workflow_plan_id": self._plan_id,
            "total_nodes": self.total_nodes,
            "max_depth": self.max_depth,
            "nodes": {nid: n.to_dict() for nid, n in self._nodes.items()},
        }


@dataclass
class GoalAlignmentResult:
    """Result of goal alignment validation."""

    is_aligned: bool
    confidence: float  # [0, 1] how confident we are in the alignment assessment
    reason: str
    ancestry: GoalAncestryChain

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_aligned": self.is_aligned,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "ancestry_depth": self.ancestry.depth,
        }


def compute_goal_ancestry(
    task_id: str,
    task_parents: dict[str, str],
    task_descriptions: dict[str, str],
    original_request: str,
) -> list[str]:
    """Standalone utility: compute goal ancestry from flat maps.

    This is a convenience function for contexts where a full
    GoalAncestryTracker is not available (e.g., agent prompts
    that receive flat data from SCD).

    Args:
        task_id: The task to compute ancestry for.
        task_parents: Map of task_id -> parent_task_id.
        task_descriptions: Map of task_id -> description.
        original_request: The root-level user request.

    Returns:
        List of descriptions from root to current task's parent.
    """
    ancestry: list[str] = []
    current_id = task_id
    visited: set[str] = set()

    while current_id in task_parents and current_id not in visited:
        visited.add(current_id)
        parent_id = task_parents[current_id]
        description = task_descriptions.get(parent_id, parent_id)
        ancestry.append(description)
        current_id = parent_id

    if original_request:
        ancestry.append(original_request)

    return list(reversed(ancestry))
