"""
BDD Scenarios: Golden Principles + Garbage Collection (Task 4)

These tests validate that the golden principles module correctly detects
structural code quality violations in agent-generated code.

Source: OpenAI Harness Engineering — "golden principles encoded in repo"
Impact: Prevents architectural drift by encoding mechanical "taste" invariants
"""

import textwrap
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════
# Feature: GP-01 Maximum File Size
# ═══════════════════════════════════════════════════════════════════


class TestGP01MaxFileSize:
    """
    Feature: Files exceeding 500 lines are flagged
      As a Staff Engineer
      I want to know when agent-generated files grow too large
      So that modules stay focused and reviewable
    """

    def test_detects_file_over_500_lines(self, tmp_path):
        """
        Scenario: File with 600 non-empty lines triggers GP-01
          Given an agents/ directory with a file containing 600 non-empty lines
          When golden principles are checked
          Then GP-01 violation is reported with the line count
        """
        from agents.golden_principles import check_max_file_size

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        big_file = agents_dir / "big_module.py"
        big_file.write_text('"""Big module."""\n' + "x = 1\n" * 600)

        violations = check_max_file_size(str(tmp_path))

        assert len(violations) == 1
        assert violations[0].principle == "GP-01"
        assert "600" in violations[0].message or "601" in violations[0].message

    def test_no_violation_under_500_lines(self, tmp_path):
        """
        Scenario: File with 100 lines does not trigger GP-01
          Given an agents/ directory with a small file
          When golden principles are checked
          Then no GP-01 violation is reported
        """
        from agents.golden_principles import check_max_file_size

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        small_file = agents_dir / "small_module.py"
        small_file.write_text('"""Small module."""\n' + "x = 1\n" * 100)

        violations = check_max_file_size(str(tmp_path))
        assert len(violations) == 0


# ═══════════════════════════════════════════════════════════════════
# Feature: GP-02 No print() in Production
# ═══════════════════════════════════════════════════════════════════


class TestGP02NoPrint:
    """
    Feature: print() statements in production code are flagged
      As a Staff Engineer
      I want agents to use structured logging instead of print
      So that output is observable in containerized environments
    """

    def test_detects_print_statement(self, tmp_path):
        """
        Scenario: File with print() triggers GP-02
          Given an agents/ file containing print("hello")
          When golden principles are checked
          Then GP-02 violation is reported with the line number
        """
        from agents.golden_principles import check_no_print

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "bad_module.py").write_text(
            '"""Bad module."""\nimport logging\nprint("debug output")\n'
        )

        violations = check_no_print(str(tmp_path))

        assert len(violations) == 1
        assert violations[0].principle == "GP-02"
        assert violations[0].line == 3

    def test_no_violation_with_logger(self, tmp_path):
        """
        Scenario: File using logger.info() does not trigger GP-02
          Given an agents/ file using only logger calls
          When golden principles are checked
          Then no GP-02 violation is reported
        """
        from agents.golden_principles import check_no_print

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "good_module.py").write_text(
            '"""Good module."""\nimport logging\nlogger = logging.getLogger(__name__)\nlogger.info("hello")\n'
        )

        violations = check_no_print(str(tmp_path))
        assert len(violations) == 0


# ═══════════════════════════════════════════════════════════════════
# Feature: GP-03 Module Docstrings
# ═══════════════════════════════════════════════════════════════════


class TestGP03ModuleDocstrings:
    """
    Feature: Modules without docstrings are flagged
      As a Staff Engineer
      I want every module to explain its purpose
      So that agents and humans can navigate the codebase efficiently
    """

    def test_detects_missing_docstring(self, tmp_path):
        """
        Scenario: File without docstring triggers GP-03
          Given an agents/ file starting with import (no docstring)
          When golden principles are checked
          Then GP-03 violation is reported
        """
        from agents.golden_principles import check_module_docstrings

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "no_doc.py").write_text("import os\n\nx = 1\n")

        violations = check_module_docstrings(str(tmp_path))

        assert len(violations) == 1
        assert violations[0].principle == "GP-03"

    def test_no_violation_with_docstring(self, tmp_path):
        """
        Scenario: File with docstring does not trigger GP-03
          Given an agents/ file starting with a triple-quoted docstring
          When golden principles are checked
          Then no GP-03 violation is reported
        """
        from agents.golden_principles import check_module_docstrings

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "with_doc.py").write_text('"""This module does X."""\nimport os\n')

        violations = check_module_docstrings(str(tmp_path))
        assert len(violations) == 0


# ═══════════════════════════════════════════════════════════════════
# Feature: GP-04 No Star Imports
# ═══════════════════════════════════════════════════════════════════


