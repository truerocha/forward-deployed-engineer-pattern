"""
Repo Onboarding Agent — Phase 0 Assessment (Activity 3.15).

Runs when a new repository is added to the factory. Performs initial
assessment using SystemMaturityScorer, detects team archetype from
git history, and recommends:
  - Initial autonomy level (L2/L4/L5)
  - Profile (starter/standard/full)
  - Default organism level for task classification

Team archetype detection analyzes:
  - Commit frequency (commits per week)
  - PR patterns (avg PR size, review turnaround)
  - Branch strategy (trunk-based vs feature branches)
  - Contributor count and distribution

Results are stored in the DynamoDB metrics table for use by the
orchestrator and governance systems.

DynamoDB SK pattern: onboarding#{project_id}#{date}

Ref: docs/adr/ADR-015-repo-onboarding-phase-zero.md
     docs/design/fde-core-brain-development.md Wave 3
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

from src.core.brain_sim.organism_ladder import OrganismLevel, OrganismLadder
from src.core.governance.system_maturity_scorer import (
    AutonomyRecommendation,
    DoraCapability,
    MaturityAssessment,
    SystemMaturityScorer,
    TeamArchetype,
)

logger = logging.getLogger(__name__)


class OnboardingProfile(Enum):
    """Factory profile recommendation based on maturity assessment."""

    STARTER = "starter"
    STANDARD = "standard"
    FULL = "full"


@dataclass
class GitHistoryMetrics:
    """Metrics extracted from git history for team archetype detection."""

    commits_per_week: float = 0.0
    avg_pr_size_lines: int = 0
    active_contributors: int = 0
    branch_count: int = 0
    uses_trunk_based: bool = False
    avg_review_turnaround_hours: float = 0.0
    total_commits_30d: int = 0
    merge_commit_ratio: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "commits_per_week": self.commits_per_week,
            "avg_pr_size_lines": self.avg_pr_size_lines,
            "active_contributors": self.active_contributors,
            "branch_count": self.branch_count,
            "uses_trunk_based": self.uses_trunk_based,
            "avg_review_turnaround_hours": self.avg_review_turnaround_hours,
            "total_commits_30d": self.total_commits_30d,
            "merge_commit_ratio": self.merge_commit_ratio,
        }


@dataclass
class OnboardingResult:
    """Complete onboarding assessment result."""

    project_id: str
    maturity_assessment: MaturityAssessment | None = None
    git_metrics: GitHistoryMetrics = field(default_factory=GitHistoryMetrics)
    recommended_autonomy: AutonomyRecommendation = AutonomyRecommendation.MAX_L2
    recommended_profile: OnboardingProfile = OnboardingProfile.STARTER
    recommended_organism_level: OrganismLevel = OrganismLevel.O2_ADAPTIVE
    team_archetype: TeamArchetype = TeamArchetype.STARTING
    onboarded_at: str = ""
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.onboarded_at:
            self.onboarded_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for persistence."""
        return {
            "project_id": self.project_id,
            "maturity_assessment": (
                self.maturity_assessment.to_dict() if self.maturity_assessment else None
            ),
            "git_metrics": self.git_metrics.to_dict(),
            "recommended_autonomy": self.recommended_autonomy.value,
            "recommended_profile": self.recommended_profile.value,
            "recommended_organism_level": int(self.recommended_organism_level),
            "recommended_organism_name": self.recommended_organism_level.name,
            "team_archetype": self.team_archetype.value,
            "onboarded_at": self.onboarded_at,
            "warnings": self.warnings,
        }


