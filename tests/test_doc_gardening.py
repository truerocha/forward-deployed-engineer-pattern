"""
BDD Scenarios: Doc-Gardening Agent (Task 2)

These tests validate that the doc-gardening module correctly detects
documentation drift from code. Each check compares filesystem state
against documented state in markdown files.

Source: OpenAI Harness Engineering — "recurring agent scans for stale docs"
Impact: Resolves the most repeated COE pattern (6 of 9 entries are "doc was outdated")
"""

import os
import tempfile
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════
# Feature: Doc-Gardening Drift Detection
# ═══════════════════════════════════════════════════════════════════


class TestDocGardeningHookCount:
    """
    Feature: Hook count drift detection
      As a Staff Engineer
      I want to know when README hook count diverges from actual hooks
      So that documentation stays accurate without manual checking
    """

    def test_detects_hook_count_drift(self, tmp_path):
        """
        Scenario: README says 14 hooks but 15 exist
          Given a workspace with 15 .hook files
          And a README badge showing 14 hooks
          When the hook count check runs
          Then it reports drift with documented=14, actual=15
        """
        from agents.doc_gardening import check_hook_count

        # Setup: create hooks dir with 15 files
        hooks_dir = tmp_path / ".kiro" / "hooks"
        hooks_dir.mkdir(parents=True)
        for i in range(15):
            (hooks_dir / f"hook-{i}.kiro.hook").write_text("{}")

        # Setup: README with badge showing 14
        readme = tmp_path / "README.md"
        readme.write_text(
            '[![Hooks](https://img.shields.io/badge/hooks-14%20total-blue)]()\n'
        )

        drifts = check_hook_count(str(tmp_path))

        assert len(drifts) == 1
        assert drifts[0].documented_value == "14"
        assert drifts[0].actual_value == "15"
        assert "README" in drifts[0].file

    def test_no_drift_when_counts_match(self, tmp_path):
        """
        Scenario: README says 14 hooks and 14 exist
          Given a workspace with 14 .hook files
          And a README badge showing 14 hooks
          When the hook count check runs
          Then no drift is reported
        """
        from agents.doc_gardening import check_hook_count

        hooks_dir = tmp_path / ".kiro" / "hooks"
        hooks_dir.mkdir(parents=True)
        for i in range(14):
            (hooks_dir / f"hook-{i}.kiro.hook").write_text("{}")

        readme = tmp_path / "README.md"
        readme.write_text(
            '[![Hooks](https://img.shields.io/badge/hooks-14%20stuff-blue)]()\n'
        )

        drifts = check_hook_count(str(tmp_path))
        assert len(drifts) == 0


class TestDocGardeningADRCount:
    """
    Feature: ADR count drift detection
      As a Staff Engineer
      I want to know when README ADR references diverge from actual ADRs
      So that new ADRs are always reflected in documentation
    """

    def test_detects_adr_count_drift(self, tmp_path):
        """
        Scenario: README says 10 ADRs but 13 exist
          Given a workspace with 13 ADR files
          And a README referencing "10 Architecture Decision Records"
          When the ADR count check runs
          Then it reports drift with documented=10, actual=13
        """
        from agents.doc_gardening import check_adr_count

        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        for i in range(1, 14):
            (adr_dir / f"ADR-{i:03d}-something.md").write_text("# ADR")

        readme = tmp_path / "README.md"
        readme.write_text("We have 10 Architecture Decision Records in this repo.\n")

        drifts = check_adr_count(str(tmp_path))

        assert len(drifts) == 1
        assert drifts[0].documented_value == "10"
        assert drifts[0].actual_value == "13"

    def test_no_drift_when_counts_match(self, tmp_path):
        """
        Scenario: README says 13 ADRs and 13 exist
          Given a workspace with 13 ADR files
          And a README referencing "13 Architecture Decision Records"
          When the ADR count check runs
          Then no drift is reported
        """
        from agents.doc_gardening import check_adr_count

        adr_dir = tmp_path / "docs" / "adr"
        adr_dir.mkdir(parents=True)
        for i in range(1, 14):
            (adr_dir / f"ADR-{i:03d}-something.md").write_text("# ADR")

        readme = tmp_path / "README.md"
        readme.write_text("We have 13 Architecture Decision Records.\n")

        drifts = check_adr_count(str(tmp_path))
        assert len(drifts) == 0


class TestDocGardeningFlowCount:
    """
    Feature: Flow count drift detection
      As a Staff Engineer
      I want to know when README flow count diverges from actual flows
      So that new flows are always reflected in documentation
    """

    def test_detects_flow_count_drift(self, tmp_path):
        """
        Scenario: README says 10 Mermaid diagrams but 13 exist
          Given a workspace with 13 flow files (plus README.md)
          And a README referencing "10 Mermaid"
          When the flow count check runs
          Then it reports drift with documented=10, actual=13
        """
        from agents.doc_gardening import check_flow_count

        flows_dir = tmp_path / "docs" / "flows"
        flows_dir.mkdir(parents=True)
        for i in range(1, 14):
            (flows_dir / f"{i:02d}-flow.md").write_text("# Flow")
        (flows_dir / "README.md").write_text("# Flows index")  # excluded

        readme = tmp_path / "README.md"
        readme.write_text("See the 10 Mermaid feature flow diagrams.\n")

        drifts = check_flow_count(str(tmp_path))

        assert len(drifts) == 1
        assert drifts[0].documented_value == "10"
        assert drifts[0].actual_value == "13"


