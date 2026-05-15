"""
design_phase_injector.py — Injects Brown-Field Elevation and DDD Design Phase steps.

This module reads fde-profile.json and conditionally injects architect steps
into the Conductor's workflow plan before it's converted to a SquadManifest.

Integration point: Called from conductor_integration.generate_conductor_manifest()
after the Conductor generates its plan but before _convert_plan_to_manifest().

Ref: ADR-032 (Extension Opt-In System)
Ref: ADR-033 (Brown-Field Elevation & DDD Design Phase)
"""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("fde.design-phase-injector")

# ─── Profile Loading ─────────────────────────────────────────────────────────

_PROFILE_PATHS = [
    Path("fde-profile.json"),                    # Project root (when running from repo)
    Path("/workspaces") / "fde-profile.json",    # EFS workspace fallback
]


def load_fde_profile() -> dict[str, Any]:
    """Load fde-profile.json from project root. Returns empty dict if not found."""
    for path in _PROFILE_PATHS:
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load %s: %s", path, e)
    return {}


def is_extension_enabled(profile: dict[str, Any], extension_name: str) -> bool:
    """Check if an extension is enabled in the profile."""
    extensions = profile.get("extensions", {})
    return extensions.get(extension_name, False)


def get_auto_design_threshold(profile: dict[str, Any]) -> float:
    """Get the cognitive depth threshold for auto-activating design phase."""
    conductor = profile.get("conductor", {})
    return conductor.get("auto-design-threshold", 0.5)


# ─── Step Injection ──────────────────────────────────────────────────────────

class DesignPhaseStep:
    """Represents an injected design phase step."""

    def __init__(
        self,
        step_index: int,
        subtask: str,
        agent_role: str,
        model_tier: str,
        access_list: list[int | str],
        outputs: list[str],
    ):
        self.step_index = step_index
        self.subtask = subtask
        self.agent_role = agent_role
        self.model_tier = model_tier
        self.access_list = access_list
        self.outputs = outputs

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_index": self.step_index,
            "subtask": self.subtask,
            "agent_role": self.agent_role,
            "model_tier": self.model_tier,
            "access_list": self.access_list,
            "outputs": self.outputs,
            "injected_by": "design_phase_injector",
        }


def compute_design_steps(
    profile: dict[str, Any],
    cognitive_depth: float,
    is_brown_field: bool,
    task_description: str = "",
    force_design: bool = False,
) -> list[DesignPhaseStep]:
    """Compute which design phase steps should be injected.

    Args:
        profile: Loaded fde-profile.json content.
        cognitive_depth: Current task's cognitive depth (0.0-1.0).
        is_brown_field: Whether the task modifies existing files.
        task_description: Task description for context.
        force_design: Override threshold — always include design phase.

    Returns:
        List of DesignPhaseStep to inject at the beginning of the plan.
        Empty list if no design steps are needed.
    """
    steps: list[DesignPhaseStep] = []
    threshold = get_auto_design_threshold(profile)

    # Step 0: Brown-Field Elevation
    if is_extension_enabled(profile, "brown-field-elevation") and is_brown_field:
        steps.append(DesignPhaseStep(
            step_index=0,
            subtask=(
                "Elevate existing code into semantic model. Produce: "
                "1) Static model (components, responsibilities, relationships), "
                "2) Dynamic model (key interaction flows), "
                "3) Boundary map (files → bounded contexts), "
                "4) Change impact assessment. "
                f"Context: {task_description[:200]}"
            ),
            agent_role="architect",
            model_tier="reasoning",
            access_list=["all"],
            outputs=["aidlc-docs/design-artifacts/elevation-model.md"],
        ))

    # Step 1: DDD Design Phase
    should_design = (
        is_extension_enabled(profile, "ddd-design-phase")
        and (cognitive_depth >= threshold or force_design)
    )

    if should_design:
        elevation_access = [0] if steps else []  # Reference elevation if it exists

        steps.append(DesignPhaseStep(
            step_index=len(steps),
            subtask=(
                "Domain design: identify aggregates, entities, value objects, "
                "domain events, repositories, and domain services. "
                "Apply DDD tactical patterns. Reference WAF corpus for "
                "well-architected alignment. "
                f"Context: {task_description[:200]}"
            ),
            agent_role="architect",
            model_tier="reasoning",
            access_list=elevation_access,
            outputs=["aidlc-docs/design-artifacts/domain-model.md"],
        ))

        steps.append(DesignPhaseStep(
            step_index=len(steps),
            subtask=(
                "Logical design: select architecture patterns (CQRS, event sourcing, "
                "circuit breaker, etc.), create ADRs for key decisions, map domain "
                "components to AWS services, validate against Well-Architected pillars. "
                f"Context: {task_description[:200]}"
            ),
            agent_role="architect",
            model_tier="reasoning",
            access_list=list(range(len(steps))),  # Access all prior steps
            outputs=["aidlc-docs/design-artifacts/logical-design.md"],
        ))

    if steps:
        logger.info(
            "Design phase: injecting %d steps (brown_field=%s, depth=%.2f, threshold=%.2f)",
            len(steps), is_brown_field, cognitive_depth, threshold,
        )

    return steps


