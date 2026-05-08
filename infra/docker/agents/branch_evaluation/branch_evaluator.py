"""
Branch Evaluator — Core orchestrator for the Branch Evaluation Agent.

Orchestrates the full evaluation pipeline:
  git diff → classify → evaluate all 7 dimensions → score → report

Entry point for both CLI (scripts/evaluate_branch.py) and ECS execution.

Design ref: docs/design/branch-evaluation-agent.md Section 10.1
"""

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .artifact_classifier import ClassifiedFile, classify_files, get_affected_pipeline_edges
from .code_evaluator import (
    evaluate_backward_compatibility,
    evaluate_convention_compliance,
    evaluate_documentation,
    evaluate_structural_validity,
    evaluate_test_coverage,
)
from .domain_evaluator import evaluate_adversarial_resilience, evaluate_domain_alignment
from .pipeline_graph import compute_regression_surface, find_affected_edges
from .report_renderer import render_json_report, render_markdown_report, write_reports
from .scoring_engine import DimensionScore, EvaluationVerdict, produce_verdict

logger = logging.getLogger("fde.branch_evaluation.orchestrator")


# ─── Configuration ──────────────────────────────────────────────────────────

@dataclass
class EvaluationConfig:
    """Configuration for a branch evaluation run."""

    base: str = "main"
    head: str = ""
    engineering_level: int = 3
    ci_green: bool = True
    json_output: str = "evaluation_report.json"
    markdown_output: str = "evaluation_comment.md"
    repo_root: str = "."


# ─── Git Operations ─────────────────────────────────────────────────────────

def _get_current_branch() -> str:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "unknown"


