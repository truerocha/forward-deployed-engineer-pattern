"""
Report Renderer — Generates evaluation reports in markdown and JSON formats.

Produces:
1. PR comment (markdown) with score breakdown, observations, and verdict
2. Machine-readable JSON report for CI/CD integration and metrics

Design ref: docs/design/branch-evaluation-agent.md Section 9
"""

import json
import logging
from datetime import datetime, timezone

from .scoring_engine import DimensionScore, EvaluationVerdict

logger = logging.getLogger("fde.branch_evaluation.report_renderer")

VERDICT_EMOJI = {
    "PASS": "\U0001f7e2",
    "CONDITIONAL_PASS": "\U0001f7e1",
    "CONDITIONAL_FAIL": "\U0001f7e0",
    "FAIL": "\U0001f534",
}


def render_markdown_report(
    verdict: EvaluationVerdict,
    branch: str,
    base: str,
    files_evaluated: int,
    pipeline_edges: list[str],
    evaluated_at: str | None = None,
) -> str:
    """Generate the PR comment markdown report."""
    ts = evaluated_at or datetime.now(timezone.utc).isoformat()
    emoji = VERDICT_EMOJI.get(verdict.verdict, "\u26aa")

    lines = [
        "## \U0001f50d Branch Evaluation Report\n",
        f"**Branch**: `{branch}`",
        f"**Base**: `{base}`",
        f"**Evaluated**: {ts}",
        f"**Verdict**: {emoji} {verdict.verdict} ({verdict.aggregate_score:.1f}/10)",
        f"**Merge eligible**: {'Yes' if verdict.merge_eligible else 'No'}",
        f"**Auto-merge eligible**: {'Yes' if verdict.auto_merge_eligible else 'No'}\n",
        "### Score Breakdown\n",
        "| Dimension | Score | Weight | Weighted |",
        "|-----------|-------|--------|----------|",
    ]

    for d in verdict.dimensions:
        name_display = d.name.replace("_", " ").title()
        lines.append(f"| {name_display} | {d.score:.1f}/10 | {d.weight*100:.0f}% | {d.weighted:.2f} |")

    lines.append(f"| **Aggregate** | | | **{verdict.aggregate_score:.2f}** |")

    if pipeline_edges:
        lines.append(f"\n### Pipeline Edges Affected\n")
        lines.append(f"Edges: {', '.join(pipeline_edges)}")

    all_issues = [(d.name, issue) for d in verdict.dimensions for issue in d.issues]
    if all_issues:
        lines.append("\n### Observations\n")
        for dim_name, issue in all_issues[:15]:
            dim_display = dim_name.replace("_", " ").title()
            lines.append(f"- \u26a0\ufe0f **{dim_display}**: {issue}")

    if verdict.veto_triggered:
        lines.append(f"\n### \u26d4 Veto Triggered\n")
        lines.append(f"{verdict.veto_reason}")

    if verdict.auto_merge_eligible:
        lines.append("\n### \u2705 Auto-Merge\n")
        lines.append("This branch meets auto-merge criteria (score \u2265 8.0, L1/L2, CI green).")
        lines.append("Merging automatically.")

    lines.append(f"\n---")
    lines.append(f"*Files evaluated: {files_evaluated} | Evaluated by Branch Evaluation Agent (FDE Protocol)*")

    return "\n".join(lines)


def render_json_report(
    verdict: EvaluationVerdict,
    branch: str,
    base: str,
    files_evaluated: int,
    pipeline_edges: list[str],
    changed_files: list[dict] | None = None,
    evaluated_at: str | None = None,
) -> dict:
    """Generate the machine-readable JSON evaluation report."""
    ts = evaluated_at or datetime.now(timezone.utc).isoformat()

    report = {
        "evaluation_id": f"eval-{ts.replace(':', '').replace('-', '')[:15]}",
        "branch": branch,
        "base": base,
        "evaluated_at": ts,
        "verdict": verdict.verdict,
        "aggregate_score": verdict.aggregate_score,
        "merge_eligible": verdict.merge_eligible,
        "auto_merge_eligible": verdict.auto_merge_eligible,
        "veto_triggered": verdict.veto_triggered,
        "veto_reason": verdict.veto_reason,
        "dimensions": verdict.to_dict()["dimensions"],
        "pipeline_edges_affected": pipeline_edges,
        "files_evaluated": files_evaluated,
    }

    if changed_files:
        report["files"] = changed_files

    return report


def write_reports(
    verdict: EvaluationVerdict,
    branch: str,
    base: str,
    files_evaluated: int,
    pipeline_edges: list[str],
    changed_files: list[dict] | None = None,
    json_path: str = "evaluation_report.json",
    markdown_path: str = "evaluation_comment.md",
) -> tuple[str, str]:
    """Write both report formats to disk."""
    ts = datetime.now(timezone.utc).isoformat()

    json_report = render_json_report(
        verdict, branch, base, files_evaluated, pipeline_edges, changed_files, ts,
    )
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_report, f, indent=2, default=str)
    logger.info("JSON report written to: %s", json_path)

    md_report = render_markdown_report(
        verdict, branch, base, files_evaluated, pipeline_edges, ts,
    )
    with open(markdown_path, "w", encoding="utf-8") as f:
        f.write(md_report)
    logger.info("Markdown report written to: %s", markdown_path)

    return json_path, markdown_path
