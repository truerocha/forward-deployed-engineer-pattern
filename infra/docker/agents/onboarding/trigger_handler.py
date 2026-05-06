"""
Trigger Handler — Receives onboarding event, validates input, determines
execution mode, creates isolated workspace, and initiates the pipeline.

Design ref: §3.1 Trigger Handler
"""

import logging
import os
import re
import sqlite3
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("fde-onboarding.trigger_handler")

# Supported Git hosts (allowlist for input validation)
ALLOWED_HOSTS = {
    "github.com",
    "gitlab.com",
    "bitbucket.org",
}

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@dataclass
class TriggerContext:
    """Output of the Trigger Handler — consumed by all downstream stages."""

    correlation_id: str
    mode: str  # "cloud" | "local"
    workspace_path: str
    catalog_path: str
    repo_url: Optional[str]
    repo_owner: str
    repo_name: str
    clone_depth: int
    force_full_scan: bool
    skip_scan: bool  # True if catalog exists and commit unchanged


class TriggerValidationError(Exception):
    """Raised when trigger input fails validation."""


def handle_trigger(
    repo_url: Optional[str] = None,
    clone_depth: int = 1,
    force_full_scan: bool = False,
    correlation_id: Optional[str] = None,
    enterprise_hosts: Optional[set[str]] = None,
) -> TriggerContext:
    """
    Process the onboarding trigger event and produce a TriggerContext.

    Args:
        repo_url: Repository URL (None for local mode).
        clone_depth: Git clone depth (positive int, max 100).
        force_full_scan: Skip incremental check, force full scan.
        correlation_id: Optional override UUID (generated if not provided).
        enterprise_hosts: Additional allowed Git hosts beyond the default set.

    Returns:
        TriggerContext with all fields populated.

    Raises:
        TriggerValidationError: If input validation fails.
    """
    # Generate or validate correlation ID
    if correlation_id:
        if not UUID_PATTERN.match(correlation_id):
            raise TriggerValidationError(
                f"Invalid correlation_id format (must be UUID v4): {correlation_id}"
            )
    else:
        correlation_id = str(uuid.uuid4())

    # Validate clone_depth
    if not isinstance(clone_depth, int) or clone_depth < 1 or clone_depth > 100:
        raise TriggerValidationError(
            f"clone_depth must be a positive integer (1-100), got: {clone_depth}"
        )

    # Determine mode
    if not repo_url:
        return _build_local_context(correlation_id, force_full_scan)

    # Validate repo_url
    owner, name = _validate_repo_url(repo_url, enterprise_hosts)

    # Cloud mode: create isolated workspace
    workspace_path = os.path.join(tempfile.gettempdir(), f"onboard-{correlation_id}")
    os.makedirs(workspace_path, exist_ok=True)

    catalog_path = f"catalogs/{owner}/{name}/catalog.db"

    # Incremental check (REQ-4.3)
    skip_scan = False
    if not force_full_scan:
        skip_scan = _check_incremental_skip(catalog_path, repo_url)

    return TriggerContext(
        correlation_id=correlation_id,
        mode="cloud",
        workspace_path=workspace_path,
        catalog_path=catalog_path,
        repo_url=repo_url,
        repo_owner=owner,
        repo_name=name,
        clone_depth=clone_depth,
        force_full_scan=force_full_scan,
        skip_scan=skip_scan,
    )


def _build_local_context(correlation_id: str, force_full_scan: bool) -> TriggerContext:
    """Build TriggerContext for local mode (no clone, scan cwd)."""
    workspace_path = os.getcwd()
    catalog_path = os.path.join(workspace_path, "catalog.db")

    # Try to infer repo owner/name from git remote
    owner, name = _infer_local_repo_identity(workspace_path)

    # Incremental check for local mode
    skip_scan = False
    if not force_full_scan and os.path.exists(catalog_path):
        skip_scan = _check_local_incremental_skip(catalog_path, workspace_path)

    return TriggerContext(
        correlation_id=correlation_id,
        mode="local",
        workspace_path=workspace_path,
        catalog_path=catalog_path,
        repo_url=None,
        repo_owner=owner,
        repo_name=name,
        clone_depth=1,
        force_full_scan=force_full_scan,
        skip_scan=skip_scan,
    )


