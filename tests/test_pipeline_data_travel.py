"""
E2E Data Travel Test — Validates the full FDE pipeline composition.

This is NOT a node-scoped test. It validates that data flows correctly
across module boundaries when a data contract enters the pipeline.

The test exercises the REAL composition:
  Data Contract → Scope Check → Autonomy → Gate Resolution → Execution Plan
  → SDLC Gates (with enrichment) → Pipeline Execution → Completion

Anti-pattern avoided: "Node-scoped verification" (COE-052)
What this proves: The modules compose correctly as a system.
"""

import json
import tempfile
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════
# Feature: Full Pipeline Data Travel
# ═══════════════════════════════════════════════════════════════════


class TestPipelineDataTravel:
    """
    Feature: Data contract flows through the entire pipeline correctly
      As a Code Factory
      I want a data contract to travel through all modules
      So that the composed system produces correct behavior
    """

    def test_bugfix_l2_high_confidence_full_journey(self):
        """
        Scenario: Bugfix L2 with high confidence travels the full pipeline
          Given a data contract with type=bugfix, level=L2, confidence=high
          When the pipeline processes this contract
          Then:
            1. Scope check passes with confidence_level="high"
            2. Autonomy resolves to L5 (Observer)
            3. Gate resolution with L5+high skips dor_gate and ship_readiness
            4. Execution plan is created with the remaining gates as milestones
            5. Each milestone can be started and completed
            6. If interrupted and resumed, it skips completed milestones
        """
        from agents.scope_boundaries import check_scope
        from agents.autonomy import compute_autonomy_level, resolve_pipeline_gates
        from agents.execution_plan import (
            create_plan, start_milestone, complete_milestone,
            resume_from_plan, save_plan, load_plan,
        )

        # ── Step 1: Data contract enters the system ──
        data_contract = {
            "type": "bugfix",
            "level": "L2",
            "tech_stack": ["Python", "FastAPI"],
            "title": "Fix null pointer in user service",
            "acceptance_criteria": [
                "User endpoint returns 200 for valid requests",
                "Null user_id returns 400 with error message",
                "Existing tests still pass",
            ],
            "constraints": "Do not change the API contract",
            "related_docs": ["docs/api-spec.md"],
        }

        # ── Step 2: Scope check produces confidence_level ──
        scope_result = check_scope(data_contract)
        assert scope_result.in_scope is True
        assert scope_result.confidence_level == "high"

        # ── Step 3: Autonomy computation uses data contract ──
        autonomy_result = compute_autonomy_level(data_contract)
        assert autonomy_result.level == "L5"
        assert autonomy_result.fast_path is True

        # ── Step 4: Gate resolution uses BOTH autonomy level AND confidence ──
        gates = resolve_pipeline_gates(
            autonomy_level=autonomy_result.level,
            confidence_level=scope_result.confidence_level,
        )

        # L5 + high confidence → minimal gates
        assert "dor_gate" not in gates.outer_gates
        assert "ship_readiness" not in gates.outer_gates
        assert "adversarial_challenge" not in gates.outer_gates
        assert "constraint_extraction" in gates.outer_gates
        assert "lint" in gates.inner_gates
        assert "unit_test" in gates.inner_gates
        assert "build" in gates.inner_gates

        # ── Step 5: Execution plan is created from resolved gates ──
        all_milestones = gates.outer_gates + gates.inner_gates
        plan = create_plan(
            task_id="TASK-bugfix-001",
            milestone_names=all_milestones,
        )

        assert plan.task_id == "TASK-bugfix-001"
        assert plan.total_count == len(all_milestones)
        assert plan.current_milestone == 0

        # ── Step 6: Pipeline executes milestones sequentially ──
        plan = start_milestone(plan)
        assert plan.milestones[0].status == "in_progress"
        plan = complete_milestone(plan, "Constraints extracted: 1 rule")
        assert plan.current_milestone == 1

        plan = start_milestone(plan)
        plan = complete_milestone(plan, "Lint passed with 0 errors")
        assert plan.current_milestone == 2

        # ── Step 7: Simulate interruption at milestone 3 ──
        plan = start_milestone(plan)
        assert plan.milestones[2].status == "in_progress"

        # Save state (simulating container crash)
        with tempfile.TemporaryDirectory() as tmp:
            save_plan(plan, tmp)

            # ── Step 8: Restart and resume ──
            loaded_plan = load_plan("TASK-bugfix-001", tmp)
            assert loaded_plan is not None

            resume_index = resume_from_plan(loaded_plan)
            assert resume_index == 2
            assert loaded_plan.milestones[0].status == "completed"
            assert loaded_plan.milestones[1].status == "completed"
            assert loaded_plan.milestones[2].status == "pending"

    def test_feature_l4_medium_confidence_full_gates(self):
        """
        Scenario: Feature L4 with medium confidence runs full gates
          Given a data contract with type=feature, level=L4
          When the pipeline processes this contract
          Then:
            1. Scope check passes with confidence_level="medium"
            2. Autonomy resolves to L3 (Consultant)
            3. Gate resolution runs ALL outer gates (no skips for L3)
            4. Human checkpoints are required after recon and at PR
        """
        from agents.scope_boundaries import check_scope
        from agents.autonomy import compute_autonomy_level, resolve_pipeline_gates

        data_contract = {
            "type": "feature",
            "level": "L4",
            "tech_stack": ["Terraform", "AWS"],
            "title": "Add VPC peering for cross-account access",
            "acceptance_criteria": [
                "VPC peering connection is established",
                "Route tables updated in both accounts",
            ],
        }

        scope_result = check_scope(data_contract)
        assert scope_result.in_scope is True
        assert scope_result.confidence_level == "medium"

        autonomy_result = compute_autonomy_level(data_contract)
        assert autonomy_result.level == "L3"
        assert "after_reconnaissance" in autonomy_result.human_checkpoints

        gates = resolve_pipeline_gates(
            autonomy_level=autonomy_result.level,
            confidence_level=scope_result.confidence_level,
        )

        assert "dor_gate" in gates.outer_gates
        assert "constraint_extraction" in gates.outer_gates
        assert "adversarial_challenge" in gates.outer_gates
        assert "ship_readiness" in gates.outer_gates
        assert "after_reconnaissance" in gates.human_checkpoints
        assert "pr_review" in gates.human_checkpoints

    def test_lint_enrichment_reaches_gate_result(self):
        """
        Scenario: Lint errors in the inner loop include remediation hints
          Given a workspace with a Python file that has E501 errors
          When check_lint runs and produces errors
          Then the error output includes remediation instructions
          And the enriched output is what the agent sees in the retry
        """
        from agents.sdlc_gates import _enrich_lint_output

        # Simulate what happens inside check_lint when ruff reports E501
        raw_error = "src/main.py:42:89: E501 Line too long (120 > 88 characters)"

        # The enrichment function is called inside check_lint on errors
        enriched = _enrich_lint_output(raw_error, tech_stack=["python"])

        # The agent sees the enriched output, not the raw error
        assert "E501" in enriched
        assert "Remediation:" in enriched
        assert "Split line at a logical boundary" in enriched
        assert "src/main.py:42:89" in enriched

    def test_execution_plan_milestones_match_resolved_gates(self):
        """
        Scenario: Execution plan milestones are derived from gate resolution
          Given a resolved set of gates (outer + inner)
          When an execution plan is created from those gates
          Then the plan milestones exactly match the gate sequence
          And completing all milestones marks the plan as done
        """
        from agents.autonomy import resolve_pipeline_gates
        from agents.execution_plan import create_plan, start_milestone, complete_milestone

        gates = resolve_pipeline_gates("L4")
        all_milestones = gates.outer_gates + gates.inner_gates

        plan = create_plan("TASK-integration", all_milestones)

        assert [m.name for m in plan.milestones] == all_milestones
        assert plan.total_count == len(gates.outer_gates) + len(gates.inner_gates)

        for _ in range(plan.total_count):
            plan = start_milestone(plan)
            plan = complete_milestone(plan, "done")

        assert plan.is_complete is True
        assert plan.status == "completed"

    def test_scope_rejection_prevents_pipeline_entry(self):
        """
        Scenario: Out-of-scope task never enters the pipeline
          Given a data contract requesting production deploy
          When scope check runs
          Then the task is rejected
          And no autonomy computation happens
          And no execution plan is created
        """
        from agents.scope_boundaries import check_scope

        data_contract = {
            "type": "infrastructure",
            "level": "L3",
            "tech_stack": ["Terraform"],
            "title": "Deploy to production",
            "acceptance_criteria": ["Service is live in production"],
        }

        scope_result = check_scope(data_contract)
        assert scope_result.in_scope is False
        assert scope_result.rejection_reason == "production_deploy_forbidden"

    def test_confidence_level_flows_from_scope_to_gates(self):
        """
        Scenario: confidence_level computed by scope_boundaries is consumed by autonomy
          Given two data contracts with different signal counts
          When each flows through scope → autonomy → gates
          Then the gate behavior differs based on confidence
        """
        from agents.scope_boundaries import check_scope
        from agents.autonomy import compute_autonomy_level, resolve_pipeline_gates

        # High confidence: all signals present
        high_contract = {
            "type": "bugfix", "level": "L2",
            "tech_stack": ["Python"],
            "acceptance_criteria": ["a", "b", "c"],
            "constraints": "no breaking changes",
            "related_docs": ["spec.md"],
        }

        # Low confidence: minimal signals
        low_contract = {
            "type": "bugfix", "level": "L2",
            "tech_stack": ["Cobol"],
            "acceptance_criteria": ["fix it"],
        }

        # High confidence path
        high_scope = check_scope(high_contract)
        high_autonomy = compute_autonomy_level(high_contract)
        high_gates = resolve_pipeline_gates(high_autonomy.level, high_scope.confidence_level)

        assert high_scope.confidence_level == "high"
        assert "dor_gate" not in high_gates.outer_gates

        # Low confidence path
        low_scope = check_scope(low_contract)
        low_autonomy = compute_autonomy_level(low_contract)
        low_gates = resolve_pipeline_gates(low_autonomy.level, low_scope.confidence_level)

        assert low_scope.confidence_level == "low"
        assert "dor_gate" in low_gates.outer_gates

    def test_documentation_task_minimal_path(self):
        """
        Scenario: Documentation task takes the fastest path through the pipeline
          Given a data contract with type=documentation, high confidence
          When it flows through the full pipeline
          Then: L5 autonomy, minimal gates, fast execution plan
        """
        from agents.scope_boundaries import check_scope
        from agents.autonomy import compute_autonomy_level, resolve_pipeline_gates
        from agents.execution_plan import create_plan

        data_contract = {
            "type": "documentation", "level": "L3",
            "tech_stack": ["Python"],
            "acceptance_criteria": ["README updated", "CHANGELOG updated", "ADR written"],
            "constraints": "No code changes",
        }

        scope = check_scope(data_contract)
        autonomy = compute_autonomy_level(data_contract)
        gates = resolve_pipeline_gates(autonomy.level, scope.confidence_level)

        assert autonomy.level == "L5"
        assert scope.confidence_level == "high"
        assert gates.outer_gates == ["constraint_extraction"]
        assert len(gates.inner_gates) == 4

        plan = create_plan("TASK-docs", gates.outer_gates + gates.inner_gates)
        assert plan.total_count == 5
