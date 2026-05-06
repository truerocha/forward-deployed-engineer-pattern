"""
Status Sync — Posts structured progress comments to the originating GitHub issue
as the agent moves through pipeline stages.

Design ref: ADR-006 (Enterprise ALM Integration)
Security: Comments NEVER expose internal architecture, error traces, or secrets.
Only stage name, status, duration, and outcome are visible.

Usage:
    from agents.status_sync import StatusSync

    sync = StatusSync(issue_url="https://github.com/org/repo/issues/123", environment="dev")
    sync.post_stage_start("reconnaissance")
    sync.post_stage_complete("reconnaissance", duration_ms=12000)
    sync.post_pipeline_complete(pr_url="https://github.com/org/repo/pull/45")
    sync.post_pipeline_failed(stage="engineering", reason="Test failures in module X")
"""

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import boto3

logger = logging.getLogger("fde-agent.status_sync")

# Stage display names and emojis (PM-friendly)
STAGE_DISPLAY = {
    "reconnaissance": ("📋", "Reconnaissance"),
    "intake": ("📝", "Task Intake"),
    "engineering": ("⚙️", "Engineering"),
    "testing": ("🧪", "Testing"),
    "review": ("🔍", "Review"),
    "completion": ("📦", "Completion"),
    "reporting": ("📊", "Reporting"),
}

TEMPLATE_STAGE_START = """{emoji} **{stage_name}** — Started

| Field | Value |
|-------|-------|
| Stage | {stage_name} |
| Started | {timestamp} |
| Correlation | `{correlation_id}` |

---
_Automated by Code Factory_"""

TEMPLATE_STAGE_COMPLETE = """{emoji} **{stage_name}** — Complete ✓

| Field | Value |
|-------|-------|
| Stage | {stage_name} |
| Duration | {duration} |
| Status | ✅ Passed |

---
_Automated by Code Factory_"""

TEMPLATE_PIPELINE_COMPLETE = """🎉 **Pipeline Complete**

| Field | Value |
|-------|-------|
| Total Duration | {total_duration} |
| Stages Passed | {stages_passed} |
| Pull Request | {pr_link} |
| Status | ✅ Ready for Review |

The agent has opened a PR for your review. Please check the changes and approve if satisfied.

---
_Automated by Code Factory_"""

TEMPLATE_PIPELINE_FAILED = """⚠️ **Pipeline Failed**

| Field | Value |
|-------|-------|
| Failed Stage | {failed_stage} |
| Reason | {reason} |
| Stages Completed | {stages_completed} |
| Status | ❌ Needs Attention |

The Staff Engineer has been notified. This issue will be retried or escalated.

---
_Automated by Code Factory_"""


