"""
Integration Test: Maturity Scoring (Activities 3.13, 3.15).

Tests the SystemMaturityScorer capability scoring, composite score
mapping, team archetype detection, and RepoOnboardingAgent recommendations.

Some tests run without AWS (pure logic tests for scoring and mapping),
while DynamoDB-dependent tests are gated by FDE_INTEGRATION_TESTS_ENABLED.

Activity coverage:
  3.13 - SystemMaturityScorer (7 capabilities, composite, autonomy mapping)
  3.15 - RepoOnboardingAgent (onboarding recommendations)

Ref: docs/dora-2025-code-factory-analysis.md
     docs/adr/ADR-015-repo-onboarding-phase-zero.md
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# --- Tests that work WITHOUT AWS (pure logic) ---


class TestMaturityScorerLogic:
    """Pure logic tests for SystemMaturityScorer (no AWS required)."""

    def test_scores_all_seven_capabilities(self):
        """SystemMaturityScorer accepts scores for all 7 DORA capabilities."""
        from src.core.governance.system_maturity_scorer import (
            DoraCapability,
            SystemMaturityScorer,
        )

        scorer = SystemMaturityScorer(project_id="test-logic", metrics_table="")

        # Score all 7 capabilities
        scorer.score_capability(DoraCapability.C1_AI_STANCE, 60)
        scorer.score_capability(DoraCapability.C2_DATA_ECOSYSTEMS, 45)
        scorer.score_capability(DoraCapability.C3_AI_ACCESSIBLE_DATA, 50)
        scorer.score_capability(DoraCapability.C4_VERSION_CONTROL, 85)
        scorer.score_capability(DoraCapability.C5_SMALL_BATCHES, 70)
        scorer.score_capability(DoraCapability.C6_USER_CENTRIC_FOCUS, 40)
        scorer.score_capability(DoraCapability.C7_QUALITY_PLATFORMS, 75)

        assessment = scorer.compute_assessment()

        # All 7 capabilities should be scored
        assert len(assessment.capability_scores) == 7
        assert assessment.metadata["capabilities_scored"] == 7

    def test_score_clamped_to_0_100(self):
        """CapabilityScore clamps values to 0-100 range."""
        from src.core.governance.system_maturity_scorer import (
            DoraCapability,
            SystemMaturityScorer,
        )

        scorer = SystemMaturityScorer(project_id="test-clamp", metrics_table="")

        # Score above 100 should be clamped
        cap = scorer.score_capability(DoraCapability.C1_AI_STANCE, 150)
        assert cap.score == 100

        # Score below 0 should be clamped
        cap = scorer.score_capability(DoraCapability.C2_DATA_ECOSYSTEMS, -10)
        assert cap.score == 0

    def test_composite_score_weighted_average(self):
        """Composite score is a weighted average of capability scores."""
        from src.core.governance.system_maturity_scorer import (
            DoraCapability,
            SystemMaturityScorer,
        )

        scorer = SystemMaturityScorer(project_id="test-composite", metrics_table="")

        # All capabilities at 80 should give composite of 80
        for cap in DoraCapability:
            scorer.score_capability(cap, 80)

        assessment = scorer.compute_assessment()
        assert abs(assessment.composite_score - 80.0) < 0.1

    def test_low_composite_maps_to_max_l2(self):
        """Composite < 40 maps to MAX_L2 autonomy recommendation."""
        from src.core.governance.system_maturity_scorer import (
            AutonomyRecommendation,
            DoraCapability,
            SystemMaturityScorer,
        )

        scorer = SystemMaturityScorer(project_id="test-low", metrics_table="")

        # All capabilities at 20 -> composite ~20
        for cap in DoraCapability:
            scorer.score_capability(cap, 20)

        assessment = scorer.compute_assessment()
        assert assessment.composite_score < 40
        assert assessment.autonomy_recommendation == AutonomyRecommendation.MAX_L2

    def test_medium_composite_maps_to_max_l4(self):
        """Composite 40-70 maps to MAX_L4 autonomy recommendation."""
        from src.core.governance.system_maturity_scorer import (
            AutonomyRecommendation,
            DoraCapability,
            SystemMaturityScorer,
        )

        scorer = SystemMaturityScorer(project_id="test-medium", metrics_table="")

        # All capabilities at 55 -> composite ~55
        for cap in DoraCapability:
            scorer.score_capability(cap, 55)

        assessment = scorer.compute_assessment()
        assert 40 <= assessment.composite_score <= 70
        assert assessment.autonomy_recommendation == AutonomyRecommendation.MAX_L4

    def test_high_composite_maps_to_l5_eligible(self):
        """Composite > 70 maps to L5_ELIGIBLE autonomy recommendation."""
        from src.core.governance.system_maturity_scorer import (
            AutonomyRecommendation,
            DoraCapability,
            SystemMaturityScorer,
        )

        scorer = SystemMaturityScorer(project_id="test-high", metrics_table="")

        # All capabilities at 85 -> composite ~85
        for cap in DoraCapability:
            scorer.score_capability(cap, 85)

        assessment = scorer.compute_assessment()
        assert assessment.composite_score > 70
        assert assessment.autonomy_recommendation == AutonomyRecommendation.L5_ELIGIBLE

    def test_empty_scores_give_zero_composite(self):
        """No scored capabilities gives composite of 0."""
        from src.core.governance.system_maturity_scorer import SystemMaturityScorer

        scorer = SystemMaturityScorer(project_id="test-empty", metrics_table="")
        assessment = scorer.compute_assessment()
        assert assessment.composite_score == 0.0


class TestTeamArchetypeDetection:
    """Tests for team archetype classification logic."""

    def test_starting_archetype_low_scores(self):
        """Low scores with critical gaps map to STARTING archetype."""
        from src.core.governance.system_maturity_scorer import (
            DoraCapability,
            SystemMaturityScorer,
            TeamArchetype,
        )

        scorer = SystemMaturityScorer(project_id="test-starting", metrics_table="")

        # Very low scores with a critical gap (< 20)
        scorer.score_capability(DoraCapability.C1_AI_STANCE, 10)
        scorer.score_capability(DoraCapability.C2_DATA_ECOSYSTEMS, 15)
        scorer.score_capability(DoraCapability.C3_AI_ACCESSIBLE_DATA, 10)
        scorer.score_capability(DoraCapability.C4_VERSION_CONTROL, 25)
        scorer.score_capability(DoraCapability.C5_SMALL_BATCHES, 20)
        scorer.score_capability(DoraCapability.C6_USER_CENTRIC_FOCUS, 10)
        scorer.score_capability(DoraCapability.C7_QUALITY_PLATFORMS, 15)

        assessment = scorer.compute_assessment()
        assert assessment.team_archetype == TeamArchetype.STARTING

    def test_thriving_archetype_high_scores(self):
        """High scores across all capabilities map to THRIVING archetype."""
        from src.core.governance.system_maturity_scorer import (
            DoraCapability,
            SystemMaturityScorer,
            TeamArchetype,
        )

        scorer = SystemMaturityScorer(project_id="test-thriving", metrics_table="")

        # All capabilities above 75, min above 50
        scorer.score_capability(DoraCapability.C1_AI_STANCE, 80)
        scorer.score_capability(DoraCapability.C2_DATA_ECOSYSTEMS, 85)
        scorer.score_capability(DoraCapability.C3_AI_ACCESSIBLE_DATA, 75)
        scorer.score_capability(DoraCapability.C4_VERSION_CONTROL, 90)
        scorer.score_capability(DoraCapability.C5_SMALL_BATCHES, 85)
        scorer.score_capability(DoraCapability.C6_USER_CENTRIC_FOCUS, 70)
        scorer.score_capability(DoraCapability.C7_QUALITY_PLATFORMS, 80)

        assessment = scorer.compute_assessment()
        assert assessment.team_archetype == TeamArchetype.THRIVING

    def test_accelerating_archetype_strong_c4_c5(self):
        """Strong C4+C5 with composite > 50 maps to ACCELERATING."""
        from src.core.governance.system_maturity_scorer import (
            DoraCapability,
            SystemMaturityScorer,
            TeamArchetype,
        )

        scorer = SystemMaturityScorer(project_id="test-accel", metrics_table="")

        scorer.score_capability(DoraCapability.C1_AI_STANCE, 40)
        scorer.score_capability(DoraCapability.C2_DATA_ECOSYSTEMS, 50)
        scorer.score_capability(DoraCapability.C3_AI_ACCESSIBLE_DATA, 45)
        scorer.score_capability(DoraCapability.C4_VERSION_CONTROL, 75)  # Strong
        scorer.score_capability(DoraCapability.C5_SMALL_BATCHES, 70)    # Strong
        scorer.score_capability(DoraCapability.C6_USER_CENTRIC_FOCUS, 45)
        scorer.score_capability(DoraCapability.C7_QUALITY_PLATFORMS, 55)

        assessment = scorer.compute_assessment()
        assert assessment.team_archetype == TeamArchetype.ACCELERATING

    def test_flowing_archetype_moderate_scores(self):
        """Moderate scores without critical gaps map to FLOWING."""
        from src.core.governance.system_maturity_scorer import (
            DoraCapability,
            SystemMaturityScorer,
            TeamArchetype,
        )

        scorer = SystemMaturityScorer(project_id="test-flowing", metrics_table="")

        # Moderate scores, no critical gaps, but C4/C5 not strong enough for accelerating
        scorer.score_capability(DoraCapability.C1_AI_STANCE, 35)
        scorer.score_capability(DoraCapability.C2_DATA_ECOSYSTEMS, 40)
        scorer.score_capability(DoraCapability.C3_AI_ACCESSIBLE_DATA, 35)
        scorer.score_capability(DoraCapability.C4_VERSION_CONTROL, 45)
        scorer.score_capability(DoraCapability.C5_SMALL_BATCHES, 40)
        scorer.score_capability(DoraCapability.C6_USER_CENTRIC_FOCUS, 30)
        scorer.score_capability(DoraCapability.C7_QUALITY_PLATFORMS, 35)

        assessment = scorer.compute_assessment()
        assert assessment.team_archetype == TeamArchetype.FLOWING


class TestOnboardingAgentLogic:
    """Tests for RepoOnboardingAgent recommendation logic (no AWS required)."""

    def test_onboarding_result_dataclass(self):
        """OnboardingResult dataclass initializes correctly."""
        from src.agents.onboarding.repo_onboarding_agent import (
            GitHistoryMetrics,
            OnboardingProfile,
            OnboardingResult,
        )
        from src.core.brain_sim.organism_ladder import OrganismLevel
        from src.core.governance.system_maturity_scorer import (
            AutonomyRecommendation,
            TeamArchetype,
        )

        result = OnboardingResult(
            project_id="test-project",
            recommended_autonomy=AutonomyRecommendation.MAX_L4,
            recommended_profile=OnboardingProfile.STANDARD,
            recommended_organism_level=OrganismLevel.O3_COGNITIVE,
            team_archetype=TeamArchetype.FLOWING,
        )

        assert result.project_id == "test-project"
        assert result.onboarded_at != ""
        assert result.recommended_profile == OnboardingProfile.STANDARD

        # Serialization
        data = result.to_dict()
        assert data["project_id"] == "test-project"
        assert data["recommended_autonomy"] == "max_L4"
        assert data["recommended_profile"] == "standard"
        assert data["recommended_organism_level"] == 3

    def test_git_history_metrics_dataclass(self):
        """GitHistoryMetrics dataclass serializes correctly."""
        from src.agents.onboarding.repo_onboarding_agent import GitHistoryMetrics

        metrics = GitHistoryMetrics(
            commits_per_week=12.5,
            avg_pr_size_lines=150,
            active_contributors=4,
            branch_count=8,
            uses_trunk_based=True,
            total_commits_30d=54,
            merge_commit_ratio=0.25,
        )

        data = metrics.to_dict()
        assert data["commits_per_week"] == 12.5
        assert data["avg_pr_size_lines"] == 150
        assert data["active_contributors"] == 4
        assert data["uses_trunk_based"] is True

    @patch("src.agents.onboarding.repo_onboarding_agent.boto3.resource")
    @patch("src.agents.onboarding.repo_onboarding_agent.subprocess.run")
    def test_onboarding_produces_valid_recommendations(
        self, mock_subprocess, mock_boto
    ):
        """OnboardingAgent produces valid recommendations for a mock repo."""
        from src.agents.onboarding.repo_onboarding_agent import (
            OnboardingProfile,
            RepoOnboardingAgent,
        )
        from src.core.brain_sim.organism_ladder import OrganismLevel
        from src.core.governance.system_maturity_scorer import AutonomyRecommendation

        # Mock DynamoDB
        mock_table = MagicMock()
        mock_table.put_item.return_value = {}
        mock_table.get_item.return_value = {}
        mock_table.query.return_value = {"Items": []}
        mock_boto.return_value.Table.return_value = mock_table

        # Mock git commands to simulate an active repo
        def mock_git_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            if "rev-list" in cmd and "--count" in cmd:
                if "--merges" in cmd:
                    result.stdout = "5\n"
                else:
                    result.stdout = "45\n"
            elif "shortlog" in cmd:
                result.stdout = "  15\tDev A\n  12\tDev B\n  8\tDev C\n"
            elif "branch" in cmd:
                result.stdout = "  origin/main\n  origin/feature-1\n  origin/feature-2\n"
            elif "log" in cmd and "--merges" in cmd:
                result.stdout = "abc123\ndef456\n"
            elif "log" in cmd and "--first-parent" in cmd:
                result.stdout = "\n".join([f"abc{i} commit {i}" for i in range(20)])
            elif "diff" in cmd:
                result.stdout = " 3 files changed, 85 insertions(+), 20 deletions(-)\n"
            else:
                result.stdout = ""
            return result

        mock_subprocess.side_effect = mock_git_run

        # Create a temp workspace with expected files
        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / ".git").mkdir()
            (workspace / ".github" / "workflows").mkdir(parents=True)
            (workspace / ".github" / "pull_request_template.md").write_text("PR template")
            (workspace / "Makefile").write_text("all: build")
            (workspace / "docs" / "adr").mkdir(parents=True)

            agent = RepoOnboardingAgent(
                project_id="test-onboarding",
                workspace_path=str(workspace),
                metrics_table="fde-dev-metrics",
            )

            result = agent.run_onboarding()

        # Verify valid recommendations
        assert result.project_id == "test-onboarding"
        assert result.recommended_autonomy in list(AutonomyRecommendation)
        assert result.recommended_profile in list(OnboardingProfile)
        assert result.recommended_organism_level in list(OrganismLevel)
        assert result.maturity_assessment is not None
        assert result.maturity_assessment.composite_score >= 0

    def test_profile_enum_values(self):
        """OnboardingProfile enum has expected values."""
        from src.agents.onboarding.repo_onboarding_agent import OnboardingProfile

        assert OnboardingProfile.STARTER.value == "starter"
        assert OnboardingProfile.STANDARD.value == "standard"
        assert OnboardingProfile.FULL.value == "full"


# --- Tests that require AWS (gated by env var) ---

pytestmark_aws = pytest.mark.skipif(
    not os.environ.get("FDE_INTEGRATION_TESTS_ENABLED"),
    reason="Set FDE_INTEGRATION_TESTS_ENABLED=1 to run integration tests",
)


@pytestmark_aws
class TestMaturityScorerPersistence:
    """Tests for SystemMaturityScorer DynamoDB persistence."""

    def test_assessment_persisted_to_dynamodb(self):
        """SystemMaturityScorer persists assessment to metrics table."""
        from src.core.governance.system_maturity_scorer import (
            DoraCapability,
            SystemMaturityScorer,
        )

        metrics_table = os.environ.get("METRICS_TABLE", "fde-dev-metrics")
        scorer = SystemMaturityScorer(
            project_id="test-persist", metrics_table=metrics_table
        )

        for cap in DoraCapability:
            scorer.score_capability(cap, 60)

        assessment = scorer.compute_assessment()
        assert assessment.composite_score > 0

        # Retrieve the latest assessment
        latest = scorer.get_latest_assessment()
        assert latest is not None
        assert latest.project_id == "test-persist"
        assert latest.composite_score == assessment.composite_score

    def test_batch_scoring(self):
        """SystemMaturityScorer.score_all() batch-sets multiple capabilities."""
        from src.core.governance.system_maturity_scorer import (
            DoraCapability,
            SystemMaturityScorer,
        )

        metrics_table = os.environ.get("METRICS_TABLE", "fde-dev-metrics")
        scorer = SystemMaturityScorer(
            project_id="test-batch", metrics_table=metrics_table
        )

        scores = {
            DoraCapability.C1_AI_STANCE: 50,
            DoraCapability.C2_DATA_ECOSYSTEMS: 60,
            DoraCapability.C3_AI_ACCESSIBLE_DATA: 55,
            DoraCapability.C4_VERSION_CONTROL: 80,
            DoraCapability.C5_SMALL_BATCHES: 75,
            DoraCapability.C6_USER_CENTRIC_FOCUS: 45,
            DoraCapability.C7_QUALITY_PLATFORMS: 70,
        }

        scorer.score_all(scores)
        assessment = scorer.compute_assessment()

        assert len(assessment.capability_scores) == 7
        assert assessment.composite_score > 0


@pytestmark_aws
class TestOnboardingAgentIntegration:
    """Integration tests for RepoOnboardingAgent with real DynamoDB."""

    @patch("src.agents.onboarding.repo_onboarding_agent.subprocess.run")
    def test_full_onboarding_flow(self, mock_subprocess):
        """OnboardingAgent completes full onboarding with DynamoDB persistence."""
        from src.agents.onboarding.repo_onboarding_agent import RepoOnboardingAgent

        # Mock git commands
        def mock_git_run(cmd, **kwargs):
            result = MagicMock()
            result.returncode = 0
            if "rev-list" in cmd and "--count" in cmd:
                if "--merges" in cmd:
                    result.stdout = "3\n"
                else:
                    result.stdout = "20\n"
            elif "shortlog" in cmd:
                result.stdout = "  10\tDev A\n  5\tDev B\n"
            elif "branch" in cmd:
                result.stdout = "  origin/main\n  origin/dev\n"
            elif "log" in cmd and "--merges" in cmd:
                result.stdout = "abc123\n"
            elif "log" in cmd:
                result.stdout = "\n".join([f"abc{i} msg" for i in range(15)])
            elif "diff" in cmd:
                result.stdout = " 2 files changed, 50 insertions(+)\n"
            else:
                result.stdout = ""
            return result

        mock_subprocess.side_effect = mock_git_run

        with tempfile.TemporaryDirectory() as tmpdir:
            workspace = Path(tmpdir)
            (workspace / ".git").mkdir()
            (workspace / "Makefile").write_text("build:")

            metrics_table = os.environ.get("METRICS_TABLE", "fde-dev-metrics")
            agent = RepoOnboardingAgent(
                project_id="test-integration-onboard",
                workspace_path=str(workspace),
                metrics_table=metrics_table,
            )

            result = agent.run_onboarding()

        assert result.project_id == "test-integration-onboard"
        assert result.maturity_assessment is not None
        assert result.git_metrics.total_commits_30d == 20
        assert result.git_metrics.active_contributors == 2
