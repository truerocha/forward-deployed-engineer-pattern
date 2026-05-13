"""
Synapse 2: Agent Harness Architecture Bundles (Wei 2026).

Validates that Conductor-generated WorkflowPlans maintain bundle coherence —
design decisions that empirically co-occur should not be split.

Academic source: Wei, H. (2026). Architectural Design Decisions in AI
                 Agent Harnesses. arXiv:2604.18071.

Priority: P1 (MEDIUM effort, MEDIUM impact — prevents architectural drift)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("fde.synapses.bundle")


@dataclass
class CoherenceViolation:
    """A single bundle coherence violation."""

    rule_name: str
    condition: str
    required: str
    actual: str
    severity: str  # "critical" | "warning"


@dataclass
class CoherenceAssessment:
    """Result of bundle coherence validation."""

    is_coherent: bool
    violations: list[CoherenceViolation] = field(default_factory=list)
    pattern_classification: str = ""
    organism_alignment: bool = True
    coherence_score: float = 1.0
    reasoning: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_coherent": self.is_coherent,
            "violations": [
                {"rule": v.rule_name, "condition": v.condition,
                 "required": v.required, "actual": v.actual, "severity": v.severity}
                for v in self.violations
            ],
            "pattern_classification": self.pattern_classification,
            "organism_alignment": self.organism_alignment,
            "coherence_score": round(self.coherence_score, 4),
            "reasoning": self.reasoning,
        }


class BundleCoherenceValidator:
    """Validates architectural bundle coherence in WorkflowPlans.

    Usage:
        validator = BundleCoherenceValidator()
        assessment = validator.validate(plan_metadata, organism_level="O4")
    """

    _COHERENCE_RULES: list[tuple[str, Any, str, Any, str, str]] = [
        ("agent_count", lambda v: v >= 3, "context_persistence", lambda v: v == "durable",
         "multi_agent_requires_durable_context", "critical"),
        ("tool_surface", lambda v: v == "broad", "safety_approval", lambda v: v == "policy_based",
         "broad_tools_require_policy_approval", "critical"),
        ("has_recursive", lambda v: v is True, "max_depth", lambda v: v is not None and v <= 2,
         "recursive_requires_depth_limit", "critical"),
        ("topology", lambda v: v == "debate", "has_arbiter", lambda v: v is True,
         "debate_requires_arbiter", "warning"),
        ("organism_level_num", lambda v: v >= 4, "has_verification", lambda v: v is True,
         "complex_tasks_require_verification", "warning"),
    ]

    _PATTERN_MAP = {
        "O1": "lightweight_tool",
        "O2": "balanced_cli_framework",
        "O3": "multi_agent_orchestrator",
        "O4": "multi_agent_orchestrator",
        "O5": "enterprise_full_featured",
    }

    _PATTERN_EXPECTED_AGENTS = {
        "lightweight_tool": (2, 3),
        "balanced_cli_framework": (3, 5),
        "multi_agent_orchestrator": (4, 8),
        "enterprise_full_featured": (6, 10),
    }

    def validate(self, plan_metadata: dict[str, Any], organism_level: str) -> CoherenceAssessment:
        """Validate bundle coherence of a WorkflowPlan."""
        violations: list[CoherenceViolation] = []

        organism_num = {"O1": 1, "O2": 2, "O3": 3, "O4": 4, "O5": 5}.get(organism_level, 3)
        enriched = {**plan_metadata, "organism_level_num": organism_num}

        for (cond_key, cond_check, req_key, req_check, rule_name, severity) in self._COHERENCE_RULES:
            cond_value = enriched.get(cond_key)
            if cond_value is not None and cond_check(cond_value):
                req_value = enriched.get(req_key)
                if req_value is None or not req_check(req_value):
                    violations.append(CoherenceViolation(
                        rule_name=rule_name,
                        condition=f"{cond_key}={cond_value}",
                        required=f"{req_key} must satisfy coherence rule",
                        actual=f"{req_key}={req_value}",
                        severity=severity,
                    ))

        pattern = self._PATTERN_MAP.get(organism_level, "multi_agent_orchestrator")
        agent_count = plan_metadata.get("agent_count", 3)
        expected_range = self._PATTERN_EXPECTED_AGENTS.get(pattern, (2, 8))
        organism_alignment = expected_range[0] <= agent_count <= expected_range[1]

        if not organism_alignment:
            violations.append(CoherenceViolation(
                rule_name="organism_agent_count_alignment",
                condition=f"organism={organism_level} (pattern={pattern})",
                required=f"agent_count in [{expected_range[0]}, {expected_range[1]}]",
                actual=f"agent_count={agent_count}",
                severity="warning",
            ))

        critical_violations = sum(1 for v in violations if v.severity == "critical")
        warning_violations = sum(1 for v in violations if v.severity == "warning")
        coherence_score = max(0.0, 1.0 - (critical_violations * 0.3) - (warning_violations * 0.1))
        is_coherent = critical_violations == 0

        if violations:
            reasoning = "Bundle violations: " + "; ".join(f"{v.rule_name} ({v.severity})" for v in violations)
        else:
            reasoning = f"Plan is coherent with {pattern} pattern for {organism_level}"

        assessment = CoherenceAssessment(
            is_coherent=is_coherent, violations=violations,
            pattern_classification=pattern, organism_alignment=organism_alignment,
            coherence_score=coherence_score, reasoning=reasoning,
        )

        logger.info("Bundle coherence: coherent=%s violations=%d pattern=%s", is_coherent, len(violations), pattern)
        return assessment

    def extract_plan_metadata(
        self, topology: str, steps: list[dict[str, Any]],
        organism_level: str, has_recursive: bool = False, max_depth: int | None = 2,
    ) -> dict[str, Any]:
        """Extract metadata from a WorkflowPlan for validation."""
        agent_count = len(steps)
        has_arbiter = any(
            "arbiter" in s.get("agent_role", "").lower()
            or "select" in s.get("subtask", "").lower()
            or "evaluate" in s.get("subtask", "").lower()
            for s in steps
        )
        has_verification = any(
            "valid" in s.get("subtask", "").lower()
            or "review" in s.get("subtask", "").lower()
            or "fidelity" in s.get("agent_role", "").lower()
            for s in steps
        )

        context_persistence = "durable" if agent_count >= 3 else "ephemeral"
        broad_roles = {"swe-developer-agent", "swe-architect-agent"}
        tool_surface = "broad" if any(s.get("agent_role", "") in broad_roles for s in steps) else "standard"

        return {
            "topology": topology,
            "agent_count": agent_count,
            "has_recursive": has_recursive,
            "context_persistence": context_persistence,
            "safety_approval": "policy_based",
            "tool_surface": tool_surface,
            "max_depth": max_depth,
            "has_arbiter": has_arbiter,
            "has_verification": has_verification,
        }