class StatusSync:
    """Posts structured progress comments to GitHub issues."""

    def __init__(
        self,
        issue_url: str,
        correlation_id: str = "",
        environment: str = "dev",
        aws_region: str = "us-east-1",
    ):
        self.issue_url = issue_url
        self.correlation_id = correlation_id
        self.environment = environment
        self.aws_region = aws_region
        self._owner, self._repo, self._issue_number = self._parse_issue_url(issue_url)
        self._stages_completed: list[str] = []
        self._pipeline_start = datetime.now(timezone.utc)

    def post_stage_start(self, stage: str) -> bool:
        """Post a comment when a pipeline stage starts."""
        emoji, display_name = STAGE_DISPLAY.get(stage, ("▶️", stage.title()))
        body = TEMPLATE_STAGE_START.format(
            emoji=emoji,
            stage_name=display_name,
            timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            correlation_id=self.correlation_id[:8] if self.correlation_id else "—",
        )
        return self._post_comment(body)

    def post_stage_complete(self, stage: str, duration_ms: int = 0) -> bool:
        """Post a comment when a pipeline stage completes."""
        emoji, display_name = STAGE_DISPLAY.get(stage, ("✅", stage.title()))
        self._stages_completed.append(display_name)
        body = TEMPLATE_STAGE_COMPLETE.format(
            emoji=emoji,
            stage_name=display_name,
            duration=self._format_duration(duration_ms),
        )
        return self._post_comment(body)

    def post_pipeline_complete(self, pr_url: str = "") -> bool:
        """Post a comment when the full pipeline completes successfully."""
        total_ms = int((datetime.now(timezone.utc) - self._pipeline_start).total_seconds() * 1000)
        pr_link = f"[#{pr_url.split('/')[-1]}]({pr_url})" if pr_url else "—"
        body = TEMPLATE_PIPELINE_COMPLETE.format(
            total_duration=self._format_duration(total_ms),
            stages_passed=len(self._stages_completed),
            pr_link=pr_link,
        )
        return self._post_comment(body)

    def post_pipeline_failed(self, stage: str, reason: str) -> bool:
        """Post a comment when the pipeline fails."""
        _, display_name = STAGE_DISPLAY.get(stage, ("", stage.title()))
        safe_reason = self._sanitize_reason(reason)
        body = TEMPLATE_PIPELINE_FAILED.format(
            failed_stage=display_name,
            reason=safe_reason,
            stages_completed=len(self._stages_completed),
        )
        return self._post_comment(body)

    def _post_comment(self, body: str) -> bool:
        """Post a comment to the GitHub issue via the GitHub API."""
        token = self._fetch_token()
        if not token:
            logger.warning("No GitHub token available — skipping status sync")
            return False

        import urllib.request

        url = f"https://api.github.com/repos/{self._owner}/{self._repo}/issues/{self._issue_number}/comments"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        data = json.dumps({"body": body}).encode("utf-8")

        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            response = urllib.request.urlopen(req, timeout=10)
            if response.status in (200, 201):
                logger.info("Status comment posted to %s/issues/%s", self._repo, self._issue_number)
                return True
            else:
                logger.warning("GitHub API returned %d", response.status)
                return False
        except Exception as e:
            logger.error("Failed to post status comment: %s", e)
            return False

    def _fetch_token(self) -> Optional[str]:
        """Fetch GitHub PAT from Secrets Manager (ADR-014 pattern)."""
        try:
            client = boto3.client("secretsmanager", region_name=self.aws_region)
            response = client.get_secret_value(
                SecretId=f"fde-{self.environment}/alm-tokens"
            )
            secrets = json.loads(response["SecretString"])
            token = secrets.get("github_pat", "")
            if token and not token.startswith("placeholder"):
                return token
        except Exception as e:
            logger.debug("Secrets Manager unavailable: %s", e)

        return os.environ.get("GITHUB_TOKEN", "")

    def _sanitize_reason(self, reason: str) -> str:
        """
        Remove internal details from failure reasons.

        SECURITY: Never expose file paths, stack traces, module names,
        or internal architecture details in public comments.
        """
        reason = re.sub(r"/[\w/.-]+\.\w+", "[internal]", reason)
        reason = re.sub(r"File \".*\".*line \d+.*", "", reason)
        reason = re.sub(r"Traceback \(most recent.*\):", "", reason)
        if len(reason) > 200:
            reason = reason[:197] + "..."
        return reason.strip() or "Internal error — Staff Engineer notified"

    @staticmethod
    def _parse_issue_url(url: str) -> tuple[str, str, str]:
        """Parse owner, repo, and issue number from a GitHub issue URL."""
        parsed = urlparse(url)
        parts = [p for p in parsed.path.strip("/").split("/") if p]
        if len(parts) >= 4 and parts[2] == "issues":
            return parts[0], parts[1], parts[3]
        raise ValueError(f"Cannot parse GitHub issue URL: {url}")

    @staticmethod
    def _format_duration(ms: int) -> str:
        """Format milliseconds into human-readable duration."""
        if ms < 1000:
            return f"{ms}ms"
        seconds = ms / 1000
        if seconds < 60:
            return f"{seconds:.1f}s"
        minutes = seconds / 60
        return f"{minutes:.1f}min"
