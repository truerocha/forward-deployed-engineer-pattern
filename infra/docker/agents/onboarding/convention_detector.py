"""
Convention Detector — Detects project conventions by examining configuration
files and directory structure.

Design ref: §3.5 Convention Detector
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger("fde-onboarding.convention_detector")


@dataclass
class Convention:
    """A detected project convention."""

    category: str  # language | package_manager | test_framework | linter | ci_cd | container | iac
    name: str
    version: Optional[str] = None
    config_path: Optional[str] = None


@dataclass
class ConventionResult:
    """Aggregate result of convention detection."""

    conventions: list[Convention]
    total_found: int
    duration_ms: int


# Detection rules: (config file/pattern, category, name)
DETECTION_RULES: list[tuple[str, str, str]] = [
    # Package managers
    ("package.json", "package_manager", "npm"),
    ("yarn.lock", "package_manager", "yarn"),
    ("pnpm-lock.yaml", "package_manager", "pnpm"),
    ("requirements.txt", "package_manager", "pip"),
    ("Pipfile", "package_manager", "pipenv"),
    ("pyproject.toml", "package_manager", "poetry"),
    ("setup.py", "package_manager", "setuptools"),
    ("go.mod", "package_manager", "go-modules"),
    ("Cargo.toml", "package_manager", "cargo"),
    ("pom.xml", "package_manager", "maven"),
    ("build.gradle", "package_manager", "gradle"),
    ("Gemfile", "package_manager", "bundler"),
    ("composer.json", "package_manager", "composer"),

    # Test frameworks
    ("pytest.ini", "test_framework", "pytest"),
    ("conftest.py", "test_framework", "pytest"),
    ("setup.cfg", "test_framework", "pytest"),
    ("jest.config.js", "test_framework", "jest"),
    ("jest.config.ts", "test_framework", "jest"),
    ("vitest.config.ts", "test_framework", "vitest"),
    ("vitest.config.js", "test_framework", "vitest"),
    ("karma.conf.js", "test_framework", "karma"),
    (".mocharc.yml", "test_framework", "mocha"),
    ("phpunit.xml", "test_framework", "phpunit"),

    # Linters
    ("ruff.toml", "linter", "ruff"),
    (".ruff.toml", "linter", "ruff"),
    (".eslintrc", "linter", "eslint"),
    (".eslintrc.js", "linter", "eslint"),
    (".eslintrc.json", "linter", "eslint"),
    ("eslint.config.js", "linter", "eslint"),
    (".pylintrc", "linter", "pylint"),
    (".flake8", "linter", "flake8"),
    (".golangci.yml", "linter", "golangci-lint"),
    (".golangci.yaml", "linter", "golangci-lint"),
    ("clippy.toml", "linter", "clippy"),
    (".prettierrc", "linter", "prettier"),
    ("biome.json", "linter", "biome"),

    # CI/CD
    (".github/workflows", "ci_cd", "github-actions"),
    (".gitlab-ci.yml", "ci_cd", "gitlab-ci"),
    ("Jenkinsfile", "ci_cd", "jenkins"),
    (".circleci/config.yml", "ci_cd", "circleci"),
    ("bitbucket-pipelines.yml", "ci_cd", "bitbucket-pipelines"),
    (".travis.yml", "ci_cd", "travis-ci"),
    ("azure-pipelines.yml", "ci_cd", "azure-devops"),
    ("buildspec.yml", "ci_cd", "aws-codebuild"),

    # Containerization
    ("Dockerfile", "container", "docker"),
    ("docker-compose.yml", "container", "docker-compose"),
    ("docker-compose.yaml", "container", "docker-compose"),
    ("compose.yml", "container", "docker-compose"),
    ("compose.yaml", "container", "docker-compose"),

    # Infrastructure as Code
    ("main.tf", "iac", "terraform"),
    ("cdk.json", "iac", "aws-cdk"),
    ("template.yaml", "iac", "aws-sam"),
    ("template.yml", "iac", "aws-sam"),
    ("serverless.yml", "iac", "serverless-framework"),
    ("pulumi.yaml", "iac", "pulumi"),
    ("cloudformation.yaml", "iac", "cloudformation"),
    ("cloudformation.yml", "iac", "cloudformation"),

    # Type checking
    ("tsconfig.json", "type_checker", "typescript"),
    ("mypy.ini", "type_checker", "mypy"),
    (".mypy.ini", "type_checker", "mypy"),
    ("pyrightconfig.json", "type_checker", "pyright"),

    # Formatters
    (".editorconfig", "formatter", "editorconfig"),
    ("rustfmt.toml", "formatter", "rustfmt"),
    (".clang-format", "formatter", "clang-format"),
]


def detect_conventions(
    workspace_path: str,
    file_paths: Optional[list[str]] = None,
) -> ConventionResult:
    """
    Detect project conventions from configuration files and directory structure.

    Args:
        workspace_path: Root directory of the repository.
        file_paths: Optional pre-scanned file list (avoids re-walking).

    Returns:
        ConventionResult with detected conventions.
    """
    start = time.time()
    conventions: list[Convention] = []
    seen: set[tuple[str, str]] = set()

    # Build a set of existing paths for fast lookup
    if file_paths:
        existing_paths = set(file_paths)
    else:
        existing_paths = _collect_paths(workspace_path)

    # Check each detection rule
    for pattern, category, name in DETECTION_RULES:
        key = (category, name)
        if key in seen:
            continue

        config_path = _find_config(workspace_path, pattern, existing_paths)
        if config_path:
            version = _extract_version(workspace_path, config_path, name)
            conventions.append(Convention(
                category=category,
                name=name,
                version=version,
                config_path=config_path,
            ))
            seen.add(key)

    # Detect Go test files (convention: *_test.go)
    if any(p.endswith("_test.go") for p in existing_paths):
        key = ("test_framework", "go-test")
        if key not in seen:
            conventions.append(Convention(category="test_framework", name="go-test"))
            seen.add(key)

    # Detect JUnit from pom.xml or build.gradle
    if ("package_manager", "maven") in seen or ("package_manager", "gradle") in seen:
        key = ("test_framework", "junit")
        if key not in seen:
            conventions.append(Convention(category="test_framework", name="junit"))
            seen.add(key)

    # Detect Terraform files (*.tf anywhere)
    if any(p.endswith(".tf") for p in existing_paths):
        key = ("iac", "terraform")
        if key not in seen:
            conventions.append(Convention(category="iac", name="terraform"))
            seen.add(key)

    # Check pyproject.toml for ruff/pytest config
    _check_pyproject_toml(workspace_path, existing_paths, conventions, seen)

    duration_ms = int((time.time() - start) * 1000)

    logger.info(
        "Convention detection complete: %d conventions found, %dms",
        len(conventions),
        duration_ms,
    )

    return ConventionResult(
        conventions=conventions,
        total_found=len(conventions),
        duration_ms=duration_ms,
    )


def _collect_paths(workspace_path: str) -> set[str]:
    """Collect all relative file paths in the workspace."""
    paths = set()
    for dirpath, dirnames, filenames in os.walk(workspace_path):
        dirnames[:] = [d for d in dirnames if d not in {".git", "node_modules", "__pycache__", ".venv"}]
        for f in filenames:
            rel = os.path.relpath(os.path.join(dirpath, f), workspace_path)
            paths.add(rel)
    return paths


def _find_config(workspace_path: str, pattern: str, existing_paths: set[str]) -> Optional[str]:
    """Check if a config file/directory exists."""
    if pattern in existing_paths:
        return pattern

    full_path = os.path.join(workspace_path, pattern)
    if os.path.isdir(full_path):
        return pattern

    # Check for pattern in subdirectories
    for path in existing_paths:
        if path.endswith("/" + pattern) or Path(path).name == pattern:
            return path

    return None


def _extract_version(workspace_path: str, config_path: str, name: str) -> Optional[str]:
    """Try to extract version information from a config file."""
    full_path = os.path.join(workspace_path, config_path)

    if not os.path.isfile(full_path):
        return None

    try:
        if config_path == "package.json":
            with open(full_path, "r") as f:
                data = json.load(f)
                deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
                if name in deps:
                    return deps[name]
        elif config_path == "go.mod":
            with open(full_path, "r") as f:
                for line in f:
                    if line.startswith("go "):
                        return line.strip().split()[-1]
    except (json.JSONDecodeError, OSError, KeyError):
        pass

    return None


def _check_pyproject_toml(
    workspace_path: str,
    existing_paths: set[str],
    conventions: list[Convention],
    seen: set[tuple[str, str]],
) -> None:
    """Check pyproject.toml for tool configurations."""
    if "pyproject.toml" not in existing_paths:
        return

    full_path = os.path.join(workspace_path, "pyproject.toml")
    try:
        with open(full_path, "r") as f:
            content = f.read()

        if "[tool.ruff]" in content or "[ruff]" in content:
            key = ("linter", "ruff")
            if key not in seen:
                conventions.append(Convention(
                    category="linter", name="ruff", config_path="pyproject.toml"
                ))
                seen.add(key)

        if "[tool.pytest" in content:
            key = ("test_framework", "pytest")
            if key not in seen:
                conventions.append(Convention(
                    category="test_framework", name="pytest", config_path="pyproject.toml"
                ))
                seen.add(key)

        if "[tool.mypy]" in content or "[mypy]" in content:
            key = ("type_checker", "mypy")
            if key not in seen:
                conventions.append(Convention(
                    category="type_checker", name="mypy", config_path="pyproject.toml"
                ))
                seen.add(key)

    except OSError:
        pass
