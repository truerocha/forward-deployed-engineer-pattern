"""
Artifact Classifier — Classifies changed files by artifact type.

Each artifact type has a different evaluation strategy. The classifier
uses file path patterns to determine the type, then loads the appropriate
evaluator for that type.

Design ref: docs/design/branch-evaluation-agent.md Section 4
"""

import logging
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path

logger = logging.getLogger("fde.branch_evaluation.classifier")


@dataclass
class ClassifiedFile:
    """A file classified by artifact type with its change status."""

    path: str
    artifact_type: str
    status: str  # added, modified, deleted, renamed
    content: str = ""  # Loaded lazily for non-deleted files

    def load_content(self) -> str:
        """Load file content if not already loaded and file exists."""
        if self.content:
            return self.content
        if self.status == "deleted":
            return ""
        try:
            self.content = Path(self.path).read_text(encoding="utf-8")
        except (FileNotFoundError, UnicodeDecodeError, PermissionError) as e:
            logger.warning("Cannot read %s: %s", self.path, e)
            self.content = ""
        return self.content


# Pattern definitions — order matters (first match wins)
ARTIFACT_TYPE_PATTERNS: dict[str, list[str]] = {
    "schema": [
        "src/contracts/schemas/**/*.json",
        "**/*.schema.json",
    ],
    "code": [
        "src/**/*.py",
        "wafr/**/*.py",
        "lambdas/**/*.py",
        "infra/docker/agents/**/*.py",
        "infra/terraform/lambda/**/*.py",
        "scripts/*.py",
    ],
    "knowledge": [
        "config/mappings/**/*.yaml",
        "config/mappings/**/*.json",
        "data/**/*.json",
        "src/knowledge/**/*.py",
        ".kiro/steering/*.md",
    ],
    "prompt": [
        "prompts/**/*.md",
        "prompts/**/*.txt",
        "infra/docker/agents/prompts.py",
    ],
    "infrastructure": [
        "infra/terraform/**/*.tf",
        "infra/docker/Dockerfile*",
        "infra/docker/requirements*.txt",
        ".github/workflows/**/*.yml",
        ".github/workflows/**/*.yaml",
    ],
    "documentation": [
        "docs/**/*.md",
        "README.md",
        "CHANGELOG.md",
        "LICENSE",
    ],
    "test": [
        "tests/**/*.py",
        "tests/**/*.json",
    ],
    "hook": [
        ".kiro/hooks/**/*.hook",
    ],
    "portal": [
        "infra/portal-src/**",
        "infra/dashboard/**",
    ],
}


