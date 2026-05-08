#!/usr/bin/env python3
"""
CLI entrypoint for the Branch Evaluation Agent.

Usage:
    python3 scripts/evaluate_branch.py --base main --head feature/GH-42
    python3 scripts/evaluate_branch.py --base main  # uses current branch as head

Exit codes:
    0 — PASS or CONDITIONAL_PASS (merge eligible)
    1 — CONDITIONAL_FAIL or FAIL (merge blocked)

Design ref: docs/design/branch-evaluation-agent.md Section 10
"""

import argparse
import logging
import sys
from pathlib import Path

# Ensure the infra/docker directory is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "infra" / "docker"))

from agents.branch_evaluation.branch_evaluator import EvaluationConfig, evaluate_branch


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Branch Evaluation Agent — Automated quality gate for merge readiness.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/evaluate_branch.py --base main --head feature/GH-42
  python3 scripts/evaluate_branch.py --base main
  python3 scripts/evaluate_branch.py --base main --output report.json --pr-comment comment.md
  python3 scripts/evaluate_branch.py --base main --level 2 --ci-green
        """,
    )
    parser.add_argument(
        "--base", default="main",
        help="Base branch to diff against (default: main)",
    )
    parser.add_argument(
        "--head", default="",
        help="Head branch to evaluate (default: current branch)",
    )
    parser.add_argument(
        "--output", default="evaluation_report.json",
        help="Path for JSON report output (default: evaluation_report.json)",
    )
    parser.add_argument(
        "--pr-comment", default="evaluation_comment.md",
        help="Path for markdown PR comment output (default: evaluation_comment.md)",
    )
    parser.add_argument(
        "--level", type=int, default=3, choices=[1, 2, 3, 4, 5],
        help="Engineering level override (default: 3, auto-detected from branch name)",
    )
    parser.add_argument(
        "--ci-green", action="store_true", default=True,
        help="Indicate CI checks are green (default: True)",
    )
    parser.add_argument(
        "--no-ci-green", action="store_true",
        help="Indicate CI checks are NOT green",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true",
        help="Suppress all output except the final verdict line",
    )
    return parser.parse_args()


def main() -> int:
    """Run branch evaluation and return exit code."""
    args = parse_args()

    # Configure logging
    if args.quiet:
        log_level = logging.CRITICAL
    elif args.verbose:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    ci_green = not args.no_ci_green

    config = EvaluationConfig(
        base=args.base,
        head=args.head,
        engineering_level=args.level,
        ci_green=ci_green,
        json_output=args.output,
        markdown_output=args.pr_comment,
    )

    logger = logging.getLogger("evaluate_branch")
    logger.info("Branch Evaluation Agent starting...")
    logger.info("Config: base=%s, head=%s, level=L%d, ci_green=%s",
                config.base, config.head or "(current)", config.engineering_level, ci_green)

    # Run evaluation
    result = evaluate_branch(config)

    # Print summary
    verdict = result.verdict
    print(f"\n{'='*60}")
    print(f"  Branch Evaluation: {result.branch} -> {result.base}")
    print(f"  Verdict: {verdict.verdict} ({verdict.aggregate_score:.2f}/10)")
    print(f"  Merge eligible: {verdict.merge_eligible}")
    print(f"  Auto-merge eligible: {verdict.auto_merge_eligible}")
    if verdict.veto_triggered:
        print(f"  Veto: {verdict.veto_reason}")
    print(f"  Files evaluated: {len(result.classified_files)}")
    print(f"  Pipeline edges: {', '.join(result.pipeline_edges) or 'none'}")
    print(f"  Reports: {result.json_report_path}, {result.markdown_report_path}")
    print(f"{'='*60}\n")

    # Print dimension scores
    if not args.quiet:
        print("  Dimension Scores:")
        for d in verdict.dimensions:
            name = d.name.replace("_", " ").title()
            bar_filled = int(d.score)
            bar_empty = 10 - bar_filled
            bar = "#" * bar_filled + "." * bar_empty
            print(f"    {name:<25} [{bar}] {d.score:.1f}/10 (w={d.weight:.0%})")
            for issue in d.issues[:3]:
                print(f"      ! {issue[:100]}")
        print()

    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