def inject_design_steps_into_plan(
    plan_steps: list[dict[str, Any]],
    design_steps: list[DesignPhaseStep],
) -> list[dict[str, Any]]:
    """Inject design steps at the beginning of a plan, re-indexing existing steps.

    Args:
        plan_steps: Original plan steps from the Conductor.
        design_steps: Design phase steps to inject.

    Returns:
        New list with design steps prepended and all step_index values re-numbered.
        Existing steps' access_lists are updated to include design step indices.
    """
    if not design_steps:
        return plan_steps

    offset = len(design_steps)
    injected = [step.to_dict() for step in design_steps]

    # Re-index existing steps and update their access lists
    reindexed = []
    for step in plan_steps:
        new_step = dict(step)
        new_step["step_index"] = step.get("step_index", 0) + offset

        # Update access_list: shift indices and add design step references
        original_access = step.get("access_list", [])
        new_access = []
        for item in original_access:
            if isinstance(item, int):
                new_access.append(item + offset)
            elif item == "all":
                new_access.append("all")
            else:
                new_access.append(item)

        # Add design step indices to coder/reviewer access lists
        role = step.get("agent_role", "")
        if role in ("coder", "swe-developer-agent", "reviewer", "fde-fidelity-agent", "adversarial"):
            design_indices = list(range(offset))
            new_access = design_indices + new_access

        new_step["access_list"] = new_access
        reindexed.append(new_step)

    return injected + reindexed


# ─── Convenience: Full Integration ──────────────────────────────────────────

def maybe_inject_design_phase(
    plan_steps: list[dict[str, Any]],
    cognitive_depth: float,
    is_brown_field: bool,
    task_description: str = "",
    force_design: bool = False,
    workspace_path: str = "",
) -> tuple[list[dict[str, Any]], list[DesignPhaseStep]]:
    """Full integration: load profile, compute steps, inject into plan.

    This is the single function to call from conductor_integration.py.

    Args:
        plan_steps: Original Conductor plan steps.
        cognitive_depth: Task cognitive depth.
        is_brown_field: Whether task modifies existing files.
        task_description: Task description.
        force_design: Override threshold.
        workspace_path: Path to workspace (for profile discovery).

    Returns:
        Tuple of (modified_plan_steps, injected_design_steps).
        If no injection needed, returns (original_steps, []).
    """
    # Try workspace-specific profile first
    profile = {}
    if workspace_path:
        ws_profile_path = Path(workspace_path) / "fde-profile.json"
        if ws_profile_path.exists():
            try:
                profile = json.loads(ws_profile_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

    if not profile:
        profile = load_fde_profile()

    if not profile:
        # No profile = no extensions enabled (backward compatible)
        return plan_steps, []

    design_steps = compute_design_steps(
        profile=profile,
        cognitive_depth=cognitive_depth,
        is_brown_field=is_brown_field,
        task_description=task_description,
        force_design=force_design,
    )

    if not design_steps:
        return plan_steps, []

    modified_plan = inject_design_steps_into_plan(plan_steps, design_steps)
    return modified_plan, design_steps
