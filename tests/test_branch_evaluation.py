"""
Integration tests for the Branch Evaluation Agent.

Verifies the full pipeline: classify -> evaluate -> score -> verdict -> report.
Tests run against the actual repo state (this repo is the test fixture).

Design ref: docs/design/branch-evaluation-agent.md
"""

import json
import sys
from pathlib import Path

import pytest

# Add the agents directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "infra" / "docker"))

from agents.branch_evaluation.artifact_classifier import (
    classify_file,
    classify_files,
    get_affected_pipeline_edges,
    ClassifiedFile,
)
from agents.branch_evaluation.scoring_engine import (
    DimensionScore,
    EvaluationVerdict,
    compute_aggregate,
    check_veto_rules,
    determine_verdict,
    check_auto_merge_eligibility,
    produce_verdict,
    DEFAULT_WEIGHTS,
    VERDICT_PASS,
    VERDICT_CONDITIONAL_PASS,
    VERDICT_CONDITIONAL_FAIL,
    VERDICT_FAIL,
)
from agents.branch_evaluation.code_evaluator import (
    evaluate_structural_validity,
    evaluate_convention_compliance,
    evaluate_backward_compatibility,
    evaluate_test_coverage,
    evaluate_documentation,
)
from agents.branch_evaluation.domain_evaluator import (
    evaluate_domain_alignment,
    evaluate_adversarial_resilience,
)
from agents.branch_evaluation.report_renderer import (
    render_markdown_report,
    render_json_report,
)


class TestArtifactClassifier:
    """Tests for file classification logic."""

    def test_classify_python_agent_as_code(self):
        assert classify_file("infra/docker/agents/orchestrator.py") == "code"

    def test_classify_script_as_code(self):
        assert classify_file("scripts/evaluate_branch.py") == "code"

    def test_classify_terraform_as_infrastructure(self):
        assert classify_file("infra/terraform/eventbridge.tf") == "infrastructure"

    def test_classify_dockerfile_as_infrastructure(self):
        assert classify_file("infra/docker/Dockerfile.strands-agent") == "infrastructure"

    def test_classify_hook_as_hook(self):
        assert classify_file(".kiro/hooks/fde-adversarial-gate.kiro.hook") == "hook"

    def test_classify_adr_as_documentation(self):
        assert classify_file("docs/adr/ADR-018-branch-evaluation-agent.md") == "documentation"

    def test_classify_readme_as_documentation(self):
        assert classify_file("README.md") == "documentation"

    def test_classify_steering_as_knowledge(self):
        assert classify_file(".kiro/steering/fde.md") == "knowledge"

    def test_classify_test_as_test(self):
        assert classify_file("tests/test_branch_evaluation.py") == "test"

    def test_classify_portal_src_as_portal(self):
        assert classify_file("infra/portal-src/src/App.tsx") == "portal"

    def test_classify_unknown_as_other(self):
        assert classify_file("random_file.xyz") == "other"

    def test_classify_files_returns_classified_list(self):
        changed = [
            ("added", "infra/docker/agents/new_module.py"),
            ("modified", "README.md"),
            ("deleted", "tests/old_test.py"),
        ]
        result = classify_files(changed)
        assert len(result) == 3
        assert result[0].artifact_type == "code"
        assert result[1].artifact_type == "documentation"
        assert result[2].artifact_type == "test"

    def test_pipeline_edges_for_orchestrator(self):
        files = [ClassifiedFile(path="infra/docker/agents/orchestrator.py", artifact_type="code", status="modified")]
        edges = get_affected_pipeline_edges(files)
        assert "E1" in edges

    def test_pipeline_edges_for_portal(self):
        files = [ClassifiedFile(path="infra/portal-src/src/App.tsx", artifact_type="portal", status="modified")]
        edges = get_affected_pipeline_edges(files)
        assert "E6" in edges


