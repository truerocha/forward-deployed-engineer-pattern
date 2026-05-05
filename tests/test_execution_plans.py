"""
BDD Scenarios: Execution Plans with Progress Tracking (Task 1)

These tests validate that the execution plan module correctly creates,
tracks, persists, and resumes pipeline execution plans.

Source: OpenAI PLANS.md Cookbook
Impact: Allows L3/L4 tasks to resume from interruption point instead of restarting
"""

import json
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════
# Feature: Execution Plan Creation
# ═══════════════════════════════════════════════════════════════════


class TestExecutionPlanCreation:
    """
    Feature: Create execution plans for pipeline tasks
      As an Orchestrator
      I want to create a plan at pipeline start
      So that progress is tracked and resumable
    """

    def test_create_plan_with_milestones(self):
        """
        Scenario: Create a plan with 4 milestones
          Given a task_id and 4 milestone names
          When create_plan is called
          Then the plan has 4 milestones all in "pending" status
          And current_milestone is 0
          And status is "active"
        """
        from agents.execution_plan import create_plan

        plan = create_plan(
            task_id="TASK-abc123",
            milestone_names=[
                "constraint_extraction",
                "dor_gate",
                "engineering",
                "ship_readiness",
            ],
        )

        assert plan.task_id == "TASK-abc123"
        assert len(plan.milestones) == 4
        assert all(m.status == "pending" for m in plan.milestones)
        assert plan.current_milestone == 0
        assert plan.status == "active"
        assert plan.created_at != ""

    def test_create_plan_with_descriptions(self):
        """
        Scenario: Create a plan with milestone descriptions
          Given milestone names and matching descriptions
          When create_plan is called
          Then each milestone has its description set
        """
        from agents.execution_plan import create_plan

        plan = create_plan(
            task_id="TASK-xyz",
            milestone_names=["recon", "build"],
            descriptions=["Reconnaissance phase", "Build phase"],
        )

        assert plan.milestones[0].description == "Reconnaissance phase"
        assert plan.milestones[1].description == "Build phase"


# ═══════════════════════════════════════════════════════════════════
# Feature: Milestone Progression
# ═══════════════════════════════════════════════════════════════════


class TestMilestoneProgression:
    """
    Feature: Track milestone progress through the pipeline
      As an Orchestrator executing a pipeline
      I want to mark milestones as started/completed
      So that the plan reflects actual progress
    """

    def test_start_milestone(self):
        """
        Scenario: Start the first milestone
          Given a fresh plan with 3 milestones
          When start_milestone is called
          Then the first milestone is "in_progress"
          And progress_log has a "started" entry
        """
        from agents.execution_plan import create_plan, start_milestone

        plan = create_plan("TASK-1", ["a", "b", "c"])
        plan = start_milestone(plan)

        assert plan.milestones[0].status == "in_progress"
        assert plan.milestones[0].started_at != ""
        assert len(plan.progress_log) == 1
        assert plan.progress_log[0].action == "started"

    def test_complete_milestone_advances_index(self):
        """
        Scenario: Complete a milestone advances current_milestone
          Given a plan with milestone 0 in_progress
          When complete_milestone is called
          Then milestone 0 is "completed"
          And current_milestone advances to 1
        """
        from agents.execution_plan import create_plan, start_milestone, complete_milestone

        plan = create_plan("TASK-1", ["a", "b", "c"])
        plan = start_milestone(plan)
        plan = complete_milestone(plan, output_summary="Extracted 3 constraints")

        assert plan.milestones[0].status == "completed"
        assert plan.milestones[0].output_summary == "Extracted 3 constraints"
        assert plan.current_milestone == 1

    def test_complete_all_milestones_marks_plan_completed(self):
        """
        Scenario: Completing all milestones marks the plan as completed
          Given a plan with 2 milestones
          When both are completed
          Then plan.status is "completed"
          And plan.is_complete is True
        """
        from agents.execution_plan import create_plan, start_milestone, complete_milestone

        plan = create_plan("TASK-1", ["a", "b"])
        plan = start_milestone(plan)
        plan = complete_milestone(plan)
        plan = start_milestone(plan)
        plan = complete_milestone(plan)

        assert plan.status == "completed"
        assert plan.is_complete is True
        assert plan.completed_count == 2

    def test_skip_milestone(self):
        """
        Scenario: Skip a milestone (e.g., fast path)
          Given a plan with 3 milestones
          When skip_milestone is called on the first
          Then it's marked "skipped" and index advances
        """
        from agents.execution_plan import create_plan, skip_milestone

        plan = create_plan("TASK-1", ["a", "b", "c"])
        plan = skip_milestone(plan, reason="Fast path — no constraints")

        assert plan.milestones[0].status == "skipped"
        assert plan.current_milestone == 1
        assert plan.progress_log[0].action == "skipped"