def _get_changed_files(base: str, head: str) -> list[tuple[str, str]]:
    """Get list of changed files between base and head with their status.

    Args:
        base: Base branch/ref (e.g., 'main').
        head: Head branch/ref (e.g., 'feature/GH-42').

    Returns:
        List of (status, filepath) tuples.
        Status is one of: added, modified, deleted, renamed.
    """
    # Use merge-base for accurate diff
    try:
        merge_base_result = subprocess.run(
            ["git", "merge-base", base, head],
            capture_output=True, text=True, timeout=10,
        )
        if merge_base_result.returncode == 0:
            merge_base = merge_base_result.stdout.strip()
        else:
            merge_base = base
    except (subprocess.TimeoutExpired, FileNotFoundError):
        merge_base = base

    try:
        result = subprocess.run(
            ["git", "diff", "--name-status", merge_base, head],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            # Fallback: diff against base directly
            result = subprocess.run(
                ["git", "diff", "--name-status", f"{base}...{head}"],
                capture_output=True, text=True, timeout=30,
            )
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        logger.error("Git diff failed: %s", e)
        return []

    if result.returncode != 0:
        logger.error("Git diff failed: %s", result.stderr.strip())
        return []

    STATUS_MAP = {
        "A": "added",
        "M": "modified",
        "D": "deleted",
        "R": "renamed",
    }

    changed: list[tuple[str, str]] = []
    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("\t")
        if len(parts) >= 2:
            raw_status = parts[0][0]  # First char (R100 → R)
            filepath = parts[-1]  # Last part (for renames, this is the new path)
            status = STATUS_MAP.get(raw_status, "modified")
            changed.append((status, filepath))

    logger.info("Found %d changed files between %s and %s", len(changed), base, head)
    return changed


def _detect_engineering_level(branch: str) -> int:
    """Attempt to detect engineering level from branch name or labels.

    Convention: branch names like feature/GH-42-level-2-... or labels.
    Default: L3 (requires human review).

    Args:
        branch: Branch name.

    Returns:
        Engineering level (1-5).
    """
    import re

    # Check branch name for level indicator
    level_match = re.search(r'level[- ]?(\d)', branch, re.IGNORECASE)
    if level_match:
        level = int(level_match.group(1))
        if 1 <= level <= 5:
            return level

    # Check for L1/L2 indicators
    l_match = re.search(r'\bL([12345])\b', branch)
    if l_match:
        return int(l_match.group(1))

    # Default to L3 (human review required)
    return 3


# ─── Orchestrator ───────────────────────────────────────────────────────────

@dataclass
class EvaluationResult:
    """Complete result of a branch evaluation."""

    verdict: EvaluationVerdict
    classified_files: list[ClassifiedFile]
    pipeline_edges: list[str]
    regression_surface: list[str]
    json_report_path: str = ""
    markdown_report_path: str = ""
    branch: str = ""
    base: str = ""

    @property
    def exit_code(self) -> int:
        """Return CLI exit code based on verdict.

        0 = PASS or CONDITIONAL_PASS (merge eligible)
        1 = CONDITIONAL_FAIL or FAIL (merge blocked)
        """
        return 0 if self.verdict.merge_eligible else 1


def evaluate_branch(config: EvaluationConfig) -> EvaluationResult:
    """Run the full branch evaluation pipeline.

    Pipeline:
    1. Determine head branch (current if not specified)
    2. Compute git diff (base...head)
    3. Classify all changed files by artifact type
    4. Evaluate all 7 dimensions
    5. Produce verdict (aggregate score + veto check)
    6. Render reports (markdown + JSON)

    Args:
        config: Evaluation configuration.

    Returns:
        EvaluationResult with verdict, files, and report paths.
    """
    # Step 1: Determine branches
    head = config.head or _get_current_branch()
    base = config.base
    logger.info("Evaluating branch: %s against %s", head, base)

    # Step 2: Get changed files
    changed_files = _get_changed_files(base, head)
    if not changed_files:
        logger.warning("No changed files found. Producing default PASS verdict.")
        empty_verdict = produce_verdict([], config.engineering_level, config.ci_green)
        return EvaluationResult(
            verdict=empty_verdict,
            classified_files=[],
            pipeline_edges=[],
            regression_surface=[],
            branch=head,
            base=base,
        )

    # Step 3: Classify files
    classified = classify_files(changed_files)
    logger.info("Classified %d files", len(classified))

    # Step 4: Determine pipeline edges and regression surface
    pipeline_edges = get_affected_pipeline_edges(classified)
    changed_paths = [f.path for f in classified if f.status != "deleted"]
    regression_surface = compute_regression_surface(changed_paths)
    logger.info("Pipeline edges affected: %s", pipeline_edges)
    logger.info("Regression surface: %d tests", len(regression_surface))

    # Step 5: Detect engineering level
    engineering_level = config.engineering_level
    if engineering_level == 3:  # Default — try to detect
        detected = _detect_engineering_level(head)
        if detected != 3:
            engineering_level = detected
            logger.info("Detected engineering level: L%d", engineering_level)

    # Step 6: Evaluate all 7 dimensions
    dimensions: list[DimensionScore] = []

    logger.info("Evaluating D1: Structural Validity...")
    dimensions.append(evaluate_structural_validity(classified))

    logger.info("Evaluating D2: Convention Compliance...")
    dimensions.append(evaluate_convention_compliance(classified))

    logger.info("Evaluating D3: Backward Compatibility...")
    dimensions.append(evaluate_backward_compatibility(classified))

    logger.info("Evaluating D4: Domain Alignment...")
    dimensions.append(evaluate_domain_alignment(classified))

    logger.info("Evaluating D5: Test Coverage...")
    dimensions.append(evaluate_test_coverage(classified))

    logger.info("Evaluating D6: Adversarial Resilience...")
    dimensions.append(evaluate_adversarial_resilience(classified))

    logger.info("Evaluating D7: Documentation...")
    dimensions.append(evaluate_documentation(classified))

    # Step 7: Produce verdict
    verdict = produce_verdict(dimensions, engineering_level, config.ci_green)
    logger.info(
        "Verdict: %s (score=%.2f, merge=%s, auto_merge=%s)",
        verdict.verdict, verdict.aggregate_score,
        verdict.merge_eligible, verdict.auto_merge_eligible,
    )

    # Step 8: Render reports
    changed_file_dicts = [
        {"path": f.path, "type": f.artifact_type, "status": f.status}
        for f in classified
    ]

    json_path, md_path = write_reports(
        verdict=verdict,
        branch=head,
        base=base,
        files_evaluated=len(classified),
        pipeline_edges=pipeline_edges,
        changed_files=changed_file_dicts,
        json_path=config.json_output,
        markdown_path=config.markdown_output,
    )

    return EvaluationResult(
        verdict=verdict,
        classified_files=classified,
        pipeline_edges=pipeline_edges,
        regression_surface=regression_surface,
        json_report_path=json_path,
        markdown_report_path=md_path,
        branch=head,
        base=base,
    )