class TestScoringEngine:
    """Tests for the scoring engine logic."""

    def _make_dimensions(self, scores: dict) -> list:
        return [DimensionScore(name=n, score=s, weight=DEFAULT_WEIGHTS[n]) for n, s in scores.items()]

    def test_compute_aggregate_perfect(self):
        dims = self._make_dimensions({k: 10.0 for k in DEFAULT_WEIGHTS})
        assert compute_aggregate(dims) == 10.0

    def test_compute_aggregate_zero(self):
        dims = self._make_dimensions({k: 0.0 for k in DEFAULT_WEIGHTS})
        assert compute_aggregate(dims) == 0.0

    def test_veto_triggered_on_low_structural(self):
        dims = self._make_dimensions({k: 10.0 for k in DEFAULT_WEIGHTS})
        dims[0] = DimensionScore("structural_validity", 2.0, 0.20)
        triggered, reason = check_veto_rules(dims)
        assert triggered is True
        assert "structural_validity" in reason

    def test_veto_not_triggered_on_acceptable(self):
        dims = self._make_dimensions({k: 8.0 for k in DEFAULT_WEIGHTS})
        triggered, _ = check_veto_rules(dims)
        assert triggered is False

    def test_verdict_pass(self):
        assert determine_verdict(8.5, False) == VERDICT_PASS

    def test_verdict_conditional_pass(self):
        assert determine_verdict(7.5, False) == VERDICT_CONDITIONAL_PASS

    def test_verdict_conditional_fail(self):
        assert determine_verdict(6.0, False) == VERDICT_CONDITIONAL_FAIL

    def test_verdict_fail_low_score(self):
        assert determine_verdict(4.0, False) == VERDICT_FAIL

    def test_verdict_fail_on_veto(self):
        assert determine_verdict(9.5, True) == VERDICT_FAIL

    def test_auto_merge_eligible_l1(self):
        assert check_auto_merge_eligibility("PASS", 8.5, engineering_level=1) is True

    def test_auto_merge_eligible_l2(self):
        assert check_auto_merge_eligibility("PASS", 8.0, engineering_level=2) is True

    def test_auto_merge_not_eligible_l3(self):
        assert check_auto_merge_eligibility("PASS", 9.0, engineering_level=3) is False

    def test_auto_merge_not_eligible_low_score(self):
        assert check_auto_merge_eligibility("PASS", 7.5, engineering_level=1) is False

    def test_auto_merge_not_eligible_ci_red(self):
        assert check_auto_merge_eligibility("PASS", 9.0, engineering_level=1, ci_green=False) is False

    def test_produce_verdict_full_pipeline(self):
        dims = self._make_dimensions({
            "structural_validity": 10.0, "convention_compliance": 9.0,
            "backward_compatibility": 10.0, "domain_alignment": 9.0,
            "test_coverage": 8.0, "adversarial_resilience": 8.0, "documentation": 10.0,
        })
        result = produce_verdict(dims, engineering_level=2, ci_green=True)
        assert result.verdict == VERDICT_PASS
        assert result.aggregate_score >= 8.0
        assert result.auto_merge_eligible is True


class TestCodeEvaluator:
    """Tests that run evaluators against actual repo files."""

    def test_structural_validity_on_real_files(self):
        files = [
            ClassifiedFile(path="infra/docker/agents/branch_evaluation/scoring_engine.py",
                           artifact_type="code", status="added"),
        ]
        result = evaluate_structural_validity(files)
        assert result.score == 10.0, f"Parse failed: {result.issues}"

    def test_convention_compliance_on_real_files(self):
        files = [
            ClassifiedFile(path="infra/docker/agents/branch_evaluation/scoring_engine.py",
                           artifact_type="code", status="added"),
        ]
        result = evaluate_convention_compliance(files)
        assert result.score >= 8.0, f"Convention issues: {result.issues}"

    def test_backward_compatibility_no_deletions(self):
        files = [ClassifiedFile(path="infra/docker/agents/branch_evaluation/scoring_engine.py",
                                artifact_type="code", status="added")]
        result = evaluate_backward_compatibility(files)
        assert result.score == 10.0

    def test_backward_compatibility_deletion_detected(self):
        files = [ClassifiedFile(path="infra/docker/agents/some_module.py",
                                artifact_type="code", status="deleted")]
        result = evaluate_backward_compatibility(files)
        assert result.score < 10.0
        assert any("BREAKING" in i for i in result.issues)


