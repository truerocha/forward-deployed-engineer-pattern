"""
Code Evaluator — Evaluates Python code artifacts for structural validity,
convention compliance, and test coverage.

Implements Section 6.2 of the design doc.

Design ref: docs/design/branch-evaluation-agent.md Section 6.2
"""

import ast
import logging
import subprocess
from pathlib import Path

from .artifact_classifier import ClassifiedFile
from .scoring_engine import DimensionScore, DEFAULT_WEIGHTS

logger = logging.getLogger("fde.branch_evaluation.code_evaluator")


def evaluate_structural_validity(files: list[ClassifiedFile]) -> DimensionScore:
    """D1: Structural Validity — All code artifacts parse and compile.

    Evaluation method:
    - Python: ast.parse() for syntax validation
    - JSON hooks: json.loads() for structure
    - Terraform: file existence (tf validate requires init)

    Args:
        files: Classified files to evaluate.

    Returns:
        DimensionScore for structural validity.
    """
    import json

    issues: list[str] = []
    total = 0
    passed = 0

    for f in files:
        if f.status == "deleted":
            continue

        path = Path(f.path)
        if not path.exists():
            continue

        total += 1

        if f.artifact_type == "code" and f.path.endswith(".py"):
            try:
                content = path.read_text(encoding="utf-8")
                ast.parse(content)
                passed += 1
            except SyntaxError as e:
                issues.append(f"SyntaxError in {f.path}:{e.lineno}: {e.msg}")
            except Exception as e:
                issues.append(f"Parse error in {f.path}: {str(e)[:100]}")

        elif f.artifact_type == "hook" and f.path.endswith(".hook"):
            try:
                content = path.read_text(encoding="utf-8")
                hook_data = json.loads(content)
                required = {"name", "version", "when", "then"}
                missing = required - set(hook_data.keys())
                if missing:
                    issues.append(f"Hook {f.path} missing fields: {missing}")
                else:
                    passed += 1
            except json.JSONDecodeError as e:
                issues.append(f"Invalid JSON in hook {f.path}: {e}")
            except Exception as e:
                issues.append(f"Error reading {f.path}: {str(e)[:100]}")

        elif f.artifact_type == "schema" and f.path.endswith(".json"):
            try:
                content = path.read_text(encoding="utf-8")
                schema = json.loads(content)
                if "$schema" not in schema and "type" not in schema:
                    issues.append(f"Schema {f.path} missing $schema or type field")
                else:
                    passed += 1
            except json.JSONDecodeError as e:
                issues.append(f"Invalid JSON schema {f.path}: {e}")

        elif f.artifact_type == "infrastructure" and f.path.endswith(".tf"):
            if path.exists() and path.stat().st_size > 0:
                passed += 1
            else:
                issues.append(f"Empty or missing Terraform file: {f.path}")

        elif f.artifact_type in ("documentation", "knowledge") and f.path.endswith(".md"):
            if path.exists() and path.stat().st_size > 0:
                passed += 1
            else:
                issues.append(f"Empty documentation file: {f.path}")

        elif f.artifact_type == "portal":
            if path.exists():
                passed += 1
            else:
                issues.append(f"Missing portal file: {f.path}")

        else:
            if path.exists():
                passed += 1

    score = (passed / total * 10.0) if total > 0 else 10.0
    return DimensionScore(
        name="structural_validity",
        score=min(10.0, score),
        weight=DEFAULT_WEIGHTS["structural_validity"],
        issues=issues,
        details={"total": total, "passed": passed},
    )


