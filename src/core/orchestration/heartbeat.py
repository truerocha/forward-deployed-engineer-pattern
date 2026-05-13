"""
Heartbeat-Aware Conductor — Persistent Execution Governance for O4-O5 Tasks.

Extends the Conductor (ADR-020) with the OpenClaw heartbeat pattern for
long-running autonomous tasks. Unlike prompt-triggered agents that complete
and stop, the heartbeat conductor runs persistently: at regular intervals
it checks task state, evaluates what needs action, probes transparency,
and either acts or waits.

Academic basis:
  - NVIDIA/OpenClaw (Boitano, April 2026): heartbeat pattern shifts agents
    from "on-demand" to "always-on" with enterprise governance layers
  - Anthropic/NLA (May 2026): ATTP probes at each heartbeat cycle detect
    reasoning divergence before it cascades

Execution modes:
  - Standard (O1-O3): prompt -> execute -> complete (traditional)
  - Heartbeat (O4-O5): heartbeat cycle -> check -> evaluate -> act -> wait

Integration:
  - Uses AtomicTaskOwnership for liveness monitoring
  - Uses ATTP probes at governance-critical decision points
  - Respects token budgets to prevent runaway costs
  - Escalates to human when divergence > 0.6

Ref: fde-design-swe-sinapses.md Section 8.4 (Heartbeat-Aware Conductor)
Ref: fde-design-swe-sinapses.md Section 8.6 (Inference Economics)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from src.core.orchestration.task_ownership import AtomicTaskOwnership
from src.core.risk.attp import (
    ATTPBudget,
    AgentThoughtTransparency,
    probe_agent_transparency,
)

logger = logging.getLogger("fde.orchestration.heartbeat")


class HeartbeatPhase(Enum):
    """Phases of the heartbeat execution cycle."""

    CHECK = "check"
    EVALUATE = "evaluate"
    PROBE = "probe"
    ACT = "act"
    WAIT = "wait"


class ExecutionMode(Enum):
    """Task execution mode based on organism level."""

    STANDARD = "standard"
    HEARTBEAT = "heartbeat"


@dataclass
class HeartbeatConfig:
    """Configuration for heartbeat execution mode.

    Controls timing, budgets, and escalation thresholds for
    persistent task execution.

    Ref: fde-design-swe-sinapses.md Section 8.6 (Inference Economics)
    """

    heartbeat_interval_o4: int = 300
    heartbeat_interval_o5: int = 600
    heartbeat_token_budget: int = 5000
    attp_probe_budget: int = 10000
    total_task_ceiling: int = 200000
    divergence_escalation_threshold: float = 0.6
    max_consecutive_waits: int = 10
    max_heartbeat_cycles: int = 50
    task_timeout_seconds: int = 3600

    def get_interval(self, organism_level: str) -> int:
        """Get heartbeat interval for organism level."""
        if organism_level == "O5":
            return self.heartbeat_interval_o5
        return self.heartbeat_interval_o4

    def to_dict(self) -> dict[str, Any]:
        return {
            "heartbeat_interval_o4": self.heartbeat_interval_o4,
            "heartbeat_interval_o5": self.heartbeat_interval_o5,
            "heartbeat_token_budget": self.heartbeat_token_budget,
            "attp_probe_budget": self.attp_probe_budget,
            "total_task_ceiling": self.total_task_ceiling,
            "divergence_escalation_threshold": self.divergence_escalation_threshold,
            "max_consecutive_waits": self.max_consecutive_waits,
            "max_heartbeat_cycles": self.max_heartbeat_cycles,
            "task_timeout_seconds": self.task_timeout_seconds,
        }


@dataclass
class HeartbeatState:
    """Tracks the state of a heartbeat execution cycle."""

    task_id: str
    organism_level: str
    current_phase: HeartbeatPhase = HeartbeatPhase.CHECK
    cycles_completed: int = 0
    consecutive_waits: int = 0
    total_tokens_consumed: int = 0
    is_complete: bool = False
    is_escalated: bool = False
    escalation_reason: str = ""
    started_at: str = ""
    last_heartbeat_at: str = ""
    transparency_probes: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = datetime.now(timezone.utc).isoformat()

    @property
    def elapsed_seconds(self) -> float:
        started = datetime.fromisoformat(self.started_at)
        return (datetime.now(timezone.utc) - started).total_seconds()

    def record_cycle(self, tokens_used: int = 0) -> None:
        self.cycles_completed += 1
        self.total_tokens_consumed += tokens_used
        self.last_heartbeat_at = datetime.now(timezone.utc).isoformat()

    def record_wait(self) -> None:
        self.consecutive_waits += 1

    def record_action(self) -> None:
        self.consecutive_waits = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "organism_level": self.organism_level,
            "current_phase": self.current_phase.value,
            "cycles_completed": self.cycles_completed,
            "consecutive_waits": self.consecutive_waits,
            "total_tokens_consumed": self.total_tokens_consumed,
            "is_complete": self.is_complete,
            "is_escalated": self.is_escalated,
            "escalation_reason": self.escalation_reason,
            "started_at": self.started_at,
            "last_heartbeat_at": self.last_heartbeat_at,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "transparency_probes_count": len(self.transparency_probes),
        }


@dataclass
class HeartbeatDecision:
    """Decision made during the EVALUATE phase of a heartbeat cycle."""

    should_act: bool
    reasoning: str
    next_step_index: int | None = None
    confidence: float = 0.5

    def to_dict(self) -> dict[str, Any]:
        return {
            "should_act": self.should_act,
            "reasoning": self.reasoning,
            "next_step_index": self.next_step_index,
            "confidence": round(self.confidence, 4),
        }


def select_execution_mode(organism_level: str) -> ExecutionMode:
    """Select execution mode based on organism level.

    Standard tasks (O1-O3): prompt -> execute -> complete
    Complex tasks (O4-O5): heartbeat cycle

    Args:
        organism_level: Task complexity classification (O1-O5).

    Returns:
        ExecutionMode for the task.
    """
    if organism_level in ("O4", "O5"):
        return ExecutionMode.HEARTBEAT
    return ExecutionMode.STANDARD


class HeartbeatAwareConductor:
    """Extends Conductor with persistent heartbeat cycle for O4-O5 tasks.

    The heartbeat pattern prevents the anti-pattern of "fire and forget"
    for complex tasks that require iterative refinement.

    Lifecycle:
      1. Task arrives with O4/O5 classification
      2. Conductor generates WorkflowPlan (standard path)
      3. HeartbeatAwareConductor wraps execution in heartbeat cycle
      4. Each cycle: CHECK -> EVALUATE -> PROBE -> ACT/WAIT
      5. ATTP probes run at governance-critical points
      6. Escalation triggers on divergence > 0.6 or budget exhaustion

    Usage:
        conductor = HeartbeatAwareConductor()
        state = conductor.create_heartbeat_state("task-1", "O4")
        while conductor.should_continue(state):
            task_state = conductor.check_task_state(state, ownership)
            decision = conductor.evaluate_next_action(state, task_state, pending)
            conductor.run_transparency_probe(state, decision)
            conductor.record_cycle_outcome(state, decision)
    """

    def __init__(self, config: HeartbeatConfig | None = None):
        self._config = config or HeartbeatConfig()
        self._attp_budget = ATTPBudget(
            max_total_tokens=self._config.attp_probe_budget,
        )

    @property
    def config(self) -> HeartbeatConfig:
        return self._config

    def create_heartbeat_state(self, task_id: str, organism_level: str) -> HeartbeatState:
        """Create initial heartbeat state for a task."""
        return HeartbeatState(task_id=task_id, organism_level=organism_level)

    def should_continue(self, state: HeartbeatState) -> bool:
        """Determine if the heartbeat cycle should continue."""
        if state.is_complete or state.is_escalated:
            return False

        if state.cycles_completed >= self._config.max_heartbeat_cycles:
            state.is_escalated = True
            state.escalation_reason = f"Max heartbeat cycles ({self._config.max_heartbeat_cycles}) exceeded"
            return False

        if state.total_tokens_consumed >= self._config.total_task_ceiling:
            state.is_escalated = True
            state.escalation_reason = f"Token ceiling ({self._config.total_task_ceiling}) exceeded"
            return False

        if state.elapsed_seconds >= self._config.task_timeout_seconds:
            state.is_escalated = True
            state.escalation_reason = f"Task timeout ({self._config.task_timeout_seconds}s) exceeded"
            return False

        if state.consecutive_waits >= self._config.max_consecutive_waits:
            state.is_escalated = True
            state.escalation_reason = f"Max consecutive waits ({self._config.max_consecutive_waits}) — task appears stalled"
            return False

        return True

    def check_task_state(self, state: HeartbeatState, ownership: AtomicTaskOwnership) -> dict[str, Any]:
        """Phase 1: CHECK — what's the current state?"""
        state.current_phase = HeartbeatPhase.CHECK
        timed_out = ownership.check_timeouts()

        return {
            "active_count": ownership.active_count,
            "timed_out_count": len(timed_out),
            "timed_out_tasks": [t.task_id for t in timed_out],
            "is_at_capacity": ownership.is_at_capacity,
            "cycle": state.cycles_completed,
            "elapsed_seconds": state.elapsed_seconds,
        }

    def evaluate_next_action(
        self, state: HeartbeatState, task_state: dict[str, Any], pending_steps: list[dict[str, Any]],
    ) -> HeartbeatDecision:
        """Phase 2: EVALUATE — should we act or wait?"""
        state.current_phase = HeartbeatPhase.EVALUATE

        if task_state.get("timed_out_count", 0) > 0:
            return HeartbeatDecision(
                should_act=True,
                reasoning="Timed-out tasks detected — need reassignment or escalation",
                confidence=0.9,
            )

        if pending_steps and not task_state.get("is_at_capacity", False):
            next_step = pending_steps[0]
            return HeartbeatDecision(
                should_act=True,
                reasoning=f"Pending step available: {next_step.get('subtask', 'unknown')[:50]}",
                next_step_index=next_step.get("step_index"),
                confidence=0.8,
            )

        if task_state.get("active_count", 0) > 0 and not pending_steps:
            return HeartbeatDecision(
                should_act=False,
                reasoning="All steps in progress — waiting for completion",
                confidence=0.7,
            )

        return HeartbeatDecision(
            should_act=False,
            reasoning="No actionable items — waiting for next cycle",
            confidence=0.5,
        )

    def run_transparency_probe(
        self, state: HeartbeatState, decision: HeartbeatDecision, task_context: dict[str, Any] | None = None,
    ) -> AgentThoughtTransparency | None:
        """Phase 3: PROBE — transparency check (NLA-lite)."""
        state.current_phase = HeartbeatPhase.PROBE

        if not self._attp_budget.can_probe:
            return None

        if decision.confidence >= 0.8 and decision.should_act:
            return None

        probe_result = probe_agent_transparency(
            agent_output=decision.reasoning,
            probed_response="",
            task_id=state.task_id,
            agent_role="heartbeat-conductor",
            heartbeat_phase=state.current_phase.value,
            probe_tokens=0,
        )

        self._attp_budget.record_probe(probe_result.probe_budget_used)
        state.transparency_probes.append(probe_result.to_dict())

        if probe_result.requires_escalation:
            state.is_escalated = True
            state.escalation_reason = f"High reasoning divergence (score={probe_result.divergence_score:.2f})"

        return probe_result

    def record_cycle_outcome(self, state: HeartbeatState, decision: HeartbeatDecision, tokens_used: int = 0) -> None:
        """Record the outcome of a heartbeat cycle."""
        if decision.should_act:
            state.current_phase = HeartbeatPhase.ACT
            state.record_action()
        else:
            state.current_phase = HeartbeatPhase.WAIT
            state.record_wait()

        state.record_cycle(tokens_used)

    def get_wait_interval(self, state: HeartbeatState) -> int:
        """Get the wait interval for the current state."""
        return self._config.get_interval(state.organism_level)

    def to_dict(self) -> dict[str, Any]:
        return {"config": self._config.to_dict(), "attp_budget": self._attp_budget.to_dict()}
