"""
BDD Scenarios: Autonomy Level in Data Contract (ADR-013, Decision 1)

These tests validate that the Code Factory correctly computes and applies
autonomy levels based on the data contract fields (type + level).

Source: "Levels of Autonomy for AI Agents" (Feng et al., Jun 2025)
Source: "WhatsCode" (Mao et al., Dec 2025) — two stable collaboration patterns

All scenarios MUST FAIL until the autonomy_level module is implemented.
"""

import pytest


# ═══════════════════════════════════════════════════════════════════
# Feature: Autonomy Level Computation
# ═══════════════════════════════════════════════════════════════════


class TestAutonomyLevelComputation:
    """
    Feature: The factory computes an autonomy level for each task
      As a Staff Engineer
      I want the factory to automatically determine how much supervision a task needs
      So that simple tasks run fast and complex tasks get human checkpoints
    """

    def test_bugfix_l2_defaults_to_observer(self):
        """
        Scenario: Bugfix with low engineering level gets maximum autonomy
          Given a data contract with type "bugfix" and level "L2"
          When the autonomy level is computed
          Then the autonomy_level should be "L5" (Observer)
          And the pipeline should use fast-path execution
        """
        from agents.autonomy import compute_autonomy_level

        contract = {"type": "bugfix", "level": "L2", "tech_stack": ["Python"]}
        result = compute_autonomy_level(contract)

        assert result.level == "L5"
        assert result.name == "Observer"
        assert result.human_checkpoints == []
        assert result.fast_path is True

    def test_feature_l3_defaults_to_approver(self):
        """
        Scenario: Standard feature gets Approver level
          Given a data contract with type "feature" and level "L3"
          When the autonomy level is computed
          Then the autonomy_level should be "L4" (Approver)
          And the pipeline should require human approval at PR
        """
        from agents.autonomy import compute_autonomy_level

        contract = {"type": "feature", "level": "L3", "tech_stack": ["Python", "FastAPI"]}
        result = compute_autonomy_level(contract)

        assert result.level == "L4"
        assert result.name == "Approver"
        assert "pr_review" in result.human_checkpoints
        assert result.fast_path is False

    def test_feature_l4_defaults_to_consultant(self):
        """
        Scenario: Architectural feature gets Consultant level (more supervision)
          Given a data contract with type "feature" and level "L4"
          When the autonomy level is computed
          Then the autonomy_level should be "L3" (Consultant)
          And the pipeline should checkpoint after Reconnaissance
        """
        from agents.autonomy import compute_autonomy_level

        contract = {"type": "feature", "level": "L4", "tech_stack": ["Terraform", "AWS"]}
        result = compute_autonomy_level(contract)

        assert result.level == "L3"
        assert result.name == "Consultant"
        assert "after_reconnaissance" in result.human_checkpoints
        assert "pr_review" in result.human_checkpoints

    def test_documentation_defaults_to_observer(self):
        """
        Scenario: Documentation tasks run fully autonomous
          Given a data contract with type "documentation"
          When the autonomy level is computed
          Then the autonomy_level should be "L5" (Observer)
        """
        from agents.autonomy import compute_autonomy_level

        contract = {"type": "documentation", "level": "L3", "tech_stack": []}
        result = compute_autonomy_level(contract)

        assert result.level == "L5"
        assert result.name == "Observer"

    def test_explicit_override_takes_precedence(self):
        """
        Scenario: Human can override the computed autonomy level
          Given a data contract with type "bugfix" and level "L2"
          And an explicit autonomy_level "L3" in the contract
          When the autonomy level is computed
          Then the autonomy_level should be "L3" (Consultant)
          Because the human override takes precedence over defaults
        """
        from agents.autonomy import compute_autonomy_level

        contract = {
            "type": "bugfix", "level": "L2",
            "tech_stack": ["Python"],
            "autonomy_level": "L3",  # Human override
        }
        result = compute_autonomy_level(contract)

        assert result.level == "L3"
        assert result.name == "Consultant"

    def test_infrastructure_defaults_to_approver(self):
        """
        Scenario: Infrastructure tasks get Approver level (risky but well-scoped)
          Given a data contract with type "infrastructure" and level "L3"
          When the autonomy level is computed
          Then the autonomy_level should be "L4" (Approver)
        """
        from agents.autonomy import compute_autonomy_level

        contract = {"type": "infrastructure", "level": "L3", "tech_stack": ["Terraform"]}
        result = compute_autonomy_level(contract)

        assert result.level == "L4"
        assert result.name == "Approver"


# ═══════════════════════════════════════════════════════════════════
# Feature: Pipeline Adapts to Autonomy Level
# ═══════════════════════════════════════════════════════════════════


