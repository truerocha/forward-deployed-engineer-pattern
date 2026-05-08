"""
Scoring Engine — Computes dimension scores, aggregate, and verdict.

Implements the weighted scoring model from Section 5 of the design doc.
Supports configurable weights, thresholds, and veto rules.

Design ref: docs/design/branch-evaluation-agent.md Section 5
"""

import logging
from dataclasses import dataclass, field

logger = logging.getLogger("fde.branch_evaluation.scoring")


# ─── Configuration ──────────────────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    "structural_validity": 0.20,
    "convention_compliance": 0.15,
    "backward_compatibility": 0.20,
    "domain_alignment": 0.15,
    "test_coverage": 0.15,
    "adversarial_resilience": 0.10,
    "documentation": 0.05,
}

DEFAULT_THRESHOLDS = {
    "pass": 8.0,
    "conditional_pass": 7.0,
    "conditional_fail": 5.0,
}

DEFAULT_VETO_RULES = {
    "structural_validity": 3.0,
    "backward_compatibility": 3.0,
    "domain_alignment": 3.0,
}

# Verdicts in order of severity
VERDICT_PASS = "PASS"
VERDICT_CONDITIONAL_PASS = "CONDITIONAL_PASS"
VERDICT_CONDITIONAL_FAIL = "CONDITIONAL_FAIL"
VERDICT_FAIL = "FAIL"


# ─── Data Structures ────────────────────────────────────────────────────────

@dataclass
class DimensionScore:
    """Score for a single evaluation dimension."""

    name: str
    score: float  # 0.0 - 10.0
    weight: float
    issues: list[str] = field(default_factory=list)
    details: dict = field(default_factory=dict)

    @property
    def weighted(self) -> float:
        """Compute weighted contribution to aggregate."""
        return self.score * self.weight

    def to_dict(self) -> dict:
        """Serialize for JSON output."""
        return {
            "score": round(self.score, 2),
            "weight": self.weight,
            "weighted": round(self.weighted, 2),
            "issues": self.issues,
            "details": self.details,
        }


@dataclass
class EvaluationVerdict:
    """Final evaluation verdict with all supporting data."""

    verdict: str
    aggregate_score: float
    dimensions: list[DimensionScore]
    veto_triggered: bool = False
    veto_reason: str = ""
    merge_eligible: bool = False
    auto_merge_eligible: bool = False

    def to_dict(self) -> dict:
        """Serialize for JSON output."""
        return {
            "verdict": self.verdict,
            "aggregate_score": round(self.aggregate_score, 2),
            "dimensions": {d.name: d.to_dict() for d in self.dimensions},
            "veto_triggered": self.veto_triggered,
            "veto_reason": self.veto_reason,
            "merge_eligible": self.merge_eligible,
            "auto_merge_eligible": self.auto_merge_eligible,
        }


# ─── Scoring Functions ──────────────────────────────────────────────────────

def compute_aggregate(dimensions: list[DimensionScore]) -> float:
    """Compute weighted aggregate score from dimension scores.

    Args:
        dimensions: List of scored dimensions.

    Returns:
        Weighted aggregate score (0.0 - 10.0).
    """
    total = sum(d.weighted for d in dimensions)
    return round(total, 2)


def check_veto_rules(
    dimensions: list[DimensionScore],
    veto_rules: dict[str, float] | None = None,
) -> tuple[bool, str]:
    """Check if any veto rule is triggered.

    Veto rules override the aggregate score — if any dimension scores
    below its veto threshold, the verdict is FAIL regardless of aggregate.

    Args:
        dimensions: List of scored dimensions.
        veto_rules: Dict of dimension_name → minimum_score. Defaults to DEFAULT_VETO_RULES.

    Returns:
        Tuple of (veto_triggered: bool, reason: str).
    """
    rules = veto_rules or DEFAULT_VETO_RULES

    for d in dimensions:
        threshold = rules.get(d.name)
        if threshold is not None and d.score < threshold:
            reason = (
                f"Veto triggered: {d.name} scored {d.score:.1f} "
                f"(below minimum threshold {threshold:.1f}). "
                f"Issues: {'; '.join(d.issues[:3])}"
            )
            logger.warning(reason)
            return True, reason

    return False, ""


