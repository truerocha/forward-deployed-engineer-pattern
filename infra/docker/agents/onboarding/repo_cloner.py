"""
Repo Cloner — Clones target repository using ADR-014 credential isolation.
Skipped entirely in local mode.

Design ref: §3.2 Repo Cloner
"""

import json
import logging
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import boto3

logger = logging.getLogger("fde-onboarding.repo_cloner")


@dataclass
class CloneResult:
    """Output of the Repo Cloner stage."""

    workspace_path: str
    commit_sha: str
    repo_size_bytes: int
    duration_ms: int = 0


class CloneError(Exception):
    """Raised when repository cloning fails."""


def clone_repository(
    repo_url: str,
    workspace_path: str,
    clone_depth: int = 1,
    environment: str = "dev",
    aws_region: str = "us-east-1",
) -> CloneResult:
    """
    Clone a repository with ADR-014 credential isolation.

    The credential flow:
    1. FETCH token from Secrets Manager
    2. USE via GIT_ASKPASS one-shot script
    3. DISCARD token and script immediately after clone

    Args:
        repo_url: Full repository URL.
        workspace_path: Target directory for the clone.
        clone_depth: Shallow clone depth (default 1).
        environment: Deployment environment for secrets path.
        aws_region: AWS region for Secrets Manager.

    Returns:
        CloneResult with workspace path, commit SHA, and size.

    Raises:
        CloneError: If cloning fails.
    """
    start = time.time()

    host = urlparse(repo_url).hostname or ""
    token = _fetch_token(host, environment, aws_region)
    askpass_script = None

    try:
        # Create one-shot GIT_ASKPASS script (ADR-014: fetch-use-discard)
        askpass_script = _create_askpass_script(token)

        # Build clone command
        cmd = ["git", "clone", "--depth", str(clone_depth), repo_url, workspace_path]

        env_vars = {**os.environ, "GIT_ASKPASS": askpass_script}
        # Prevent git from prompting interactively
        env_vars["GIT_TERMINAL_PROMPT"] = "0"

        result = subprocess.run(
            cmd,
            env=env_vars,
            capture_output=True,
            text=True,
            timeout=180,  # 3 minute timeout for clone
        )

        if result.returncode != 0:
            raise CloneError(
                f"git clone failed (exit {result.returncode}): {result.stderr.strip()}"
            )

    finally:
        # DISCARD: Remove askpass script and token reference
        if askpass_script and os.path.exists(askpass_script):
            os.unlink(askpass_script)
        del token  # noqa: F821 — explicit discard

    # Get commit SHA
    commit_sha = _get_head_sha(workspace_path)

    # Calculate repo size
    repo_size_bytes = _calculate_dir_size(workspace_path)

    duration_ms = int((time.time() - start) * 1000)

    logger.info(
        "Clone complete: %s → %s (sha=%s, size=%d bytes, depth=%d, duration=%dms)",
        repo_url,
        workspace_path,
        commit_sha[:8],
        repo_size_bytes,
        clone_depth,
        duration_ms,
    )

    return CloneResult(
        workspace_path=workspace_path,
        commit_sha=commit_sha,
        repo_size_bytes=repo_size_bytes,
        duration_ms=duration_ms,
    )


def get_current_sha(workspace_path: str) -> str:
    """Get the current HEAD SHA for a workspace (works in both modes)."""
    return _get_head_sha(workspace_path)


def _fetch_token(host: str, environment: str, aws_region: str) -> str:
    """
    Fetch the appropriate token from Secrets Manager.

    Secret path: fde-{env}/alm-tokens
    Secret format: {"github_pat": "...", "gitlab_pat": "...", "bitbucket_pat": "..."}
    """
    secret_id = f"fde-{environment}/alm-tokens"

    try:
        client = boto3.client("secretsmanager", region_name=aws_region)
        response = client.get_secret_value(SecretId=secret_id)
        secrets = json.loads(response["SecretString"])
    except Exception as e:
        # Fallback to environment variable in local dev mode
        env_token = os.environ.get("GITHUB_TOKEN", "")
        if env_token:
            logger.warning("Secrets Manager unavailable, using GITHUB_TOKEN env var (local dev only)")
            return env_token
        raise CloneError(f"Failed to fetch credentials from {secret_id}: {e}") from e

    # Select token based on host
    token_map = {
        "github.com": "github_pat",
        "gitlab.com": "gitlab_pat",
        "bitbucket.org": "bitbucket_pat",
    }

    key = token_map.get(host)
    if not key or key not in secrets:
        raise CloneError(f"No token configured for host: {host}")

    return secrets[key]


def _create_askpass_script(token: str) -> str:
    """
    Create a one-shot GIT_ASKPASS script that echoes the token.

    The script is created with 0700 permissions (owner-only executable)
    and is deleted immediately after use.
    """
    script_path = f"/tmp/askpass-{uuid.uuid4()}.sh"
    with open(script_path, "w") as f:
        f.write(f"#!/bin/sh\necho '{token}'\n")
    os.chmod(script_path, 0o700)
    return script_path


def _get_head_sha(workspace_path: str) -> str:
    """Get HEAD commit SHA from a git workspace."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            cwd=workspace_path,
            timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return "unknown"


def _calculate_dir_size(path: str) -> int:
    """Calculate total size of a directory in bytes."""
    total = 0
    try:
        for dirpath, _dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.isfile(fp):
                    total += os.path.getsize(fp)
    except OSError:
        pass
    return total