class TestPipelineAdaptsToAutonomy:
    """
    Feature: The Orchestrator adapts pipeline behavior based on autonomy level
      As a Code Factory
      I want to run fewer gates for high-autonomy tasks
      So that simple tasks complete faster without sacrificing safety for complex ones
    """

    def test_l5_observer_skips_adversarial_gate(self):
        """
        Scenario: Observer level skips the adversarial challenge
          Given a task with autonomy_level "L5"
          When the pipeline gates are resolved
          Then the adversarial gate should be skipped
          And the inner loop gates should still run (lint, test, build)
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L5")

        assert "adversarial_challenge" not in gates.outer_gates
        assert "lint" in gates.inner_gates
        assert "unit_test" in gates.inner_gates
        assert "build" in gates.inner_gates

    def test_l4_approver_runs_full_outer_loop(self):
        """
        Scenario: Approver level runs the full outer loop
          Given a task with autonomy_level "L4"
          When the pipeline gates are resolved
          Then all outer loop gates should run
          And the only human checkpoint is PR review
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L4")

        assert "dor_gate" in gates.outer_gates
        assert "constraint_extraction" in gates.outer_gates
        assert "adversarial_challenge" in gates.outer_gates
        assert "ship_readiness" in gates.outer_gates
        assert gates.human_checkpoints == ["pr_review"]

    def test_l3_consultant_adds_mid_pipeline_checkpoint(self):
        """
        Scenario: Consultant level adds a checkpoint after reconnaissance
          Given a task with autonomy_level "L3"
          When the pipeline gates are resolved
          Then there should be a human checkpoint after reconnaissance
          And another checkpoint at PR review
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L3")

        assert "after_reconnaissance" in gates.human_checkpoints
        assert "pr_review" in gates.human_checkpoints

    def test_l2_collaborator_checkpoints_every_phase(self):
        """
        Scenario: Collaborator level requires human approval at every phase
          Given a task with autonomy_level "L2"
          When the pipeline gates are resolved
          Then there should be checkpoints after recon, after engineering, and at PR
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L2")

        assert "after_reconnaissance" in gates.human_checkpoints
        assert "after_engineering" in gates.human_checkpoints
        assert "pr_review" in gates.human_checkpoints


# ═══════════════════════════════════════════════════════════════════
# Feature: Minimal Gates for L5 High-Confidence Tasks (Task 7)
# ═══════════════════════════════════════════════════════════════════


class TestMinimalGatesL5:
    """
    Feature: High-confidence L5 tasks run with minimal gates
      As a Code Factory optimizing for throughput
      I want high-confidence L5 tasks to skip unnecessary gates
      So that corrections are cheap and waiting is expensive (Loop Mindset)

    Source: OpenAI "corrections are cheap, waiting is expensive" + Ralph Loop
    """

    def test_l5_high_confidence_skips_dor_and_ship_readiness(self):
        """
        Scenario: L5 + high confidence → only inner loop gates + constraint extraction
          Given a task with autonomy_level "L5" and confidence_level "high"
          When the pipeline gates are resolved
          Then dor_gate should be skipped
          And ship_readiness should be skipped
          And constraint_extraction should still run
          And all inner loop gates should still run
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L5", confidence_level="high")

        assert "dor_gate" not in gates.outer_gates
        assert "ship_readiness" not in gates.outer_gates
        assert "constraint_extraction" in gates.outer_gates
        # Inner loop always runs
        assert "lint" in gates.inner_gates
        assert "unit_test" in gates.inner_gates
        assert "build" in gates.inner_gates

    def test_l5_medium_confidence_runs_full_l5_gates(self):
        """
        Scenario: L5 + medium confidence → standard L5 gates (no extra skips)
          Given a task with autonomy_level "L5" and confidence_level "medium"
          When the pipeline gates are resolved
          Then dor_gate should still run
          And ship_readiness should still run
          And adversarial_challenge should still be skipped (standard L5 behavior)
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L5", confidence_level="medium")

        assert "dor_gate" in gates.outer_gates
        assert "ship_readiness" in gates.outer_gates
        assert "adversarial_challenge" not in gates.outer_gates

    def test_l5_no_confidence_runs_full_l5_gates(self):
        """
        Scenario: L5 without confidence_level → standard L5 gates (backward compatible)
          Given a task with autonomy_level "L5" and no confidence_level
          When the pipeline gates are resolved
          Then behavior is identical to pre-Task-7 (only adversarial skipped)
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L5")

        assert "dor_gate" in gates.outer_gates
        assert "ship_readiness" in gates.outer_gates
        assert "constraint_extraction" in gates.outer_gates
        assert "adversarial_challenge" not in gates.outer_gates

    def test_l4_high_confidence_no_effect(self):
        """
        Scenario: L4 + high confidence → no gate reduction (only L5 gets minimal gates)
          Given a task with autonomy_level "L4" and confidence_level "high"
          When the pipeline gates are resolved
          Then all outer loop gates should run (minimal gates only apply to L5)
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L4", confidence_level="high")

        assert "dor_gate" in gates.outer_gates
        assert "ship_readiness" in gates.outer_gates
        assert "adversarial_challenge" in gates.outer_gates
        assert "constraint_extraction" in gates.outer_gates

    def test_l5_low_confidence_runs_full_l5_gates(self):
        """
        Scenario: L5 + low confidence → standard L5 gates (safety net)
          Given a task with autonomy_level "L5" and confidence_level "low"
          When the pipeline gates are resolved
          Then dor_gate and ship_readiness should still run
          Because low-confidence tasks need the safety net
        """
        from agents.autonomy import resolve_pipeline_gates

        gates = resolve_pipeline_gates(autonomy_level="L5", confidence_level="low")

        assert "dor_gate" in gates.outer_gates
        assert "ship_readiness" in gates.outer_gates