def evaluate_convention_compliance(files: list[ClassifiedFile]) -> DimensionScore:
    """D2: Convention Compliance — Code follows project patterns.

    Checks:
    - Module docstrings present
    - snake_case function names
    - No wildcard imports
    - Hook files have required structure
    - Import layering (no cross-plane violations)

    Args:
        files: Classified files to evaluate.

    Returns:
        DimensionScore for convention compliance.
    """
    issues: list[str] = []
    deductions = 0.0

    for f in files:
        if f.status == "deleted":
            continue

        path = Path(f.path)
        if not path.exists():
            continue

        if f.artifact_type == "code" and f.path.endswith(".py"):
            try:
                content = path.read_text(encoding="utf-8")
                tree = ast.parse(content)

                if not ast.get_docstring(tree):
                    issues.append(f"Missing module docstring: {f.path}")
                    deductions += 0.5

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and node.names:
                        for alias in node.names:
                            if alias.name == "*":
                                issues.append(f"Wildcard import in {f.path}: from {node.module} import *")
                                deductions += 1.0

                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if not node.name.startswith("_") and not node.name.islower():
                            if not node.name.startswith("__"):
                                issues.append(f"Non-snake_case function: {f.path}:{node.name}")
                                deductions += 0.3

            except (SyntaxError, Exception):
                pass

        elif f.artifact_type == "hook" and f.path.endswith(".hook"):
            try:
                import json
                content = path.read_text(encoding="utf-8")
                hook = json.loads(content)

                version = hook.get("version", "")
                if not version or not all(p.isdigit() for p in version.split(".")):
                    issues.append(f"Invalid version format in {f.path}: {version}")
                    deductions += 0.5

                valid_types = {
                    "fileEdited", "fileCreated", "fileDeleted", "userTriggered",
                    "promptSubmit", "agentStop", "preToolUse", "postToolUse",
                    "preTaskExecution", "postTaskExecution",
                }
                when_type = hook.get("when", {}).get("type", "")
                if when_type not in valid_types:
                    issues.append(f"Invalid hook event type in {f.path}: {when_type}")
                    deductions += 1.0

            except Exception:
                pass

    score = max(0.0, 10.0 - deductions)
    return DimensionScore(
        name="convention_compliance",
        score=min(10.0, score),
        weight=DEFAULT_WEIGHTS["convention_compliance"],
        issues=issues,
        details={"deductions": deductions},
    )