# ═══════════════════════════════════════════════════════════════════
# Feature: Resume from Interruption
# ═══════════════════════════════════════════════════════════════════


class TestResumeFromInterruption:
    """
    Feature: Resume pipeline from interruption point
      As an Orchestrator restarting after interruption
      I want to resume from the last incomplete milestone
      So that completed work is not repeated

    This is the core value proposition of execution plans.
    """

    def test_resume_skips_completed_milestones(self):
        """
        Scenario: Resume after 2 of 4 milestones completed
          Given a plan with 4 milestones where 2 are completed
          When resume_from_plan is called
          Then it returns index 2 (the third milestone)
          And current_milestone is updated to 2
        """
        from agents.execution_plan import (
            create_plan, start_milestone, complete_milestone, resume_from_plan,
        )

        plan = create_plan("TASK-1", ["a", "b", "c", "d"])
        # Complete first two
        plan = start_milestone(plan)
        plan = complete_milestone(plan, "done a")
        plan = start_milestone(plan)
        plan = complete_milestone(plan, "done b")

        # Simulate interruption: plan is saved with current_milestone=2
        # On restart, resume_from_plan finds the first non-completed milestone
        resume_index = resume_from_plan(plan)

        assert resume_index == 2
        assert plan.current_milestone == 2
        assert plan.milestones[0].status == "completed"
        assert plan.milestones[1].status == "completed"
        assert plan.milestones[2].status == "pending"

    def test_resume_resets_in_progress_milestone(self):
        """
        Scenario: Resume when a milestone was interrupted mid-execution
          Given a plan where milestone 2 is "in_progress" (was running when interrupted)
          When resume_from_plan is called
          Then milestone 2 is reset to "pending"
          And progress_log has a "resumed" entry
        """
        from agents.execution_plan import (
            create_plan, start_milestone, complete_milestone, resume_from_plan,
        )

        plan = create_plan("TASK-1", ["a", "b", "c", "d"])
        plan = start_milestone(plan)
        plan = complete_milestone(plan)
        plan = start_milestone(plan)
        plan = complete_milestone(plan)
        plan = start_milestone(plan)  # milestone "c" is now in_progress

        # Simulate interruption — milestone "c" was in_progress
        assert plan.milestones[2].status == "in_progress"

        resume_index = resume_from_plan(plan)

        assert resume_index == 2
        assert plan.milestones[2].status == "pending"
        # Check that a "resumed" entry was added
        resumed_entries = [p for p in plan.progress_log if p.action == "resumed"]
        assert len(resumed_entries) == 1
        assert resumed_entries[0].milestone_name == "c"

    def test_resume_all_completed_returns_total(self):
        """
        Scenario: Resume when all milestones are already completed
          Given a plan where all milestones are completed
          When resume_from_plan is called
          Then it returns the total milestone count (nothing to resume)
          And plan status is "completed"
        """
        from agents.execution_plan import (
            create_plan, start_milestone, complete_milestone, resume_from_plan,
        )

        plan = create_plan("TASK-1", ["a", "b"])
        plan = start_milestone(plan)
        plan = complete_milestone(plan)
        plan = start_milestone(plan)
        plan = complete_milestone(plan)

        resume_index = resume_from_plan(plan)

        assert resume_index == 2  # Total count
        assert plan.status == "completed"

    def test_full_interruption_resume_cycle(self):
        """
        Scenario: Full BDD cycle — create → complete 2/4 → interrupt → restart → resume from 3
          Given a plan with 4 milestones
          When milestones 1 and 2 are completed
          And the pipeline is "interrupted" (simulated by saving and reloading)
          And the pipeline restarts
          Then it resumes from milestone 3
          And milestones 1 and 2 are not re-executed
        """
        from agents.execution_plan import (
            create_plan, start_milestone, complete_milestone,
            resume_from_plan, save_plan, load_plan,
        )

        # Phase 1: Create and execute 2 milestones
        plan = create_plan("TASK-RESUME", ["recon", "extract", "build", "ship"])
        plan = start_milestone(plan)
        plan = complete_milestone(plan, "Reconnaissance complete")
        plan = start_milestone(plan)
        plan = complete_milestone(plan, "Constraints extracted")

        # Phase 2: Save (simulating state before interruption)
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            save_plan(plan, tmp)

            # Phase 3: Simulate restart — load the plan fresh
            loaded_plan = load_plan("TASK-RESUME", tmp)
            assert loaded_plan is not None

            # Phase 4: Resume
            resume_index = resume_from_plan(loaded_plan)

            assert resume_index == 2
            assert loaded_plan.milestones[0].status == "completed"
            assert loaded_plan.milestones[1].status == "completed"
            assert loaded_plan.milestones[2].status == "pending"
            assert loaded_plan.milestones[3].status == "pending"