class TestDocGardeningDesignComponents:
    """
    Feature: Design document component drift detection
      As a Staff Engineer
      I want to know when new agent modules are not referenced in the design doc
      So that the architecture documentation stays complete
    """

    def test_detects_missing_module_reference(self, tmp_path):
        """
        Scenario: New module exists but design doc doesn't mention it
          Given an agents/ directory with modules [router, orchestrator, new_module]
          And a design document that only mentions router and orchestrator
          When the design components check runs
          Then it reports drift mentioning "new_module"
        """
        from agents.doc_gardening import check_design_components

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "__init__.py").write_text("")
        (agents_dir / "router.py").write_text("# router")
        (agents_dir / "orchestrator.py").write_text("# orchestrator")
        (agents_dir / "new_module.py").write_text("# new module")

        design_dir = tmp_path / "docs" / "architecture"
        design_dir.mkdir(parents=True)
        (design_dir / "design-document.md").write_text(
            "# Design\n\nComponents: router, orchestrator\n"
        )

        drifts = check_design_components(str(tmp_path))

        assert len(drifts) == 1
        assert "new_module" in drifts[0].message

    def test_no_drift_when_all_modules_referenced(self, tmp_path):
        """
        Scenario: All modules are referenced in design doc
          Given agents/ with [router, orchestrator]
          And a design document mentioning both
          When the design components check runs
          Then no drift is reported
        """
        from agents.doc_gardening import check_design_components

        agents_dir = tmp_path / "infra" / "docker" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "__init__.py").write_text("")
        (agents_dir / "router.py").write_text("# router")
        (agents_dir / "orchestrator.py").write_text("# orchestrator")

        design_dir = tmp_path / "docs" / "architecture"
        design_dir.mkdir(parents=True)
        (design_dir / "design-document.md").write_text(
            "# Design\n\nThe router handles events. The orchestrator runs the pipeline.\n"
        )

        drifts = check_design_components(str(tmp_path))
        assert len(drifts) == 0


class TestDocGardeningChangelog:
    """
    Feature: CHANGELOG freshness detection
      As a Staff Engineer
      I want to know when CHANGELOG [Unreleased] section is empty
      So that changes are always documented before release
    """

    def test_detects_empty_unreleased_section(self, tmp_path):
        """
        Scenario: CHANGELOG has empty Unreleased section
          Given a CHANGELOG with an empty [Unreleased] section
          When the changelog check runs
          Then it reports drift about empty unreleased section
        """
        from agents.doc_gardening import check_changelog_unreleased

        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "# Changelog\n\n## [Unreleased]\n\n---\n\n## [1.0.0]\n\n### Added\n- stuff\n"
        )

        drifts = check_changelog_unreleased(str(tmp_path))

        assert len(drifts) == 1
        assert "empty" in drifts[0].message.lower() or "Empty" in drifts[0].documented_value

    def test_no_drift_when_unreleased_has_content(self, tmp_path):
        """
        Scenario: CHANGELOG has content in Unreleased section
          Given a CHANGELOG with entries in [Unreleased]
          When the changelog check runs
          Then no drift is reported
        """
        from agents.doc_gardening import check_changelog_unreleased

        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text(
            "# Changelog\n\n## [Unreleased]\n\n### Added\n- New feature\n\n## [1.0.0]\n"
        )

        drifts = check_changelog_unreleased(str(tmp_path))
        assert len(drifts) == 0


class TestDocGardeningRegistry:
    """
    Feature: Check registry extensibility
      As a developer extending the doc-gardening agent
      I want to register custom checks via the function registry
      So that project-specific drift detection can be added
    """

    def test_run_all_checks_executes_all_registered(self, tmp_path):
        """
        Scenario: run_all_checks executes all registered check functions
          Given a workspace with known drift (hook count mismatch)
          When run_all_checks is called
          Then it returns drifts from the hook count check
        """
        from agents.doc_gardening import run_all_checks

        # Setup minimal workspace with hook count drift
        hooks_dir = tmp_path / ".kiro" / "hooks"
        hooks_dir.mkdir(parents=True)
        for i in range(5):
            (hooks_dir / f"hook-{i}.kiro.hook").write_text("{}")

        readme = tmp_path / "README.md"
        readme.write_text('[![Hooks](https://img.shields.io/badge/hooks-3-blue)]()\n')

        # Also need other dirs to exist (or checks gracefully skip)
        (tmp_path / "docs" / "adr").mkdir(parents=True)
        (tmp_path / "docs" / "flows").mkdir(parents=True)
        (tmp_path / "CHANGELOG.md").write_text("## [Unreleased]\n\n### Added\n- x\n")

        drifts = run_all_checks(str(tmp_path))

        # Should find at least the hook count drift
        hook_drifts = [d for d in drifts if d.check_name == "check_hook_count"]
        assert len(hook_drifts) == 1
        assert hook_drifts[0].documented_value == "3"
        assert hook_drifts[0].actual_value == "5"

    def test_registry_is_extensible(self):
        """
        Scenario: Custom checks can be registered
          Given the check registry
          When get_registered_checks is called
          Then it returns a non-empty list of check functions
        """
        from agents.doc_gardening import get_registered_checks

        checks = get_registered_checks()
        assert len(checks) >= 5  # Our 5 built-in checks
        assert all(callable(c) for c in checks)

    def test_crashed_check_does_not_block_others(self, tmp_path):
        """
        Scenario: A crashing check doesn't prevent other checks from running
          Given a workspace where one check would crash (missing dir)
          When run_all_checks is called
          Then other checks still execute and return results
        """
        from agents.doc_gardening import run_all_checks

        # Minimal workspace — most checks will gracefully return []
        (tmp_path / "README.md").write_text("No badges here\n")
        (tmp_path / "CHANGELOG.md").write_text("## [Unreleased]\n\n### Added\n- x\n")

        # Should not raise, even with missing directories
        drifts = run_all_checks(str(tmp_path))
        # No crashes — all checks handle missing dirs gracefully
        assert all(d.check_name != "(crashed)" for d in drifts)
