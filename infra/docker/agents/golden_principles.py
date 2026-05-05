"""
Golden Principles — Mechanical code quality invariants.

Encodes "taste" rules that prevent architectural drift in agent-generated code.
Unlike external linters (ruff, eslint), these check project-specific structural
health: file size, logging discipline, import hygiene, docstring presence.

Each principle is registered via @register_principle and produces a list of
PrincipleViolation when the rule is broken.

Usage:
  from agents.golden_principles import check_principles, PrincipleViolation
  violations: list[PrincipleViolation] = check_principles("/path/to/workspace")

Reference: docs/design/golden-principles.md
"""

import ast
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

logger = logging.getLogger("fde.golden_principles")


@dataclass
class PrincipleViolation:
    """A single golden principle violation."""

    principle: str               # e.g., "GP-01"
    rule_name: str               # e.g., "max_file_size"
    file: str                    # Relative path to the violating file
    message: str                 # Human-readable description
    remediation: str             # Actionable fix instruction
    line: int = 0                # Line number (0 if file-level)

    def to_dict(self) -> dict:
        return {
            "principle": self.principle,
            "rule_name": self.rule_name,
            "file": self.file,
            "message": self.message,
            "remediation": self.remediation,
            "line": self.line,
        }


# ─── Principle Registry ──────────────────────────────────────────

PrincipleCheckFn = Callable[[str], list[PrincipleViolation]]

_PRINCIPLE_REGISTRY: list[PrincipleCheckFn] = []


def register_principle(fn: PrincipleCheckFn) -> PrincipleCheckFn:
    """Register a golden principle check function."""
    _PRINCIPLE_REGISTRY.append(fn)
    return fn


def check_principles(workspace_dir: str) -> list[PrincipleViolation]:
    """Run all registered golden principle checks against the workspace."""
    all_violations: list[PrincipleViolation] = []
    for check_fn in _PRINCIPLE_REGISTRY:
        try:
            violations = check_fn(workspace_dir)
            all_violations.extend(violations)
        except Exception as e:
            logger.error("Principle check %s crashed: %s", check_fn.__name__, e)
    return all_violations


def get_registered_principles() -> list[PrincipleCheckFn]:
    """Return the list of registered principle check functions."""
    return list(_PRINCIPLE_REGISTRY)


# ─── Helper: Get production Python files ─────────────────────────

def _get_production_python_files(workspace_dir: str) -> list[Path]:
    """Get all Python files in infra/docker/agents/ (production code)."""
    agents_dir = Path(workspace_dir) / "infra" / "docker" / "agents"
    if not agents_dir.exists():
        return []
    return [
        f for f in agents_dir.rglob("*.py")
        if f.name != "__init__.py" and "__pycache__" not in str(f)
    ]


def _relative_path(file_path: Path, workspace_dir: str) -> str:
    """Get path relative to workspace for display."""
    try:
        return str(file_path.relative_to(workspace_dir))
    except ValueError:
        return str(file_path)


# ─── GP-01: Maximum File Size (500 lines) ────────────────────────

MAX_FILE_LINES = 500


@register_principle
def check_max_file_size(workspace_dir: str) -> list[PrincipleViolation]:
    """GP-01: No Python file in agents/ should exceed 500 lines."""
    violations: list[PrincipleViolation] = []

    for file_path in _get_production_python_files(workspace_dir):
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        line_count = len([ln for ln in content.splitlines() if ln.strip()])

        if line_count > MAX_FILE_LINES:
            violations.append(PrincipleViolation(
                principle="GP-01",
                rule_name="max_file_size",
                file=_relative_path(file_path, workspace_dir),
                message=f"File has {line_count} non-empty lines (max {MAX_FILE_LINES})",
                remediation=(
                    "Extract cohesive functions into a new module. "
                    "Look for natural boundaries (class definitions, "
                    "section comments) to split at."
                ),
            ))

    return violations


# ─── GP-02: No print() in Production Code ────────────────────────

_PRINT_PATTERN = re.compile(r"^\s*print\s*\(", re.MULTILINE)