# ═══════════════════════════════════════════════════════════════════
# Feature: Persistence (Save/Load)
# ═══════════════════════════════════════════════════════════════════


class TestPlanPersistence:
    """
    Feature: Plans persist across process restarts
      As an Orchestrator
      I want plans to survive container restarts
      So that long-running tasks can resume
    """

    def test_save_and_load_roundtrip(self, tmp_path):
        """
        Scenario: Save a plan and load it back
          Given a plan with progress
          When saved to disk and loaded back
          Then all fields are preserved
        """
        from agents.execution_plan import (
            create_plan, start_milestone, complete_milestone,
            add_decision, save_plan, load_plan,
        )

        plan = create_plan("TASK-PERSIST", ["a", "b", "c"])
        plan = start_milestone(plan)
        plan = complete_milestone(plan, "done a")
        plan = add_decision(plan, "Use fast path", "No constraints found")

        save_plan(plan, str(tmp_path))
        loaded = load_plan("TASK-PERSIST", str(tmp_path))

        assert loaded is not None
        assert loaded.task_id == "TASK-PERSIST"
        assert loaded.completed_count == 1
        assert loaded.current_milestone == 1
        assert len(loaded.decision_log) == 1
        assert loaded.decision_log[0].decision == "Use fast path"

    def test_load_nonexistent_returns_none(self, tmp_path):
        """
        Scenario: Loading a non-existent plan returns None
          Given no plan file exists
          When load_plan is called
          Then it returns None (graceful degradation)
        """
        from agents.execution_plan import load_plan

        result = load_plan("TASK-MISSING", str(tmp_path))
        assert result is None

    def test_load_corrupted_returns_none(self, tmp_path):
        """
        Scenario: Loading a corrupted plan file returns None
          Given a plan file with invalid JSON
          When load_plan is called
          Then it returns None (graceful degradation, no crash)
        """
        from agents.execution_plan import load_plan

        plan_dir = tmp_path / "TASK-CORRUPT"
        plan_dir.mkdir()
        (plan_dir / "execution_plan.json").write_text("not valid json {{{")

        result = load_plan("TASK-CORRUPT", str(tmp_path))
        assert result is None

    def test_plan_exists_check(self, tmp_path):
        """
        Scenario: plan_exists correctly reports presence
          Given a saved plan
          When plan_exists is called
          Then it returns True for existing plans and False for missing
        """
        from agents.execution_plan import create_plan, save_plan, plan_exists

        plan = create_plan("TASK-EXISTS", ["a"])
        save_plan(plan, str(tmp_path))

        assert plan_exists("TASK-EXISTS", str(tmp_path)) is True
        assert plan_exists("TASK-NOPE", str(tmp_path)) is False


# ═══════════════════════════════════════════════════════════════════
# Feature: Decision Log
# ═══════════════════════════════════════════════════════════════════


class TestDecisionLog:
    """
    Feature: Record decisions during execution
      As an Orchestrator making pipeline decisions
      I want to log decisions with rationale
      So that post-mortem analysis can understand why choices were made
    """

    def test_add_decision_records_milestone_context(self):
        """
        Scenario: Decision is recorded with current milestone context
          Given a plan at milestone "engineering"
          When add_decision is called
          Then the decision entry includes milestone_name "engineering"
        """
        from agents.execution_plan import create_plan, start_milestone, complete_milestone, add_decision

        plan = create_plan("TASK-1", ["recon", "engineering", "ship"])
        plan = start_milestone(plan)
        plan = complete_milestone(plan)
        # Now at milestone "engineering"
        plan = add_decision(plan, "Skip adversarial gate", "L5 high confidence")

        assert len(plan.decision_log) == 1
        assert plan.decision_log[0].milestone_name == "engineering"
        assert plan.decision_log[0].rationale == "L5 high confidence"
