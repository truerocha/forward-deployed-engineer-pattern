"""
Synapse 1: Deep Module Principle (Ousterhout/APOSD).

Measures and enforces the depth of module interfaces — the ratio of
public interface surface to internal implementation complexity.

Deep modules (simple interface, rich implementation) reduce risk.
Shallow modules (complex interface, thin implementation) increase risk.

Academic source: Ousterhout, J. (2018). A Philosophy of Software Design.

Priority: P1 (MEDIUM effort, HIGH impact — improves agent quality)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("fde.synapses.depth")


@dataclass
class DepthAssessment:
    """Result of interface depth analysis."""

    interface_depth_ratio: float
    module_depth_scores: dict[str, float] = field(default_factory=dict)
    shallow_modules: list[str] = field(default_factory=list)
    entangled_pairs: list[tuple[str, str]] = field(default_factory=list)
    agent_instruction_quality: float = 0.0
    reasoning: str = ""

    @property
    def depth_signal(self) -> float:
        """Normalized signal for Risk Engine (signal #14). Weight: -1.2 (protective)."""
        return self.interface_depth_ratio

    def to_dict(self) -> dict[str, Any]:
        return {
            "interface_depth_ratio": round(self.interface_depth_ratio, 4),
            "depth_signal": round(self.depth_signal, 4),
            "module_depth_scores": {k: round(v, 4) for k, v in self.module_depth_scores.items()},
            "shallow_modules": self.shallow_modules,
            "entangled_pairs": self.entangled_pairs,
            "agent_instruction_quality": round(self.agent_instruction_quality, 4),
            "reasoning": self.reasoning,
        }


class InterfaceDepthAnalyzer:
    """Analyzes module depth and agent instruction quality.

    Usage:
        analyzer = InterfaceDepthAnalyzer()
        assessment = analyzer.analyze_catalog(catalog_metadata)
        assessment = analyzer.analyze_agent_plan(workflow_steps)
    """

    _SHALLOW_THRESHOLD = 0.3
    _ENTANGLEMENT_SCD_THRESHOLD = 3
    _DEEP_INSTRUCTION_MIN_WORDS = 8
    _SHALLOW_INSTRUCTION_KEYWORDS = [
        "read file", "check if", "then modify", "run command",
        "copy paste", "line by line", "step by step",
    ]

    def analyze_catalog(self, catalog_metadata: dict[str, Any]) -> DepthAssessment:
        """Analyze module depth from onboarding catalog metadata."""
        modules = catalog_metadata.get("modules", {})
        if not modules:
            return self._analyze_from_aggregates(catalog_metadata)

        module_scores: dict[str, float] = {}
        shallow_modules: list[str] = []

        for module_name, metrics in modules.items():
            public_methods = metrics.get("public_methods", 1)
            total_lines = metrics.get("total_lines", 100)
            complexity = metrics.get("complexity_avg", 5)

            lines_per_method = total_lines / max(public_methods, 1)
            depth_from_size = min(1.0, lines_per_method / 50.0)
            depth_from_complexity = min(1.0, complexity / 15.0)

            depth_score = depth_from_size * 0.6 + depth_from_complexity * 0.4
            module_scores[module_name] = depth_score

            if depth_score < self._SHALLOW_THRESHOLD:
                shallow_modules.append(module_name)

        avg_depth = sum(module_scores.values()) / len(module_scores) if module_scores else 0.5

        reasoning_parts = []
        if shallow_modules:
            reasoning_parts.append(f"{len(shallow_modules)} shallow modules: {', '.join(shallow_modules[:3])}")
        reasoning_parts.append(f"Average depth: {avg_depth:.2f} across {len(module_scores)} modules")

        return DepthAssessment(
            interface_depth_ratio=avg_depth,
            module_depth_scores=module_scores,
            shallow_modules=shallow_modules,
            reasoning=". ".join(reasoning_parts),
        )

    def analyze_agent_plan(
        self, steps: list[dict[str, Any]], scd_access_map: dict[str, list[str]] | None = None,
    ) -> DepthAssessment:
        """Analyze depth quality of a Conductor-generated WorkflowPlan."""
        instruction_scores: list[float] = []
        module_scores: dict[str, float] = {}

        for step in steps:
            subtask = step.get("subtask", "")
            role = step.get("agent_role", f"step-{step.get('step_index', 0)}")
            score = self._score_instruction_depth(subtask)
            instruction_scores.append(score)
            module_scores[role] = score

        entangled_pairs = self._detect_entanglement(scd_access_map or {})

        avg_instruction_quality = sum(instruction_scores) / max(len(instruction_scores), 1)
        shallow = [role for role, score in module_scores.items() if score < self._SHALLOW_THRESHOLD]

        entanglement_penalty = min(0.3, len(entangled_pairs) * 0.1)
        interface_depth_ratio = max(0.0, avg_instruction_quality - entanglement_penalty)

        reasoning_parts = []
        if shallow:
            reasoning_parts.append(f"{len(shallow)} agents have shallow instructions")
        if entangled_pairs:
            reasoning_parts.append(f"{len(entangled_pairs)} entangled pairs")
        reasoning_parts.append(f"Avg instruction depth: {avg_instruction_quality:.2f}")

        return DepthAssessment(
            interface_depth_ratio=interface_depth_ratio,
            module_depth_scores=module_scores,
            shallow_modules=shallow,
            entangled_pairs=entangled_pairs,
            agent_instruction_quality=avg_instruction_quality,
            reasoning=". ".join(reasoning_parts),
        )

    def _analyze_from_aggregates(self, catalog: dict[str, Any]) -> DepthAssessment:
        """Fallback when per-module data is unavailable."""
        complexity_avg = catalog.get("complexity_avg", 10)
        test_coverage = catalog.get("test_coverage_pct", 50)

        depth_from_complexity = min(1.0, complexity_avg / 15.0)
        depth_from_coverage = test_coverage / 100.0
        ratio = depth_from_complexity * 0.5 + depth_from_coverage * 0.5

        return DepthAssessment(
            interface_depth_ratio=ratio,
            reasoning=f"Aggregate: complexity={complexity_avg}, coverage={test_coverage}%",
        )

    def _score_instruction_depth(self, instruction: str) -> float:
        """Score how 'deep' an agent instruction is (WHAT vs HOW)."""
        if not instruction:
            return 0.0

        words = instruction.split()
        word_count = len(words)

        if word_count < self._DEEP_INSTRUCTION_MIN_WORDS:
            return 0.3

        instruction_lower = instruction.lower()
        shallow_hits = sum(1 for kw in self._SHALLOW_INSTRUCTION_KEYWORDS if kw in instruction_lower)

        deep_keywords = ["ensure", "validate", "produce", "generate", "design",
                         "implement", "analyze", "evaluate", "optimize", "review"]
        deep_hits = sum(1 for kw in deep_keywords if kw in instruction_lower)

        length_score = min(1.0, word_count / 30.0)
        keyword_adjustment = (deep_hits * 0.1) - (shallow_hits * 0.15)

        return max(0.0, min(1.0, length_score + keyword_adjustment))

    def _detect_entanglement(self, scd_access_map: dict[str, list[str]]) -> list[tuple[str, str]]:
        """Detect entangled agent pairs based on SCD field sharing."""
        if not scd_access_map:
            return []

        agents = list(scd_access_map.keys())
        entangled: list[tuple[str, str]] = []

        for i in range(len(agents)):
            for j in range(i + 1, len(agents)):
                fields_a = set(scd_access_map[agents[i]])
                fields_b = set(scd_access_map[agents[j]])
                shared = fields_a & fields_b
                if len(shared) > self._ENTANGLEMENT_SCD_THRESHOLD:
                    entangled.append((agents[i], agents[j]))

        return entangled
