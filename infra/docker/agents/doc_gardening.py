"""
Doc-Gardening Agent — Detects documentation drift from code.

Resolves the most repeated pattern in COEs (6 of 9 entries are "doc was outdated").
Inspired by OpenAI Harness Engineering: recurring agent scans for stale docs and
opens fix-up PRs.

The module provides a registry of DocCheck functions. Each check:
  1. Reads the current state from code/filesystem
  2. Reads the documented state from markdown
  3. Reports drift if they differ

Usage:
  from agents.doc_gardening import run_all_checks, DocDrift
  drifts: list[DocDrift] = run_all_checks(workspace_dir="/path/to/repo")
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

logger = logging.getLogger("fde.doc_gardening")


@dataclass
class DocDrift:
    """A single documentation drift finding."""

    file: str                    # Which doc file is stale
    check_name: str              # Which check detected it
    documented_value: str        # What the doc says
    actual_value: str            # What the code/filesystem says
    message: str                 # Human-readable description

    def to_dict(self) -> dict:
        return {
            "file": self.file,
            "check_name": self.check_name,
            "documented_value": self.documented_value,
            "actual_value": self.actual_value,
            "message": self.message,
        }


# ─── Check Registry ─────────────────────────────────────────────

# Type for a doc check function: (workspace_dir) -> list[DocDrift]
DocCheckFn = Callable[[str], list[DocDrift]]

_CHECK_REGISTRY: list[DocCheckFn] = []


def register_check(fn: DocCheckFn) -> DocCheckFn:
    """Register a doc check function in the global registry."""
    _CHECK_REGISTRY.append(fn)
    return fn


def run_all_checks(workspace_dir: str) -> list[DocDrift]:
    """Run all registered doc checks and return all drifts found."""
    all_drifts: list[DocDrift] = []
    for check_fn in _CHECK_REGISTRY:
        try:
            drifts = check_fn(workspace_dir)
            all_drifts.extend(drifts)
        except Exception as e:
            logger.error("Doc check %s failed: %s", check_fn.__name__, e)
            all_drifts.append(DocDrift(
                file="(check crashed)",
                check_name=check_fn.__name__,
                documented_value="N/A",
                actual_value="N/A",
                message=f"Check crashed: {e}",
            ))
    return all_drifts


def get_registered_checks() -> list[DocCheckFn]:
    """Return the list of registered check functions (for extensibility)."""
    return list(_CHECK_REGISTRY)


# ─── Concrete Checks ────────────────────────────────────────────

@register_check
def check_hook_count(workspace_dir: str) -> list[DocDrift]:
    """Check that README hook count matches actual .kiro/hooks/ file count."""
    hooks_dir = Path(workspace_dir) / ".kiro" / "hooks"
    if not hooks_dir.exists():
        return []

    actual_count = len([
        f for f in hooks_dir.iterdir()
        if f.is_file() and f.suffix == ".hook"
    ])

    readme_path = Path(workspace_dir) / "README.md"
    if not readme_path.exists():
        return []

    readme_content = readme_path.read_text()

    # Look for hook count in badge: hooks-14 or hooks-14%20
    badge_match = re.search(r"hooks-(\d+)", readme_content)
    if not badge_match:
        return []

    documented_count = int(badge_match.group(1))

    if documented_count != actual_count:
        return [DocDrift(
            file="README.md",
            check_name="check_hook_count",
            documented_value=str(documented_count),
            actual_value=str(actual_count),
            message=(
                f"README badge says {documented_count} hooks but "
                f".kiro/hooks/ contains {actual_count} .hook files"
            ),
        )]
    return []


@register_check
def check_adr_count(workspace_dir: str) -> list[DocDrift]:
    """Check that README ADR count references match actual docs/adr/ file count."""
    adr_dir = Path(workspace_dir) / "docs" / "adr"
    if not adr_dir.exists():
        return []

    actual_count = len([
        f for f in adr_dir.iterdir()
        if f.is_file() and f.name.startswith("ADR-") and f.suffix == ".md"
    ])

    readme_path = Path(workspace_dir) / "README.md"
    if not readme_path.exists():
        return []

    readme_content = readme_path.read_text()

    # Look for ADR count references like "10 Architecture Decision Records" or "7 ADRs"
    drifts: list[DocDrift] = []
    adr_patterns = re.findall(r"(\d+)\s+(?:Architecture Decision Records|ADRs?)", readme_content)
    for documented_str in adr_patterns:
        documented_count = int(documented_str)
        if documented_count != actual_count:
            drifts.append(DocDrift(
                file="README.md",
                check_name="check_adr_count",
                documented_value=str(documented_count),
                actual_value=str(actual_count),
                message=(
                    f"README references {documented_count} ADRs but "
                    f"docs/adr/ contains {actual_count} ADR files"
                ),
            ))
    return drifts


@register_check
def check_flow_count(workspace_dir: str) -> list[DocDrift]:
    """Check that README flow count references match actual docs/flows/ file count."""
    flows_dir = Path(workspace_dir) / "docs" / "flows"
    if not flows_dir.exists():
        return []

    actual_count = len([
        f for f in flows_dir.iterdir()
        if f.is_file() and f.suffix == ".md" and f.name != "README.md"
    ])

    readme_path = Path(workspace_dir) / "README.md"
    if not readme_path.exists():
        return []

    readme_content = readme_path.read_text()

    # Look for flow count references like "13 Mermaid" or "10 Mermaid"
    drifts: list[DocDrift] = []
    flow_patterns = re.findall(r"(\d+)\s+Mermaid", readme_content)
    for documented_str in flow_patterns:
        documented_count = int(documented_str)
        if documented_count != actual_count:
            drifts.append(DocDrift(
                file="README.md",
                check_name="check_flow_count",
                documented_value=str(documented_count),
                actual_value=str(actual_count),
                message=(
                    f"README references {documented_count} Mermaid flow diagrams but "
                    f"docs/flows/ contains {actual_count} flow files"
                ),
            ))
    return drifts


@register_check
def check_design_components(workspace_dir: str) -> list[DocDrift]:
    """Check that design-document.md components table includes all agent modules."""
    agents_dir = Path(workspace_dir) / "infra" / "docker" / "agents"
    if not agents_dir.exists():
        return []

    actual_modules = sorted([
        f.stem for f in agents_dir.iterdir()
        if f.is_file() and f.suffix == ".py" and f.name != "__init__.py"
    ])

    design_doc_path = Path(workspace_dir) / "docs" / "architecture" / "design-document.md"
    if not design_doc_path.exists():
        return []

    design_content = design_doc_path.read_text()

    # Check which agent modules are mentioned in the design doc
    drifts: list[DocDrift] = []
    missing_modules: list[str] = []
    for module in actual_modules:
        # Check if the module name appears anywhere in the design doc
        # (as filename, reference, or in a table)
        if module not in design_content and f"{module}.py" not in design_content:
            missing_modules.append(module)

    if missing_modules:
        drifts.append(DocDrift(
            file="docs/architecture/design-document.md",
            check_name="check_design_components",
            documented_value=f"{len(actual_modules) - len(missing_modules)} modules referenced",
            actual_value=f"{len(actual_modules)} modules exist",
            message=(
                f"Design document is missing references to agent modules: "
                f"{', '.join(missing_modules)}"
            ),
        ))
    return drifts


@register_check
def check_changelog_unreleased(workspace_dir: str) -> list[DocDrift]:
    """Check that CHANGELOG has content in the Unreleased section."""
    changelog_path = Path(workspace_dir) / "CHANGELOG.md"
    if not changelog_path.exists():
        return []

    content = changelog_path.read_text()

    # Find the Unreleased section
    unreleased_match = re.search(
        r"## \[Unreleased\].*?\n(.*?)(?=\n## \[|$)",
        content,
        re.DOTALL,
    )

    if not unreleased_match:
        return [DocDrift(
            file="CHANGELOG.md",
            check_name="check_changelog_unreleased",
            documented_value="No [Unreleased] section found",
            actual_value="Expected [Unreleased] section",
            message="CHANGELOG.md is missing an [Unreleased] section",
        )]

    unreleased_content = unreleased_match.group(1).strip()
    # Check if it's just a separator or empty
    if not unreleased_content or unreleased_content == "---":
        return [DocDrift(
            file="CHANGELOG.md",
            check_name="check_changelog_unreleased",
            documented_value="Empty [Unreleased] section",
            actual_value="Changes exist that should be documented",
            message="CHANGELOG.md [Unreleased] section is empty — changes may be undocumented",
        )]

    return []