@register_principle
def check_no_print(workspace_dir: str) -> list[PrincipleViolation]:
    """GP-02: No print() in production code — use logger instead."""
    violations: list[PrincipleViolation] = []

    for file_path in _get_production_python_files(workspace_dir):
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(content.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("print(") or stripped.startswith("print ("):
                # Skip comments
                if line.lstrip().startswith("#"):
                    continue
                violations.append(PrincipleViolation(
                    principle="GP-02",
                    rule_name="no_print",
                    file=_relative_path(file_path, workspace_dir),
                    message=f"print() found at line {i}",
                    remediation=(
                        "Replace with logger.info(), logger.debug(), or "
                        "logger.warning(). Add 'logger = logging.getLogger(__name__)' "
                        "at module level if not present."
                    ),
                    line=i,
                ))

    return violations


# ─── GP-03: All Modules Have Docstrings ───────────────────────────

@register_principle
def check_module_docstrings(workspace_dir: str) -> list[PrincipleViolation]:
    """GP-03: Every .py file in agents/ must have a module-level docstring."""
    violations: list[PrincipleViolation] = []

    for file_path in _get_production_python_files(workspace_dir):
        content = file_path.read_text(encoding="utf-8", errors="ignore")

        # Find first non-empty, non-comment line
        has_docstring = False
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # First meaningful line should be a docstring
            if stripped.startswith('"""') or stripped.startswith("'''"):
                has_docstring = True
            break

        if not has_docstring:
            violations.append(PrincipleViolation(
                principle="GP-03",
                rule_name="module_docstring",
                file=_relative_path(file_path, workspace_dir),
                message="Module is missing a docstring",
                remediation=(
                    "Add a module-level docstring (triple-quoted string) as the "
                    "first statement. Explain the module's responsibility in 1-3 lines."
                ),
            ))

    return violations


# ─── GP-04: No import * ──────────────────────────────────────────

_STAR_IMPORT_PATTERN = re.compile(r"^\s*from\s+\S+\s+import\s+\*", re.MULTILINE)


@register_principle
def check_no_star_import(workspace_dir: str) -> list[PrincipleViolation]:
    """GP-04: No file may use 'from module import *'."""
    violations: list[PrincipleViolation] = []

    for file_path in _get_production_python_files(workspace_dir):
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        for i, line in enumerate(content.splitlines(), start=1):
            if _STAR_IMPORT_PATTERN.match(line):
                violations.append(PrincipleViolation(
                    principle="GP-04",
                    rule_name="no_star_import",
                    file=_relative_path(file_path, workspace_dir),
                    message=f"Star import found at line {i}: {line.strip()}",
                    remediation=(
                        "Import specific names: 'from module import ClassA, function_b'. "
                        "This makes dependencies explicit and enables static analysis."
                    ),
                    line=i,
                ))

    return violations


# ─── GP-05: Maximum Function Length (50 lines) ────────────────────

MAX_FUNCTION_LINES = 50


@register_principle
def check_max_function_length(workspace_dir: str) -> list[PrincipleViolation]:
    """GP-05: No function or method should exceed 50 lines (body only)."""
    violations: list[PrincipleViolation] = []

    for file_path in _get_production_python_files(workspace_dir):
        content = file_path.read_text(encoding="utf-8", errors="ignore")
        try:
            tree = ast.parse(content)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Calculate body length (excluding docstring)
                body = node.body
                start_line = body[0].lineno if body else node.lineno
                end_line = node.end_lineno or node.lineno

                # Skip docstring from count
                if (body and isinstance(body[0], ast.Expr)
                        and isinstance(body[0].value, ast.Constant)
                        and isinstance(body[0].value.value, str)):
                    if len(body) > 1:
                        start_line = body[1].lineno
                    else:
                        continue  # Function is just a docstring

                body_lines = end_line - start_line + 1

                if body_lines > MAX_FUNCTION_LINES:
                    violations.append(PrincipleViolation(
                        principle="GP-05",
                        rule_name="max_function_length",
                        file=_relative_path(file_path, workspace_dir),
                        message=(
                            f"Function '{node.name}' has {body_lines} lines "
                            f"(max {MAX_FUNCTION_LINES})"
                        ),
                        remediation=(
                            "Extract helper functions with descriptive names. "
                            "Look for logical blocks that can be named and tested independently."
                        ),
                        line=node.lineno,
                    ))

    return violations