class TestGP04NoStarImport:
    """
    Feature: Star imports are flagged
      As a Staff Engineer
      I want explicit imports so dependencies are traceable
      So that code review and static analysis work correctly
    """

    def test_detects_star_import(self, tmp_path):
        """
        Scenario: File with 'from os import *' triggers GP-04
          Given an agents/ file with a star import
          When golden principles are checked
          Then GP-04 violation is reported with the line
        """
        from agents.golden_principles import check_no_star_import

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "star.py").write_text(
            '"""Star module."""\nfrom os import *\n'
        )

        violations = check_no_star_import(str(tmp_path))

        assert len(violations) == 1
        assert violations[0].principle == "GP-04"
        assert violations[0].line == 2

    def test_no_violation_with_explicit_imports(self, tmp_path):
        """
        Scenario: File with explicit imports does not trigger GP-04
          Given an agents/ file with 'from os import path, getcwd'
          When golden principles are checked
          Then no GP-04 violation is reported
        """
        from agents.golden_principles import check_no_star_import

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "explicit.py").write_text(
            '"""Explicit module."""\nfrom os import path, getcwd\n'
        )

        violations = check_no_star_import(str(tmp_path))
        assert len(violations) == 0


# ═══════════════════════════════════════════════════════════════════
# Feature: GP-05 Maximum Function Length
# ═══════════════════════════════════════════════════════════════════


class TestGP05MaxFunctionLength:
    """
    Feature: Functions exceeding 50 lines are flagged
      As a Staff Engineer
      I want functions to stay focused and testable
      So that agent-generated code doesn't accumulate complexity
    """

    def test_detects_long_function(self, tmp_path):
        """
        Scenario: Function with 60 lines triggers GP-05
          Given an agents/ file with a function body of 60 lines
          When golden principles are checked
          Then GP-05 violation is reported with the function name
        """
        from agents.golden_principles import check_max_function_length

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)

        code = '"""Long function module."""\n\ndef very_long_function():\n'
        code += "    x = 1\n" * 60

        (agents_dir / "long_fn.py").write_text(code)

        violations = check_max_function_length(str(tmp_path))

        assert len(violations) == 1
        assert violations[0].principle == "GP-05"
        assert "very_long_function" in violations[0].message

    def test_no_violation_for_short_function(self, tmp_path):
        """
        Scenario: Function with 20 lines does not trigger GP-05
          Given an agents/ file with a short function
          When golden principles are checked
          Then no GP-05 violation is reported
        """
        from agents.golden_principles import check_max_function_length

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)

        code = '"""Short function module."""\n\ndef short_function():\n'
        code += "    x = 1\n" * 20

        (agents_dir / "short_fn.py").write_text(code)

        violations = check_max_function_length(str(tmp_path))
        assert len(violations) == 0


# ═══════════════════════════════════════════════════════════════════
# Feature: Full Principles Check
# ═══════════════════════════════════════════════════════════════════


class TestCheckPrinciplesIntegration:
    """
    Feature: check_principles runs all registered checks
      As a Code Factory
      I want a single entry point to validate all golden principles
      So that the hook can report all deviations in one pass
    """

    def test_check_principles_runs_all(self, tmp_path):
        """
        Scenario: check_principles aggregates violations from all principles
          Given a workspace with a file that violates GP-02 (print) and GP-04 (star import)
          When check_principles is called
          Then both violations are returned
        """
        from agents.golden_principles import check_principles

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "multi_bad.py").write_text(
            '"""Multi-bad module."""\nfrom os import *\nprint("oops")\n'
        )

        violations = check_principles(str(tmp_path))

        principles_found = {v.principle for v in violations}
        assert "GP-02" in principles_found
        assert "GP-04" in principles_found

    def test_clean_workspace_has_no_violations(self, tmp_path):
        """
        Scenario: Clean workspace passes all golden principles
          Given a workspace with well-structured code
          When check_principles is called
          Then no violations are returned
        """
        from agents.golden_principles import check_principles

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "clean.py").write_text(
            '"""Clean module with good practices."""\n'
            "import logging\n\n"
            "logger = logging.getLogger(__name__)\n\n\n"
            "def short_function():\n"
            '    """Do something."""\n'
            "    logger.info('working')\n"
            "    return 42\n"
        )

        violations = check_principles(str(tmp_path))
        assert len(violations) == 0

    def test_registry_has_five_principles(self):
        """
        Scenario: Registry contains all 5 golden principles
          Given the principle registry
          When get_registered_principles is called
          Then it returns exactly 5 check functions
        """
        from agents.golden_principles import get_registered_principles

        principles = get_registered_principles()
        assert len(principles) == 5
        assert all(callable(p) for p in principles)