def _validate_repo_url(repo_url: str, enterprise_hosts: Optional[set[str]] = None) -> tuple[str, str]:
    """
    Validate repo URL against allowlist and extract owner/name.

    Returns:
        Tuple of (owner, repo_name).

    Raises:
        TriggerValidationError if URL is invalid or host not allowed.
    """
    parsed = urlparse(repo_url)
    if parsed.scheme not in ("https", "http", "ssh", "git"):
        raise TriggerValidationError(f"Unsupported URL scheme: {parsed.scheme}")

    host = parsed.hostname or ""
    allowed = ALLOWED_HOSTS | (enterprise_hosts or set())
    if host not in allowed:
        raise TriggerValidationError(
            f"Host '{host}' not in allowed hosts: {sorted(allowed)}"
        )

    # Extract owner/name from path (e.g., /org/repo or /org/repo.git)
    path_parts = [p for p in parsed.path.strip("/").split("/") if p]
    if len(path_parts) < 2:
        raise TriggerValidationError(
            f"Cannot extract owner/repo from URL path: {parsed.path}"
        )

    owner = path_parts[0]
    name = path_parts[1].removesuffix(".git")
    return owner, name


def _infer_local_repo_identity(workspace_path: str) -> tuple[str, str]:
    """Infer repo owner/name from git remote origin URL."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=workspace_path,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            remote_url = result.stdout.strip()
            # Handle SSH format: git@github.com:owner/repo.git
            if ":" in remote_url and "@" in remote_url:
                path_part = remote_url.split(":")[-1]
                parts = path_part.strip("/").removesuffix(".git").split("/")
                if len(parts) >= 2:
                    return parts[0], parts[1]
            # Handle HTTPS format
            try:
                return _validate_repo_url(remote_url, None)
            except TriggerValidationError:
                pass
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass

    # Fallback: use directory name
    dir_name = os.path.basename(os.path.abspath(workspace_path))
    return "local", dir_name


def _check_incremental_skip(catalog_s3_path: str, repo_url: str) -> bool:
    """
    Check if the remote catalog's commit SHA matches the repo's current HEAD.

    In cloud mode, this requires downloading the catalog from S3 first.
    For now, returns False (full scan) — the actual S3 check is done by
    the pipeline orchestrator which has access to the S3 client.
    """
    # Incremental skip in cloud mode is handled by the pipeline orchestrator
    # after downloading the existing catalog. This is a placeholder.
    return False


def _check_local_incremental_skip(catalog_path: str, workspace_path: str) -> bool:
    """Check if local catalog's commit SHA matches current HEAD."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=workspace_path,
            timeout=5,
        )
        if result.returncode != 0:
            return False

        current_sha = result.stdout.strip()

        conn = sqlite3.connect(catalog_path)
        try:
            row = conn.execute("SELECT commit_sha FROM repos LIMIT 1").fetchone()
            if row and row[0] == current_sha:
                logger.info(
                    "Incremental skip: catalog commit %s matches HEAD", current_sha[:8]
                )
                return True
        finally:
            conn.close()
    except (subprocess.TimeoutExpired, FileNotFoundError, sqlite3.Error) as e:
        logger.debug("Incremental check failed (will do full scan): %s", e)

    return False


def parse_eventbridge_event(event: dict) -> dict:
    """
    Parse an EventBridge event into trigger handler kwargs.

    Expected event shape (§5.1):
        {
            "source": "fde.onboarding",
            "detail-type": "fde.onboarding.requested",
            "detail": {
                "repo_url": "https://github.com/org/repo",
                "clone_depth": 1,
                "force_full_scan": false,
                "correlation_id": "optional-uuid"
            }
        }
    """
    detail = event.get("detail", {})
    return {
        "repo_url": detail.get("repo_url"),
        "clone_depth": detail.get("clone_depth", 1),
        "force_full_scan": detail.get("force_full_scan", False),
        "correlation_id": detail.get("correlation_id"),
    }