def determine_verdict(
    aggregate: float,
    veto_triggered: bool,
    thresholds: dict[str, float] | None = None,
) -> str:
    """Determine the evaluation verdict based on score and veto status.

    Args:
        aggregate: Weighted aggregate score (0-10).
        veto_triggered: Whether a veto rule was triggered.
        thresholds: Score thresholds for each verdict level.

    Returns:
        Verdict string (PASS, CONDITIONAL_PASS, CONDITIONAL_FAIL, FAIL).
    """
    if veto_triggered:
        return VERDICT_FAIL

    t = thresholds or DEFAULT_THRESHOLDS

    if aggregate >= t["pass"]:
        return VERDICT_PASS
    elif aggregate >= t["conditional_pass"]:
        return VERDICT_CONDITIONAL_PASS
    elif aggregate >= t["conditional_fail"]:
        return VERDICT_CONDITIONAL_FAIL
    else:
        return VERDICT_FAIL


def check_auto_merge_eligibility(
    verdict: str,
    aggregate: float,
    engineering_level: int = 3,
    ci_green: bool = True,
    max_auto_merge_level: int = 2,
    min_auto_merge_score: float = 8.0,
) -> bool:
    """Determine if the branch is eligible for auto-merge.

    Auto-merge requires:
    - Score >= min_auto_merge_score (default 8.0)
    - Engineering level <= max_auto_merge_level (default L2)
    - All CI checks green
    - No veto rules triggered (implied by verdict = PASS)

    Args:
        verdict: The evaluation verdict.
        aggregate: The aggregate score.
        engineering_level: The task's engineering level (1-5).
        ci_green: Whether all CI checks passed.
        max_auto_merge_level: Maximum level for auto-merge (default 2).
        min_auto_merge_score: Minimum score for auto-merge (default 8.0).

    Returns:
        True if auto-merge is eligible.
    """
    if verdict != VERDICT_PASS:
        return False
    if aggregate < min_auto_merge_score:
        return False
    if engineering_level > max_auto_merge_level:
        return False
    if not ci_green:
        return False
    return True


def produce_verdict(
    dimensions: list[DimensionScore],
    engineering_level: int = 3,
    ci_green: bool = True,
    weights: dict[str, float] | None = None,
    thresholds: dict[str, float] | None = None,
    veto_rules: dict[str, float] | None = None,
) -> EvaluationVerdict:
    """Produce the final evaluation verdict from dimension scores.

    This is the main entry point for the scoring engine. It:
    1. Computes the weighted aggregate
    2. Checks veto rules
    3. Determines the verdict
    4. Checks merge and auto-merge eligibility

    Args:
        dimensions: List of scored dimensions.
        engineering_level: Task engineering level (1-5).
        ci_green: Whether CI checks passed.
        weights: Optional custom weights (overrides dimension weights).
        thresholds: Optional custom thresholds.
        veto_rules: Optional custom veto rules.

    Returns:
        EvaluationVerdict with all scoring data.
    """
    # Apply custom weights if provided
    if weights:
        for d in dimensions:
            if d.name in weights:
                d.weight = weights[d.name]

    # Compute aggregate
    aggregate = compute_aggregate(dimensions)

    # Check veto rules
    veto_triggered, veto_reason = check_veto_rules(dimensions, veto_rules)

    # Determine verdict
    verdict = determine_verdict(aggregate, veto_triggered, thresholds)

    # Check merge eligibility
    merge_eligible = verdict in (VERDICT_PASS, VERDICT_CONDITIONAL_PASS)
    auto_merge_eligible = check_auto_merge_eligibility(
        verdict, aggregate, engineering_level, ci_green,
    )

    logger.info(
        "Verdict: %s (score=%.2f, veto=%s, merge=%s, auto_merge=%s)",
        verdict, aggregate, veto_triggered, merge_eligible, auto_merge_eligible,
    )

    return EvaluationVerdict(
        verdict=verdict,
        aggregate_score=aggregate,
        dimensions=dimensions,
        veto_triggered=veto_triggered,
        veto_reason=veto_reason,
        merge_eligible=merge_eligible,
        auto_merge_eligible=auto_merge_eligible,
    )
