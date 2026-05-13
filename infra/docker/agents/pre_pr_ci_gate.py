"""
Pre-PR CI Gate — Mandatory CI Validation Before PR Submission.

Origin: COE-130 — PR #129 submitted with 14 pre-existing CI failures undetected.

This module enforces that the AI Squad MUST validate the full CI test suite
passes on the branch BEFORE creating a Pull Request. A PR with a red CI gate
is an automatic rejection.

The gate:
  1. Discovers CI commands from workflow files (.github/workflows/, .gitlab-ci.yml)
  2. Runs the full CI suite locally on the branch
  3. Triages failures (caused by PR vs pre-existing)
  4. Blocks PR creation if any required gate fails
  5. Reports structured feedback for rework if blocked

Integration:
  - Called by DTL Committer agent BEFORE `gh pr create` or `git push`
  - If gate fails: agent must fix failures before submitting
  - If pre-existing failures: agent must fix them OR escalate (never submit red)
  - Feeds into Verification Reward Gate (ADR-027) as a pre-PR signal

Feature flag: PRE_PR_CI_GATE_ENABLED (default: true)
Ref: docs/governance/pre-pr-ci-validation.md
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("fde.agents.pre_pr_ci_gate")

_PRE_PR_CI_GATE_ENABLED = os.environ.get("PRE_PR_CI_GATE_ENABLED", "true").lower() == "true"
_CI_TIMEOUT_SECONDS = 300
_MAX_OUTPUT_CHARS = 5000


@dataclass
class CICommand:
    """A single CI command discovered from workflow files."""
    command: str
    source_file: str
    job_name: str
    required: bool


@dataclass
class CIFailure:
    """A single CI test failure."""
    command: str
    exit_code: int
    output: str
    error_summary: str
    is_pre_existing: bool = False


@dataclass
class PrePRValidationResult:
    """Result of the pre-PR CI validation gate."""
    passed: bool
    commands_run: int
    commands_passed: int
    commands_failed: int
    failures: list[CIFailure] = field(default_factory=list)
    pre_existing_count: int = 0
    duration_seconds: float = 0.0
    blocked_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "commands_run": self.commands_run,
            "commands_passed": self.commands_passed,
            "commands_failed": self.commands_failed,
            "pre_existing_count": self.pre_existing_count,
            "duration_seconds": round(self.duration_seconds, 2),
            "blocked_reason": self.blocked_reason,
            "failures": [
                {"command": f.command, "exit_code": f.exit_code,
                 "error_summary": f.error_summary[:500], "is_pre_existing": f.is_pre_existing}
                for f in self.failures
            ],
        }

    def to_feedback(self) -> str:
        """Format as structured feedback for the agent to fix."""
        if self.passed:
            return ""
        parts = [
            f"PRE-PR CI GATE: BLOCKED ({self.commands_failed} command(s) failed)",
            "You MUST fix these before submitting the PR.", "",
        ]
        for f in self.failures:
            prefix = "[PRE-EXISTING] " if f.is_pre_existing else ""
            parts.append(f"{prefix}Command: {f.command}")
            parts.append(f"  Exit code: {f.exit_code}")
            parts.append(f"  Error: {f.error_summary[:300]}")
            parts.append("")
        if self.pre_existing_count > 0:
            parts.append(
                f"NOTE: {self.pre_existing_count} failure(s) are pre-existing on main. "
                "You must still fix them (Option A: fix in your PR, Option B: prerequisite PR)."
            )
        return "\n".join(parts)


class PrePRCIGate:
    """
    Mandatory CI validation gate before PR submission.

    Discovers CI commands from workflow files, runs them locally,
    and blocks PR creation if any required gate fails.

    Usage:
        gate = PrePRCIGate(repo_path="/path/to/repo")
        result = gate.validate()
        if not result.passed:
            print(result.to_feedback())
            # Agent must fix before submitting
    """

    def __init__(self, repo_path: str = "", timeout_seconds: int = _CI_TIMEOUT_SECONDS):
        self._repo_path = repo_path or os.environ.get("WORKSPACE_PATH", ".")
        self._timeout = timeout_seconds

    @property
    def enabled(self) -> bool:
        return _PRE_PR_CI_GATE_ENABLED

    def validate(self) -> PrePRValidationResult:
        """Run the full pre-PR CI validation."""
        if not self.enabled:
            return PrePRValidationResult(
                passed=True, commands_run=0, commands_passed=0, commands_failed=0,
                blocked_reason="Gate disabled",
            )

        start = time.time()
        commands = self.discover_ci_commands()

        if not commands:
            logger.warning("No CI commands discovered — passing with warning")
            return PrePRValidationResult(
                passed=True, commands_run=0, commands_passed=0, commands_failed=0,
                blocked_reason="No CI commands found",
            )

        failures: list[CIFailure] = []
        passed_count = 0

        for cmd in commands:
            if not cmd.required:
                continue
            result = self._run_command(cmd.command)
            if result is None:
                passed_count += 1
            else:
                failures.append(result)

        pre_existing_count = 0
        for failure in failures:
            if self._is_pre_existing(failure.command):
                failure.is_pre_existing = True
                pre_existing_count += 1

        duration = time.time() - start
        passed = len(failures) == 0

        result = PrePRValidationResult(
            passed=passed,
            commands_run=passed_count + len(failures),
            commands_passed=passed_count,
            commands_failed=len(failures),
            failures=failures,
            pre_existing_count=pre_existing_count,
            duration_seconds=duration,
            blocked_reason="" if passed else f"{len(failures)} CI command(s) failed",
        )

        if passed:
            logger.info("Pre-PR CI gate PASSED: %d commands, %.1fs", result.commands_run, duration)
        else:
            logger.warning("Pre-PR CI gate BLOCKED: %d/%d failed, %.1fs", len(failures), result.commands_run, duration)

        return result

    def discover_ci_commands(self) -> list[CICommand]:
        """Discover CI test commands from workflow files."""
        commands: list[CICommand] = []
        repo = Path(self._repo_path)

        # GitHub Actions
        workflows_dir = repo / ".github" / "workflows"
        if workflows_dir.exists():
            for wf_file in workflows_dir.glob("*.yml"):
                commands.extend(self._parse_github_workflow(wf_file))

        # GitLab CI
        gitlab_ci = repo / ".gitlab-ci.yml"
        if gitlab_ci.exists():
            commands.extend(self._parse_gitlab_ci(gitlab_ci))

        # Fallback
        if not commands:
            commands = self._detect_fallback_commands(repo)

        return commands

    def _parse_github_workflow(self, wf_file: Path) -> list[CICommand]:
        """Extract test commands from a GitHub Actions workflow."""
        commands: list[CICommand] = []
        try:
            content = wf_file.read_text()
            if "pull_request" not in content:
                return []

            current_job = ""
            for line in content.split("\n"):
                job_match = re.match(r'^  ([\w-]+):', line)
                if job_match:
                    current_job = job_match.group(1)

                run_match = re.match(r'^\s+run:\s*(.+)$', line)
                if run_match and current_job:
                    cmd = run_match.group(1).strip()
                    if cmd and any(kw in cmd for kw in ["pytest", "test", "lint", "check", "ruff", "mypy"]):
                        is_required = "gate" in current_job or "test" in current_job or "lint" in current_job
                        commands.append(CICommand(
                            command=cmd, source_file=str(wf_file.name),
                            job_name=current_job, required=is_required,
                        ))
        except Exception as e:
            logger.warning("Failed to parse workflow %s: %s", wf_file, e)
        return commands

    def _parse_gitlab_ci(self, ci_file: Path) -> list[CICommand]:
        """Extract test commands from .gitlab-ci.yml."""
        commands: list[CICommand] = []
        try:
            content = ci_file.read_text()
            for line in content.split("\n"):
                stripped = line.strip()
                if stripped.startswith("- ") and any(kw in stripped for kw in ["pytest", "test", "lint"]):
                    cmd = stripped[2:].strip()
                    commands.append(CICommand(command=cmd, source_file=".gitlab-ci.yml", job_name="test", required=True))
        except Exception as e:
            logger.warning("Failed to parse .gitlab-ci.yml: %s", e)
        return commands

    def _detect_fallback_commands(self, repo: Path) -> list[CICommand]:
        """Detect common test commands when no CI config is found."""
        commands: list[CICommand] = []
        if (repo / "tests" / "contracts").exists():
            commands.append(CICommand(command="pytest -q tests/contracts", source_file="auto-detected", job_name="contract-tests", required=True))
        elif (repo / "tests").exists():
            commands.append(CICommand(command="pytest -q tests/", source_file="auto-detected", job_name="tests", required=True))
        if (repo / "scripts" / "run_tests.py").exists():
            commands.append(CICommand(command="python3 scripts/run_tests.py --scope contract", source_file="auto-detected", job_name="contract-tests", required=True))
        return commands

    def _run_command(self, command: str) -> CIFailure | None:
        """Run a CI command. Returns None on success, CIFailure on failure."""
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=self._timeout, cwd=self._repo_path,
            )
            if result.returncode == 0:
                return None
            return CIFailure(
                command=command, exit_code=result.returncode,
                output=result.stdout[:_MAX_OUTPUT_CHARS],
                error_summary=(result.stderr or result.stdout)[:_MAX_OUTPUT_CHARS],
            )
        except subprocess.TimeoutExpired:
            return CIFailure(command=command, exit_code=-1, output="", error_summary=f"TIMEOUT: >{self._timeout}s")
        except Exception as e:
            return CIFailure(command=command, exit_code=-1, output="", error_summary=str(e)[:200])

    def _is_pre_existing(self, command: str) -> bool:
        """Check if a failure also exists on main (pre-existing)."""
        try:
            check_cmd = f"git stash -q 2>/dev/null; git checkout main -q 2>/dev/null && {command} 2>/dev/null; EC=$?; git checkout - -q 2>/dev/null; git stash pop -q 2>/dev/null; exit $EC"
            result = subprocess.run(
                check_cmd, shell=True, capture_output=True, timeout=self._timeout, cwd=self._repo_path,
            )
            return result.returncode != 0
        except Exception:
            return False