class TestDomainEvaluator:
    """Tests for domain alignment and adversarial resilience."""

    def test_domain_alignment_on_real_hooks(self):
        files = [ClassifiedFile(path=".kiro/hooks/fde-adversarial-gate.kiro.hook",
                                artifact_type="hook", status="modified")]
        result = evaluate_domain_alignment(files)
        assert result.score >= 7.0, f"Domain issues: {result.issues}"

    def test_adversarial_resilience_on_real_code(self):
        files = [ClassifiedFile(path="infra/docker/agents/branch_evaluation/scoring_engine.py",
                                artifact_type="code", status="added")]
        result = evaluate_adversarial_resilience(files)
        assert result.score >= 7.0, f"Adversarial issues: {result.issues}"

    def test_adversarial_detects_bare_except(self):
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write('"""Module."""\ntry:\n    x = 1\nexcept:\n    pass\n')
            temp_path = f.name
        files = [ClassifiedFile(path=temp_path, artifact_type="code", status="added")]
        result = evaluate_adversarial_resilience(files)
        assert result.score < 10.0
        assert any("Bare except" in i for i in result.issues)
        Path(temp_path).unlink()


class TestReportRenderer:
    """Tests for report generation."""

    def _make_verdict(self):
        dims = [
            DimensionScore("structural_validity", 10.0, 0.20),
            DimensionScore("convention_compliance", 9.0, 0.15),
            DimensionScore("backward_compatibility", 10.0, 0.20),
            DimensionScore("domain_alignment", 8.0, 0.15),
            DimensionScore("test_coverage", 7.0, 0.15, issues=["No adversarial tests"]),
            DimensionScore("adversarial_resilience", 8.0, 0.10),
            DimensionScore("documentation", 10.0, 0.05),
        ]
        return EvaluationVerdict(verdict="PASS", aggregate_score=9.05, dimensions=dims,
                                 merge_eligible=True, auto_merge_eligible=True)

    def test_markdown_contains_verdict(self):
        md = render_markdown_report(self._make_verdict(), "feature/test", "main", 5, ["E4"])
        assert "PASS" in md
        assert "feature/test" in md

    def test_json_report_structure(self):
        report = render_json_report(self._make_verdict(), "feature/test", "main", 5, ["E4"])
        assert report["verdict"] == "PASS"
        assert report["aggregate_score"] == 9.05
        assert "structural_validity" in report["dimensions"]


class TestEndToEndEvaluation:
    """Full pipeline integration test using this repo as the fixture."""

    def test_full_evaluation_pipeline(self):
        changed_files = [
            ("added", "infra/docker/agents/branch_evaluation/__init__.py"),
            ("added", "infra/docker/agents/branch_evaluation/artifact_classifier.py"),
            ("added", "infra/docker/agents/branch_evaluation/scoring_engine.py"),
            ("added", "infra/docker/agents/branch_evaluation/code_evaluator.py"),
            ("added", "infra/docker/agents/branch_evaluation/domain_evaluator.py"),
            ("added", "infra/docker/agents/branch_evaluation/report_renderer.py"),
            ("added", "infra/docker/agents/branch_evaluation/merge_handler.py"),
            ("added", "docs/adr/ADR-018-branch-evaluation-agent.md"),
            ("added", "docs/flows/15-branch-evaluation.md"),
        ]

        # Phase 0: Classify
        files = classify_files(changed_files)
        assert len(files) == 9
        edges = get_affected_pipeline_edges(files)
        # branch_evaluation package doesn't directly participate in E1-E6 pipeline
        # This is correct behavior — not all changes affect pipeline edges

        # Phase 1-4: Evaluate
        dimensions = [
            evaluate_structural_validity(files),
            evaluate_convention_compliance(files),
            evaluate_backward_compatibility(files),
            evaluate_domain_alignment(files),
            evaluate_test_coverage(files),
            evaluate_adversarial_resilience(files),
            evaluate_documentation(files),
        ]

        for d in dimensions:
            assert 0.0 <= d.score <= 10.0, f"{d.name} out of range: {d.score}"

        # Phase 5: Verdict
        verdict = produce_verdict(dimensions, engineering_level=2, ci_green=True)
        assert verdict.verdict in (VERDICT_PASS, VERDICT_CONDITIONAL_PASS,
                                   VERDICT_CONDITIONAL_FAIL, VERDICT_FAIL)
        assert 0.0 <= verdict.aggregate_score <= 10.0

        # Phase 6: Reports
        md = render_markdown_report(verdict, "feature/branch-eval", "main", len(files), edges)
        assert "Branch Evaluation Report" in md

        json_report = render_json_report(verdict, "feature/branch-eval", "main", len(files), edges)
        assert json_report["verdict"] == verdict.verdict

        # Our own code should score reasonably well
        assert verdict.aggregate_score >= 6.0, (
            f"Self-evaluation: {verdict.aggregate_score:.1f}/10 — "
            f"issues: {[i for d in dimensions for i in d.issues]}"
        )