class RepoOnboardingAgent:
    """
    Phase 0 onboarding agent for new repositories.

    Runs SystemMaturityScorer, detects team archetype from git history,
    and produces recommendations for autonomy level, profile, and
    organism level defaults.

    Usage:
        agent = RepoOnboardingAgent(
            project_id="my-repo",
            workspace_path="/efs/workspaces/my-repo",
            metrics_table="fde-dev-metrics",
        )
        result = agent.run_onboarding()
        # result.recommended_autonomy -> AutonomyRecommendation.MAX_L4
        # result.recommended_profile -> OnboardingProfile.STANDARD
    """

    def __init__(
        self,
        project_id: str,
        workspace_path: str,
        metrics_table: str | None = None,
    ):
        self._project_id = project_id
        self._workspace_path = Path(workspace_path)
        self._metrics_table = metrics_table or os.environ.get(
            "METRICS_TABLE", "fde-dev-metrics"
        )
        self._dynamodb = boto3.resource("dynamodb")
        self._scorer = SystemMaturityScorer(
            project_id=project_id,
            metrics_table=self._metrics_table,
        )
        self._ladder = OrganismLadder(
            project_id=project_id,
            table_name=os.environ.get("ORGANISM_TABLE", ""),
        )

    @property
    def project_id(self) -> str:
        """The project ID being onboarded."""
        return self._project_id

    @property
    def workspace_path(self) -> Path:
        """The workspace path for the repository."""
        return self._workspace_path

    def run_onboarding(self) -> OnboardingResult:
        """
        Execute the full onboarding assessment pipeline.

        Steps:
          1. Extract git history metrics
          2. Score DORA capabilities using SystemMaturityScorer
          3. Detect team archetype from git patterns
          4. Compute recommendations (autonomy, profile, organism level)
          5. Persist results to DynamoDB

        Returns:
            OnboardingResult with all recommendations and assessment data.
        """
        logger.info(
            "Starting onboarding: project=%s workspace=%s",
            self._project_id,
            self._workspace_path,
        )

        result = OnboardingResult(project_id=self._project_id)

        # Step 1: Extract git history metrics
        git_metrics = self._extract_git_metrics()
        result.git_metrics = git_metrics

        # Step 2: Score DORA capabilities
        maturity = self._run_maturity_scoring(git_metrics)
        result.maturity_assessment = maturity

        # Step 3: Detect team archetype
        archetype = self._detect_team_archetype(git_metrics, maturity)
        result.team_archetype = archetype

        # Step 4: Compute recommendations
        result.recommended_autonomy = self._recommend_autonomy(maturity)
        result.recommended_profile = self._recommend_profile(maturity, git_metrics)
        result.recommended_organism_level = self._recommend_organism_level(
            maturity, git_metrics
        )

        # Step 5: Set organism level default
        self._ladder.set_project_default_level(
            result.recommended_organism_level,
            reason=f"Onboarding assessment: archetype={archetype.value}",
        )

        # Step 6: Persist results
        self._persist_onboarding_result(result)

        logger.info(
            "Onboarding complete: project=%s autonomy=%s profile=%s organism=%s archetype=%s",
            self._project_id,
            result.recommended_autonomy.value,
            result.recommended_profile.value,
            result.recommended_organism_level.name,
            result.team_archetype.value,
        )
        return result

    # ------------------------------------------------------------------
    # Git history analysis
    # ------------------------------------------------------------------

    def _extract_git_metrics(self) -> GitHistoryMetrics:
        """Extract team metrics from git history in the workspace."""
        metrics = GitHistoryMetrics()

        if not self._workspace_path.exists():
            logger.warning("Workspace path does not exist: %s", self._workspace_path)
            return metrics

        git_dir = self._workspace_path / ".git"
        if not git_dir.exists():
            logger.warning("No .git directory found in workspace: %s", self._workspace_path)
            return metrics

        try:
            metrics.total_commits_30d = self._count_commits_last_30d()
            metrics.commits_per_week = metrics.total_commits_30d / 4.3
            metrics.active_contributors = self._count_active_contributors()
            metrics.branch_count = self._count_branches()
            metrics.uses_trunk_based = self._detect_trunk_based()
            metrics.avg_pr_size_lines = self._estimate_avg_pr_size()
            metrics.merge_commit_ratio = self._compute_merge_ratio()
        except Exception as e:
            logger.warning("Error extracting git metrics: %s", e)

        return metrics

    def _count_commits_last_30d(self) -> int:
        """Count commits in the last 30 days."""
        try:
            result = subprocess.run(
                ["git", "rev-list", "--count", "--since=30.days", "HEAD"],
                cwd=str(self._workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                return int(result.stdout.strip())
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass
        return 0

    def _count_active_contributors(self) -> int:
        """Count unique contributors in the last 30 days."""
        try:
            result = subprocess.run(
                ["git", "shortlog", "-sn", "--since=30.days", "HEAD"],
                cwd=str(self._workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                return len(lines)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return 0

    def _count_branches(self) -> int:
        """Count remote branches."""
        try:
            result = subprocess.run(
                ["git", "branch", "-r"],
                cwd=str(self._workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                lines = [l.strip() for l in result.stdout.strip().split("\n") if l.strip()]
                return len(lines)
        except (subprocess.TimeoutExpired, OSError):
            pass
        return 0

    def _detect_trunk_based(self) -> bool:
        """
        Detect if the repo uses trunk-based development.

        Heuristic: trunk-based if branch count is low relative to
        contributor count, and most commits are on main/master.
        """
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "--first-parent", "-20", "HEAD"],
                cwd=str(self._workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if len(lines) >= 10:
                    return self._compute_merge_ratio() < 0.3
        except (subprocess.TimeoutExpired, OSError):
            pass
        return False

    def _estimate_avg_pr_size(self) -> int:
        """
        Estimate average PR size from merge commits.

        Uses diffstat of merge commits to approximate PR size.
        """
        try:
            result = subprocess.run(
                [
                    "git", "log", "--merges", "--since=30.days",
                    "--pretty=format:%H", "-10",
                ],
                cwd=str(self._workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0 or not result.stdout.strip():
                return 0

            merge_shas = result.stdout.strip().split("\n")
            total_lines = 0
            count = 0

            for sha in merge_shas[:10]:
                diff_result = subprocess.run(
                    ["git", "diff", "--shortstat", f"{sha}^..{sha}"],
                    cwd=str(self._workspace_path),
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if diff_result.returncode == 0 and diff_result.stdout.strip():
                    parts = diff_result.stdout.strip().split(",")
                    for part in parts:
                        part = part.strip()
                        if "insertion" in part:
                            total_lines += int(part.split()[0])
                        elif "deletion" in part:
                            total_lines += int(part.split()[0])
                    count += 1

            return total_lines // count if count > 0 else 0
        except (subprocess.TimeoutExpired, ValueError, OSError):
            return 0

    def _compute_merge_ratio(self) -> float:
        """Compute ratio of merge commits to total commits (last 30 days)."""
        try:
            total_result = subprocess.run(
                ["git", "rev-list", "--count", "--since=30.days", "HEAD"],
                cwd=str(self._workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            merge_result = subprocess.run(
                ["git", "rev-list", "--count", "--merges", "--since=30.days", "HEAD"],
                cwd=str(self._workspace_path),
                capture_output=True,
                text=True,
                timeout=30,
            )
            if total_result.returncode == 0 and merge_result.returncode == 0:
                total = int(total_result.stdout.strip())
                merges = int(merge_result.stdout.strip())
                return merges / total if total > 0 else 0.0
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass
        return 0.0

    # ------------------------------------------------------------------
    # Maturity scoring
    # ------------------------------------------------------------------

    def _run_maturity_scoring(self, git_metrics: GitHistoryMetrics) -> MaturityAssessment:
        """
        Run SystemMaturityScorer with evidence from git metrics.

        Maps git metrics to DORA capability scores:
          C4 (Version Control): branch protection, trunk-based, CI presence
          C5 (Small Batches): avg PR size, commit frequency
        """
        # C4: Version Control maturity
        c4_score = self._score_version_control(git_metrics)
        c4_evidence = []
        if git_metrics.uses_trunk_based:
            c4_evidence.append("trunk-based development detected")
        if git_metrics.branch_count > 0:
            c4_evidence.append(f"{git_metrics.branch_count} remote branches")
        c4_evidence.append(f"{git_metrics.active_contributors} active contributors")
        self._scorer.score_capability(
            DoraCapability.C4_VERSION_CONTROL, c4_score, evidence=c4_evidence
        )

        # C5: Small Batches
        c5_score = self._score_small_batches(git_metrics)
        c5_evidence = []
        if git_metrics.avg_pr_size_lines > 0:
            c5_evidence.append(f"avg PR size: {git_metrics.avg_pr_size_lines} lines")
        c5_evidence.append(f"{git_metrics.commits_per_week:.1f} commits/week")
        self._scorer.score_capability(
            DoraCapability.C5_SMALL_BATCHES, c5_score, evidence=c5_evidence
        )

        # C1: AI Stance
        c1_score = self._score_ai_stance()
        self._scorer.score_capability(
            DoraCapability.C1_AI_STANCE, c1_score,
            evidence=["Checked for AI policy documentation"],
        )

        # C2: Data Ecosystems
        c2_score = self._score_data_ecosystems()
        self._scorer.score_capability(
            DoraCapability.C2_DATA_ECOSYSTEMS, c2_score,
            evidence=["Checked for data pipeline configuration"],
        )

        # C3: AI-Accessible Data
        c3_score = self._score_ai_accessible_data()
        self._scorer.score_capability(
            DoraCapability.C3_AI_ACCESSIBLE_DATA, c3_score,
            evidence=["Checked for structured data artifacts"],
        )

        # C6: User-Centric Focus
        c6_score = self._score_user_centric()
        self._scorer.score_capability(
            DoraCapability.C6_USER_CENTRIC_FOCUS, c6_score,
            evidence=["Checked for user value documentation"],
        )

        # C7: Quality Platforms
        c7_score = self._score_quality_platforms()
        self._scorer.score_capability(
            DoraCapability.C7_QUALITY_PLATFORMS, c7_score,
            evidence=["Checked for CI/CD and platform configuration"],
        )

        return self._scorer.compute_assessment()

    def _score_version_control(self, git_metrics: GitHistoryMetrics) -> int:
        """Score C4 based on git metrics."""
        score = 30  # Base score for having git

        if git_metrics.uses_trunk_based:
            score += 25
        if git_metrics.active_contributors >= 3:
            score += 15
        elif git_metrics.active_contributors >= 2:
            score += 10

        # Check for CI configuration
        ci_files = [
            ".github/workflows",
            ".gitlab-ci.yml",
            "Jenkinsfile",
            "buildspec.yml",
        ]
        for ci_file in ci_files:
            if (self._workspace_path / ci_file).exists():
                score += 20
                break

        # Check for branch protection indicators
        protection_files = [
            "CODEOWNERS",
            ".github/CODEOWNERS",
            ".github/pull_request_template.md",
        ]
        for pf in protection_files:
            if (self._workspace_path / pf).exists():
                score += 10
                break

        return min(100, score)

    def _score_small_batches(self, git_metrics: GitHistoryMetrics) -> int:
        """Score C5 based on PR size and commit frequency."""
        score = 20  # Base score

        if git_metrics.avg_pr_size_lines > 0:
            if git_metrics.avg_pr_size_lines <= 100:
                score += 35
            elif git_metrics.avg_pr_size_lines <= 200:
                score += 25
            elif git_metrics.avg_pr_size_lines <= 400:
                score += 15
            else:
                score += 5

        if git_metrics.commits_per_week >= 20:
            score += 30
        elif git_metrics.commits_per_week >= 10:
            score += 20
        elif git_metrics.commits_per_week >= 5:
            score += 15
        elif git_metrics.commits_per_week >= 2:
            score += 10

        return min(100, score)

    def _score_ai_stance(self) -> int:
        """Score C1 by checking for AI policy documentation."""
        score = 10
        ai_indicators = [
            "docs/ai-policy.md",
            "docs/ai-usage.md",
            ".ai-policy",
            "AI_POLICY.md",
            "docs/adr",
        ]
        for indicator in ai_indicators:
            if (self._workspace_path / indicator).exists():
                score += 20

        return min(100, score)

    def _score_data_ecosystems(self) -> int:
        """Score C2 by checking for data pipeline indicators."""
        score = 10
        data_indicators = [
            "data/",
            "pipelines/",
            "dbt_project.yml",
            "airflow/",
            "glue/",
            "etl/",
        ]
        for indicator in data_indicators:
            if (self._workspace_path / indicator).exists():
                score += 20

        return min(100, score)

    def _score_ai_accessible_data(self) -> int:
        """Score C3 by checking for labeled/versioned data artifacts."""
        score = 10
        data_artifacts = [
            "schema/",
            "contracts/",
            "openapi.yaml",
            "openapi.json",
            "swagger.yaml",
            "docs/data-dictionary.md",
        ]
        for artifact in data_artifacts:
            if (self._workspace_path / artifact).exists():
                score += 20

        return min(100, score)

    def _score_user_centric(self) -> int:
        """Score C6 by checking for user value documentation."""
        score = 10
        user_indicators = [
            "docs/user-stories/",
            "docs/personas/",
            "docs/user-research/",
            "docs/product/",
            "USER_STORIES.md",
        ]
        for indicator in user_indicators:
            if (self._workspace_path / indicator).exists():
                score += 20

        return min(100, score)

    def _score_quality_platforms(self) -> int:
        """Score C7 by checking for platform tooling."""
        score = 10
        platform_indicators = [
            "Makefile",
            "Dockerfile",
            "docker-compose.yml",
            "docker-compose.yaml",
            "infra/",
            "terraform/",
            "cdk.json",
            "serverless.yml",
        ]
        for indicator in platform_indicators:
            if (self._workspace_path / indicator).exists():
                score += 15

        return min(100, score)

    # ------------------------------------------------------------------
    # Team archetype detection
    # ------------------------------------------------------------------

    def _detect_team_archetype(
        self,
        git_metrics: GitHistoryMetrics,
        maturity: MaturityAssessment,
    ) -> TeamArchetype:
        """
        Detect team archetype from git history patterns.

        Combines git metrics with maturity assessment to classify:
          - Starting: Low activity, few contributors, no CI
          - Flowing: Regular commits, some structure
          - Accelerating: High frequency, small PRs, trunk-based
          - Thriving: All indicators strong
        """
        archetype = maturity.team_archetype

        # Override with git-specific signals if they tell a different story
        if (
            git_metrics.commits_per_week >= 15
            and git_metrics.uses_trunk_based
            and git_metrics.avg_pr_size_lines <= 200
            and git_metrics.active_contributors >= 3
        ):
            if archetype.value in ("starting", "flowing"):
                archetype = TeamArchetype.ACCELERATING

        elif (
            git_metrics.commits_per_week < 2
            and git_metrics.active_contributors <= 1
        ):
            archetype = TeamArchetype.STARTING

        return archetype

    # ------------------------------------------------------------------
    # Recommendations
    # ------------------------------------------------------------------

    def _recommend_autonomy(self, maturity: MaturityAssessment) -> AutonomyRecommendation:
        """Map maturity assessment to autonomy recommendation."""
        return maturity.autonomy_recommendation

    def _recommend_profile(
        self,
        maturity: MaturityAssessment,
        git_metrics: GitHistoryMetrics,
    ) -> OnboardingProfile:
        """
        Recommend factory profile based on maturity and team size.

        Profiles:
          - starter: composite < 40 or single contributor
          - standard: composite 40-70 or small team (2-5)
          - full: composite > 70 and team >= 3
        """
        composite = maturity.composite_score

        if composite > 70 and git_metrics.active_contributors >= 3:
            return OnboardingProfile.FULL
        elif composite >= 40 or git_metrics.active_contributors >= 2:
            return OnboardingProfile.STANDARD
        else:
            return OnboardingProfile.STARTER

    def _recommend_organism_level(
        self,
        maturity: MaturityAssessment,
        git_metrics: GitHistoryMetrics,
    ) -> OrganismLevel:
        """
        Recommend default organism level for task classification.

        Mapping:
          - starter profile -> O2 (Adaptive): single agent + memory
          - standard profile -> O3 (Cognitive): multi-agent squad
          - full profile -> O4 (Reflective): full squad + fidelity
        """
        composite = maturity.composite_score

        if composite > 70 and git_metrics.active_contributors >= 3:
            return OrganismLevel.O4_REFLECTIVE
        elif composite >= 40:
            return OrganismLevel.O3_COGNITIVE
        else:
            return OrganismLevel.O2_ADAPTIVE

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _persist_onboarding_result(self, result: OnboardingResult) -> None:
        """Persist onboarding result to DynamoDB metrics table."""
        if not self._metrics_table:
            return

        table = self._dynamodb.Table(self._metrics_table)
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        try:
            table.put_item(
                Item={
                    "project_id": self._project_id,
                    "metric_key": f"onboarding#{self._project_id}#{date_str}",
                    "metric_type": "onboarding_result",
                    "recorded_at": result.onboarded_at,
                    "data": json.dumps(result.to_dict()),
                }
            )
            logger.info(
                "Persisted onboarding result: project=%s", self._project_id
            )
        except ClientError as e:
            logger.warning("Failed to persist onboarding result: %s", e)