def classify_file(filepath: str) -> str:
    """Classify a single file into an artifact type.

    Uses prefix and suffix matching against known path patterns.
    First match wins (patterns are ordered by specificity).

    Args:
        filepath: Relative path to the file from repo root.

    Returns:
        Artifact type string.
    """
    # Normalize path separators
    fp = filepath.replace("\\", "/")

    # Schema
    if "schemas/" in fp and fp.endswith(".json"):
        return "schema"
    if fp.endswith(".schema.json"):
        return "schema"

    # Test (before code — tests are also .py)
    if fp.startswith("tests/") and fp.endswith(".py"):
        return "test"

    # Code
    if fp.startswith("src/") and fp.endswith(".py"):
        return "code"
    if fp.startswith("wafr/") and fp.endswith(".py"):
        return "code"
    if fp.startswith("lambdas/") and fp.endswith(".py"):
        return "code"
    if fp.startswith("infra/docker/agents/") and fp.endswith(".py"):
        return "code"
    if fp.startswith("infra/terraform/lambda/") and fp.endswith(".py"):
        return "code"
    if fp.startswith("scripts/") and fp.endswith(".py"):
        return "code"

    # Knowledge
    if fp.startswith("config/mappings/"):
        return "knowledge"
    if fp.startswith("data/") and fp.endswith(".json"):
        return "knowledge"
    if fp.startswith("src/knowledge/") and fp.endswith(".py"):
        return "knowledge"
    if fp.startswith(".kiro/steering/") and fp.endswith(".md"):
        return "knowledge"

    # Prompt
    if fp.startswith("prompts/"):
        return "prompt"
    if fp == "infra/docker/agents/prompts.py":
        return "prompt"

    # Hook
    if fp.startswith(".kiro/hooks/") and fp.endswith(".hook"):
        return "hook"

    # Infrastructure
    if fp.startswith("infra/terraform/") and fp.endswith(".tf"):
        return "infrastructure"
    if "Dockerfile" in fp:
        return "infrastructure"
    if fp.startswith("infra/docker/requirements"):
        return "infrastructure"
    if fp.startswith(".github/workflows/") and (fp.endswith(".yml") or fp.endswith(".yaml")):
        return "infrastructure"

    # Portal
    if fp.startswith("infra/portal-src/"):
        return "portal"
    if fp.startswith("infra/dashboard/"):
        return "portal"

    # Documentation
    if fp.startswith("docs/") and fp.endswith(".md"):
        return "documentation"
    if fp == "README.md":
        return "documentation"
    if fp == "CHANGELOG.md":
        return "documentation"
    if fp == "LICENSE":
        return "documentation"

    # Test (JSON fixtures)
    if fp.startswith("tests/") and fp.endswith(".json"):
        return "test"

    return "other"


def classify_files(changed_files: list[tuple[str, str]]) -> list[ClassifiedFile]:
    """Classify a list of changed files.

    Args:
        changed_files: List of (status, filepath) tuples.
            Status is one of: added, modified, deleted, renamed.

    Returns:
        List of ClassifiedFile instances with artifact types assigned.
    """
    classified = []
    for status, filepath in changed_files:
        artifact_type = classify_file(filepath)
        classified.append(ClassifiedFile(
            path=filepath,
            artifact_type=artifact_type,
            status=status,
        ))
        logger.debug("Classified %s as %s (%s)", filepath, artifact_type, status)

    # Log summary
    type_counts: dict[str, int] = {}
    for f in classified:
        type_counts[f.artifact_type] = type_counts.get(f.artifact_type, 0) + 1
    logger.info("Classification summary: %s", type_counts)

    return classified


def get_affected_pipeline_edges(files: list[ClassifiedFile]) -> list[str]:
    """Identify which pipeline edges (E1-E6) are affected by the changes.

    Uses the module boundary map from the FDE steering to determine
    which edges are impacted.

    Args:
        files: Classified file list.

    Returns:
        List of affected edge identifiers (e.g., ["E1", "E3", "E6"]).
    """
    # Module → Edge mapping (from FDE steering)
    MODULE_EDGE_MAP = {
        "facts_extractor": ["E1"],
        "evidence_catalog": ["E1", "E2"],
        "deterministic_reviewer": ["E2", "E3"],
        "publish_tree": ["E3", "E4"],
        "publish_sanitizer": ["E4", "E5"],
        "router": ["E1"],
        "orchestrator": ["E1", "E2", "E3", "E4"],
        "task_queue": ["E4"],
        "workspace_setup": ["E5"],
        "stream_callback": ["E6"],
    }

    # Infrastructure and portal affect E5/E6
    TYPE_EDGE_MAP = {
        "schema": ["E5"],
        "portal": ["E6"],
        "infrastructure": ["E4", "E5"],
        "knowledge": ["E2", "E3"],
        "prompt": ["E3", "E4"],
    }

    affected: set[str] = set()

    for f in files:
        # Check module-level mapping
        for module_name, edges in MODULE_EDGE_MAP.items():
            if module_name in f.path:
                affected.update(edges)

        # Check type-level mapping
        type_edges = TYPE_EDGE_MAP.get(f.artifact_type, [])
        affected.update(type_edges)

    return sorted(affected)