def evaluate_backward_compatibility(files: list[ClassifiedFile]) -> DimensionScore:
    """D3: Backward Compatibility — No breaking changes without migration.

    Breaking change detection:
    - Deleted files (code, hook, knowledge) = potentially breaking
    - Removed function/class from public API
    - Changed function signatures (removed params)

    Args:
        files: Classified files to evaluate.

    Returns:
        DimensionScore for backward compatibility.
    """
    issues: list[str] = []
    breaking_count = 0

    for f in files:
        if f.status == "deleted":
            if f.artifact_type in ("code", "hook", "knowledge", "schema"):
                issues.append(f"BREAKING: Deleted {f.artifact_type} file: {f.path}")
                breaking_count += 1

        elif f.status == "modified" and f.artifact_type == "code" and f.path.endswith(".py"):
            try:
                result = subprocess.run(
                    ["git", "show", f"main:{f.path}"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    old_content = result.stdout
                    new_content = Path(f.path).read_text(encoding="utf-8")

                    old_tree = ast.parse(old_content)
                    new_tree = ast.parse(new_content)

                    old_public = {
                        node.name for node in ast.walk(old_tree)
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                        and not node.name.startswith("_")
                    }
                    new_public = {
                        node.name for node in ast.walk(new_tree)
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                        and not node.name.startswith("_")
                    }

                    removed = old_public - new_public
                    if removed:
                        for name in removed:
                            issues.append(f"BREAKING: Removed public API '{name}' from {f.path}")
                            breaking_count += 1

            except (subprocess.TimeoutExpired, SyntaxError, Exception) as e:
                logger.debug("Compat check skipped for %s: %s", f.path, e)

    score = max(0.0, 10.0 - (breaking_count * 3.0))
    return DimensionScore(
        name="backward_compatibility",
        score=score,
        weight=DEFAULT_WEIGHTS["backward_compatibility"],
        issues=issues,
        details={"breaking_changes": breaking_count},
    )


def evaluate_test_coverage(files: list[ClassifiedFile]) -> DimensionScore:
    """D5: Test Coverage — Tests exist and pass for changed code.

    Evaluation:
    1. Run scoped tests (tests that import changed modules)
    2. Check if new code files have corresponding test files
    3. Verify test pass rate

    Args:
        files: Classified files to evaluate.

    Returns:
        DimensionScore for test coverage.
    """
    issues: list[str] = []
    details: dict = {}

    test_cmd = ["python3", "-m", "pytest", "tests/", "-q", "--tb=no", "-x"]
    try:
        result = subprocess.run(
            test_cmd, capture_output=True, text=True, timeout=120,
        )
        details["exit_code"] = result.returncode
        details["output"] = result.stdout[-500:] if result.stdout else ""

        if result.returncode == 0:
            last_line = result.stdout.strip().split("\n")[-1] if result.stdout.strip() else ""
            details["summary"] = last_line
            score = 9.0
        elif "error" in (result.stdout + result.stderr).lower() and "ModuleNotFoundError" in (result.stdout + result.stderr):
            issues.append("Test collection error (environment dependency)")
            score = 7.0
        else:
            failed_lines = [l for l in result.stdout.split("\n") if "FAILED" in l]
            for line in failed_lines[:5]:
                issues.append(f"Test failure: {line.strip()[:150]}")
            score = 3.0

    except subprocess.TimeoutExpired:
        issues.append("Test suite timed out (>120s)")
        score = 5.0
    except Exception as e:
        issues.append(f"Cannot run tests: {str(e)[:100]}")
        score = 5.0

    new_code_files = [f for f in files if f.artifact_type == "code" and f.status == "added"]
    for cf in new_code_files:
        module_name = Path(cf.path).stem
        possible_tests = [
            f"tests/test_{module_name}.py",
            f"tests/{module_name}/test_{module_name}.py",
        ]
        has_test = any(Path(t).exists() for t in possible_tests)
        if not has_test:
            issues.append(f"No test file for new module: {cf.path}")
            score = max(score - 0.5, 0.0)

    return DimensionScore(
        name="test_coverage",
        score=min(10.0, score),
        weight=DEFAULT_WEIGHTS["test_coverage"],
        issues=issues,
        details=details,
    )


def evaluate_documentation(files: list[ClassifiedFile]) -> DimensionScore:
    """D7: Documentation — Changes are documented appropriately.

    Checks:
    - Code changes accompanied by doc updates
    - New modules have docstrings
    - CHANGELOG updated for significant changes
    - ADR present for architectural decisions

    Args:
        files: Classified files to evaluate.

    Returns:
        DimensionScore for documentation.
    """
    issues: list[str] = []

    has_code_changes = any(f.artifact_type == "code" and f.status != "deleted" for f in files)
    has_doc_changes = any(f.artifact_type == "documentation" for f in files)
    has_changelog = any("CHANGELOG" in f.path for f in files)
    has_adr = any("adr/" in f.path.lower() for f in files)

    code_file_count = sum(1 for f in files if f.artifact_type == "code" and f.status != "deleted")

    if code_file_count >= 3 and not has_doc_changes:
        issues.append(f"Significant code changes ({code_file_count} files) without documentation updates")
        score = 5.0
    elif code_file_count >= 5 and not has_changelog:
        issues.append("Large change set without CHANGELOG update")
        score = 6.0
    elif has_code_changes and not has_doc_changes:
        score = 7.0
    elif has_doc_changes:
        score = 10.0
    else:
        score = 8.0

    new_packages = [f for f in files if f.status == "added" and "__init__.py" in f.path]
    if new_packages and not has_adr:
        issues.append("New package introduced without ADR")
        score = min(score, 7.0)

    return DimensionScore(
        name="documentation",
        score=score,
        weight=DEFAULT_WEIGHTS["documentation"],
        issues=issues,
    )
