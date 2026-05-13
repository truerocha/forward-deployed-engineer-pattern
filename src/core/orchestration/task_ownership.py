"""
Atomic Task Ownership — Lock Semantics for Conductor Subtasks.

Implements Paperclip's atomic task checkout pattern to prevent the
MAST taxonomy's #1 failure mode: two agents claiming the same work,
producing conflicting outputs.

Key invariant: exactly ONE agent owns each subtask at any time.
A task is locked to its owner until completion or explicit release.

Academic basis:
  - Paperclip (Baby, 2026): atomic task checkout, per-agent budgets
  - MAST taxonomy (arXiv:2503.13657): 33% of multi-agent failures
    are coordination failures, not model failures
  - Agent saturation at 3-4 concurrent agents

Integration:
  - Conductor assigns ownership during WorkflowPlan execution
  - HeartbeatAwareConductor monitors liveness (Synapse 6)
  - Goal ancestry traces every subtask back to original request

Ref: fde-design-swe-sinapses.md Section 9.4 (Atomic Task Ownership)
Ref: ADR-020 (Conductor Orchestration Pattern)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger("fde.orchestration.task_ownership")


class TaskOwnershipStatus(Enum):
    """Lifecycle states for task ownership."""

    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    RELEASED = "released"
    TIMED_OUT = "timed_out"


class TaskAlreadyOwnedError(Exception):
    """Raised when attempting to assign a task that is already owned."""

    def __init__(self, task_id: str, current_owner: str, requested_by: str):
        self.task_id = task_id
        self.current_owner = current_owner
        self.requested_by = requested_by
        super().__init__(
            f"Task {task_id} is owned by '{current_owner}'. "
            f"Cannot assign to '{requested_by}'. Use release_task() first."
        )


class TaskNotOwnedError(Exception):
    """Raised when attempting to release or complete a task not owned by the caller."""

    def __init__(self, task_id: str, actual_owner: str | None, claimed_by: str):
        self.task_id = task_id
        self.actual_owner = actual_owner
        self.claimed_by = claimed_by
        super().__init__(
            f"Task {task_id} is owned by '{actual_owner}', "
            f"not '{claimed_by}'. Cannot release/complete."
        )


@dataclass
class TaskAssignment:
    """Record of a task assignment with ownership metadata."""

    task_id: str
    owner_agent_id: str
    status: TaskOwnershipStatus = TaskOwnershipStatus.ASSIGNED
    checkout_time: str = ""
    completion_time: str = ""
    goal_ancestry: list[str] = field(default_factory=list)
    timeout_seconds: int = 600
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.checkout_time:
            self.checkout_time = datetime.now(timezone.utc).isoformat()

    @property
    def is_active(self) -> bool:
        """Whether this assignment is currently active (not completed/released)."""
        return self.status in (
            TaskOwnershipStatus.ASSIGNED,
            TaskOwnershipStatus.IN_PROGRESS,
        )

    @property
    def is_timed_out(self) -> bool:
        """Whether this assignment has exceeded its timeout."""
        if not self.is_active:
            return False
        checkout = datetime.fromisoformat(self.checkout_time)
        elapsed = (datetime.now(timezone.utc) - checkout).total_seconds()
        return elapsed > self.timeout_seconds

    def to_dict(self) -> dict[str, Any]:
        """Serialize for observability and SCD persistence."""
        return {
            "task_id": self.task_id,
            "owner_agent_id": self.owner_agent_id,
            "status": self.status.value,
            "checkout_time": self.checkout_time,
            "completion_time": self.completion_time,
            "goal_ancestry": self.goal_ancestry,
            "timeout_seconds": self.timeout_seconds,
            "metadata": self.metadata,
        }


class AtomicTaskOwnership:
    """Ensures exactly one agent owns each subtask at any time.

    Prevents the MAST taxonomy's #1 failure mode: two agents
    claiming the same work, producing conflicting outputs.

    Thread-safety note: In the FDE pipeline, tasks are dispatched
    sequentially by the Conductor. This class provides logical
    ownership semantics, not OS-level locking. For distributed
    execution (ECS Fargate), DynamoDB conditional writes provide
    the actual atomic guarantee.

    Usage:
        ownership = AtomicTaskOwnership(workflow_plan_id="plan-123")
        assignment = ownership.assign_task("subtask-1", "swe-developer-agent")
        # ... agent executes ...
        ownership.complete_task("subtask-1", "swe-developer-agent")
    """

    def __init__(
        self,
        workflow_plan_id: str,
        original_request: str = "",
        max_concurrent_assignments: int = 4,
    ):
        """Initialize ownership tracker for a workflow plan.

        Args:
            workflow_plan_id: The WorkflowPlan this tracker manages.
            original_request: The original user request (root of goal ancestry).
            max_concurrent_assignments: Maximum concurrent active assignments.
                Based on MAST finding: performance saturates at 3-4 agents.
        """
        self._plan_id = workflow_plan_id
        self._original_request = original_request
        self._max_concurrent = max_concurrent_assignments
        self._assignments: dict[str, TaskAssignment] = {}
        self._task_parents: dict[str, str] = {}  # task_id -> parent_task_id

    @property
    def plan_id(self) -> str:
        return self._plan_id

    @property
    def active_assignments(self) -> list[TaskAssignment]:
        """All currently active (assigned or in-progress) tasks."""
        return [a for a in self._assignments.values() if a.is_active]

    @property
    def active_count(self) -> int:
        """Number of currently active assignments."""
        return len(self.active_assignments)

    @property
    def is_at_capacity(self) -> bool:
        """Whether we've hit the concurrent assignment limit."""
        return self.active_count >= self._max_concurrent

    def register_task_hierarchy(self, task_id: str, parent_task_id: str | None) -> None:
        """Register parent-child relationship for goal ancestry computation.

        Args:
            task_id: The subtask being registered.
            parent_task_id: Its parent task (None for root-level tasks).
        """
        if parent_task_id:
            self._task_parents[task_id] = parent_task_id

    def assign_task(
        self,
        task_id: str,
        agent_id: str,
        parent_task_id: str | None = None,
        timeout_seconds: int = 600,
        metadata: dict[str, Any] | None = None,
    ) -> TaskAssignment:
        """Atomic checkout: lock task to agent until completion or release.

        Args:
            task_id: Unique subtask identifier.
            agent_id: Agent role/id claiming ownership.
            parent_task_id: Parent task for goal ancestry.
            timeout_seconds: Max time before auto-release.
            metadata: Additional context for observability.

        Returns:
            TaskAssignment record.

        Raises:
            TaskAlreadyOwnedError: If task is already owned by another agent.
        """
        existing = self._assignments.get(task_id)

        if existing and existing.is_active:
            if existing.owner_agent_id != agent_id:
                raise TaskAlreadyOwnedError(
                    task_id=task_id,
                    current_owner=existing.owner_agent_id,
                    requested_by=agent_id,
                )
            # Same agent re-assigning — idempotent, return existing
            logger.debug(
                "Idempotent re-assignment: task=%s agent=%s", task_id, agent_id
            )
            return existing

        # Check capacity
        if self.is_at_capacity:
            logger.warning(
                "At capacity (%d/%d active). Assigning task=%s may degrade performance.",
                self.active_count, self._max_concurrent, task_id,
            )

        # Register hierarchy
        if parent_task_id:
            self._task_parents[task_id] = parent_task_id

        # Compute goal ancestry
        goal_ancestry = self.compute_goal_ancestry(task_id)

        assignment = TaskAssignment(
            task_id=task_id,
            owner_agent_id=agent_id,
            status=TaskOwnershipStatus.ASSIGNED,
            goal_ancestry=goal_ancestry,
            timeout_seconds=timeout_seconds,
            metadata=metadata or {},
        )

        self._assignments[task_id] = assignment

        logger.info(
            "Task assigned: task=%s agent=%s ancestry_depth=%d plan=%s",
            task_id, agent_id, len(goal_ancestry), self._plan_id,
        )

        return assignment

    def start_task(self, task_id: str, agent_id: str) -> TaskAssignment:
        """Mark task as in-progress (agent has begun execution).

        Args:
            task_id: The task being started.
            agent_id: The agent starting it (must be the owner).

        Returns:
            Updated TaskAssignment.

        Raises:
            TaskNotOwnedError: If agent is not the owner.
        """
        assignment = self._get_owned_assignment(task_id, agent_id)
        assignment.status = TaskOwnershipStatus.IN_PROGRESS

        logger.debug("Task started: task=%s agent=%s", task_id, agent_id)
        return assignment

    def complete_task(self, task_id: str, agent_id: str) -> TaskAssignment:
        """Mark task as completed and release ownership.

        Args:
            task_id: The task being completed.
            agent_id: The agent completing it (must be the owner).

        Returns:
            Updated TaskAssignment with completion timestamp.

        Raises:
            TaskNotOwnedError: If agent is not the owner.
        """
        assignment = self._get_owned_assignment(task_id, agent_id)
        assignment.status = TaskOwnershipStatus.COMPLETED
        assignment.completion_time = datetime.now(timezone.utc).isoformat()

        logger.info("Task completed: task=%s agent=%s", task_id, agent_id)
        return assignment

    def release_task(self, task_id: str, agent_id: str, reason: str = "") -> TaskAssignment:
        """Explicitly release ownership without completing.

        Used when an agent cannot complete a task and it should
        be returned to the queue for reassignment.

        Args:
            task_id: The task being released.
            agent_id: The agent releasing it (must be the owner).
            reason: Why the task is being released.

        Returns:
            Updated TaskAssignment.

        Raises:
            TaskNotOwnedError: If agent is not the owner.
        """
        assignment = self._get_owned_assignment(task_id, agent_id)
        assignment.status = TaskOwnershipStatus.RELEASED
        assignment.metadata["release_reason"] = reason

        logger.info(
            "Task released: task=%s agent=%s reason=%s",
            task_id, agent_id, reason,
        )
        return assignment

    def check_timeouts(self) -> list[TaskAssignment]:
        """Check all active assignments for timeouts.

        Returns list of assignments that have timed out.
        Called by HeartbeatAwareConductor on each heartbeat cycle.
        """
        timed_out: list[TaskAssignment] = []

        for assignment in self.active_assignments:
            if assignment.is_timed_out:
                assignment.status = TaskOwnershipStatus.TIMED_OUT
                assignment.metadata["timeout_detected_at"] = (
                    datetime.now(timezone.utc).isoformat()
                )
                timed_out.append(assignment)
                logger.warning(
                    "Task timed out: task=%s agent=%s timeout=%ds plan=%s",
                    assignment.task_id,
                    assignment.owner_agent_id,
                    assignment.timeout_seconds,
                    self._plan_id,
                )

        return timed_out

    def compute_goal_ancestry(self, task_id: str) -> list[str]:
        """Walk the goal tree to answer 'why am I doing this?'

        Every agent can trace its work back to the original user request.
        This prevents the anti-pattern of agents doing work that no longer
        serves the original goal (drift).

        Returns:
            List from original request down to current task's parent.
            Example: ["Build login feature", "Implement auth module", "Write JWT validator"]
        """
        ancestry: list[str] = []
        current_id = task_id
        visited: set[str] = set()  # Prevent cycles

        while current_id in self._task_parents and current_id not in visited:
            visited.add(current_id)
            parent_id = self._task_parents[current_id]
            parent_assignment = self._assignments.get(parent_id)
            if parent_assignment:
                ancestry.append(
                    parent_assignment.metadata.get("description", parent_id)
                )
            else:
                ancestry.append(parent_id)
            current_id = parent_id

        # Add original request as the root
        if self._original_request:
            ancestry.append(self._original_request)

        return list(reversed(ancestry))

    def get_assignment(self, task_id: str) -> TaskAssignment | None:
        """Get the current assignment for a task (if any)."""
        return self._assignments.get(task_id)

    def get_agent_assignments(self, agent_id: str) -> list[TaskAssignment]:
        """Get all assignments (active and completed) for an agent."""
        return [
            a for a in self._assignments.values()
            if a.owner_agent_id == agent_id
        ]

    def to_dict(self) -> dict[str, Any]:
        """Serialize full ownership state for observability."""
        return {
            "plan_id": self._plan_id,
            "original_request": self._original_request,
            "max_concurrent": self._max_concurrent,
            "active_count": self.active_count,
            "total_assignments": len(self._assignments),
            "assignments": {
                tid: a.to_dict() for tid, a in self._assignments.items()
            },
        }

    # ─── Private Helpers ────────────────────────────────────────

    def _get_owned_assignment(self, task_id: str, agent_id: str) -> TaskAssignment:
        """Get assignment and verify ownership."""
        assignment = self._assignments.get(task_id)

        if not assignment:
            raise TaskNotOwnedError(
                task_id=task_id, actual_owner=None, claimed_by=agent_id
            )

        if assignment.owner_agent_id != agent_id:
            raise TaskNotOwnedError(
                task_id=task_id,
                actual_owner=assignment.owner_agent_id,
                claimed_by=agent_id,
            )

        if not assignment.is_active:
            raise TaskNotOwnedError(
                task_id=task_id,
                actual_owner=f"{assignment.owner_agent_id} (status={assignment.status.value})",
                claimed_by=agent_id,
            )

        return assignment
