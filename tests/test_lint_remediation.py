"""
BDD Scenarios: Custom Linters with Remediation Messages (Task 3)

These tests validate that lint error output is enriched with actionable
remediation instructions before being returned to the agent in the inner loop.

Source: OpenAI Harness Engineering — "custom lints with error messages that
inject remediation instructions into agent context"

Impact: Increases inner loop first-pass rate by giving the agent a concrete
fix strategy instead of raw error codes.
"""

import pytest


# ═══════════════════════════════════════════════════════════════════
# Feature: Lint Output Enrichment with Remediation Hints
# ═══════════════════════════════════════════════════════════════════


class TestLintRemediationEnrichment:
    """
    Feature: Lint errors include actionable remediation instructions
      As an Engineering Agent in the inner loop
      I want lint errors to tell me HOW to fix them
      So that I can fix on the first retry instead of guessing
    """

    def test_python_e501_line_too_long(self):
        """
        Scenario: Python lint error E501 gets remediation hint
          Given a raw lint output containing error code E501
          When the output is enriched
          Then the enriched output includes "split line at a logical boundary"
        """
        from agents.sdlc_gates import _enrich_lint_output

        raw = "src/main.py:42:89: E501 Line too long (120 > 88 characters)"
        enriched = _enrich_lint_output(raw, tech_stack=["python"])

        assert "E501" in enriched
        assert "Remediation:" in enriched
        assert "Split line at a logical boundary" in enriched

    def test_python_f401_unused_import(self):
        """
        Scenario: Python lint error F401 gets remediation hint
          Given a raw lint output containing error code F401
          When the output is enriched
          Then the enriched output includes guidance about removing or re-exporting
        """
        from agents.sdlc_gates import _enrich_lint_output

        raw = "src/utils.py:1:1: F401 'os' imported but unused"
        enriched = _enrich_lint_output(raw, tech_stack=["python"])

        assert "F401" in enriched
        assert "Remove the unused import" in enriched

    def test_python_f841_unused_variable(self):
        """
        Scenario: Python lint error F841 gets remediation hint
          Given a raw lint output containing error code F841
          When the output is enriched
          Then the enriched output includes guidance about removing or prefixing
        """
        from agents.sdlc_gates import _enrich_lint_output

        raw = "src/handler.py:15:5: F841 Local variable 'result' is assigned but never used"
        enriched = _enrich_lint_output(raw, tech_stack=["python"])

        assert "F841" in enriched
        assert "Remove the unused variable" in enriched

    def test_typescript_no_unused_vars(self):
        """
        Scenario: TypeScript eslint no-unused-vars gets remediation hint
          Given a raw lint output containing rule "no-unused-vars"
          When the output is enriched
          Then the enriched output includes guidance about removing or prefixing
        """
        from agents.sdlc_gates import _enrich_lint_output

        raw = "src/app.ts:10:7  error  'foo' is defined but never used  no-unused-vars"
        enriched = _enrich_lint_output(raw, tech_stack=["typescript"])

        assert "no-unused-vars" in enriched
        assert "Remove the unused variable" in enriched

    def test_typescript_no_console(self):
        """
        Scenario: TypeScript eslint no-console gets remediation hint
          Given a raw lint output containing rule "no-console"
          When the output is enriched
          Then the enriched output includes guidance about structured logging
        """
        from agents.sdlc_gates import _enrich_lint_output

        raw = "src/service.ts:22:5  error  Unexpected console statement  no-console"
        enriched = _enrich_lint_output(raw, tech_stack=["typescript"])

        assert "no-console" in enriched
        assert "structured logger" in enriched

    def test_multiple_errors_each_get_remediation(self):
        """
        Scenario: Multiple lint errors each get their own remediation
          Given raw lint output with E501 and F401 on separate lines
          When the output is enriched
          Then each error line has its own remediation hint
        """
        from agents.sdlc_gates import _enrich_lint_output

        raw = (
            "src/main.py:10:89: E501 Line too long (120 > 88)\n"
            "src/main.py:1:1: F401 'sys' imported but unused"
        )
        enriched = _enrich_lint_output(raw, tech_stack=["python"])

        lines = enriched.splitlines()
        # Should have 4 lines: error1, remediation1, error2, remediation2
        assert len(lines) == 4
        assert "Split line" in lines[1]
        assert "Remove the unused import" in lines[3]

    def test_unknown_error_code_passes_through(self):
        """
        Scenario: Unknown error codes pass through without remediation
          Given a raw lint output with an unrecognized error code
          When the output is enriched
          Then the original line is preserved without remediation
        """
        from agents.sdlc_gates import _enrich_lint_output

        raw = "src/main.py:5:1: X999 Some unknown rule"
        enriched = _enrich_lint_output(raw, tech_stack=["python"])

        assert enriched == raw  # No remediation appended

    def test_empty_output_returns_unchanged(self):
        """
        Scenario: Empty lint output returns unchanged
          Given empty lint output (all checks passed)
          When the output is enriched
          Then the output is returned unchanged
        """
        from agents.sdlc_gates import _enrich_lint_output

        assert _enrich_lint_output("", tech_stack=["python"]) == ""
        assert _enrich_lint_output("   ", tech_stack=["python"]) == "   "

    def test_remediation_map_has_python_entries(self):
        """
        Scenario: REMEDIATION_MAP contains Python error codes
          Given the REMEDIATION_MAP constant
          Then it should contain entries for E501, F401, F841
        """
        from agents.sdlc_gates import REMEDIATION_MAP

        assert "E501" in REMEDIATION_MAP
        assert "F401" in REMEDIATION_MAP
        assert "F841" in REMEDIATION_MAP

    def test_remediation_map_has_typescript_entries(self):
        """
        Scenario: REMEDIATION_MAP contains TypeScript/eslint rules
          Given the REMEDIATION_MAP constant
          Then it should contain entries for no-unused-vars, no-console
        """
        from agents.sdlc_gates import REMEDIATION_MAP

        assert "no-unused-vars" in REMEDIATION_MAP
        assert "no-console" in REMEDIATION_MAP
        assert "@typescript-eslint/no-explicit-any" in REMEDIATION_MAP

    def test_go_staticcheck_remediation(self):
        """
        Scenario: Go staticcheck error gets remediation hint
          Given a raw lint output containing SA4006
          When the output is enriched
          Then the enriched output includes guidance about blank identifier
        """
        from agents.sdlc_gates import _enrich_lint_output

        raw = "main.go:15:2: SA4006: this value of `err` is never used"
        enriched = _enrich_lint_output(raw, tech_stack=["go"])

        assert "SA4006" in enriched
        assert "blank identifier" in enriched

    def test_enrichment_preserves_original_lines(self):
        """
        Scenario: Enrichment preserves original error lines verbatim
          Given a raw lint output line
          When the output is enriched
          Then the original line appears unchanged (remediation is appended below)
        """
        from agents.sdlc_gates import _enrich_lint_output

        raw = "src/main.py:42:89: E501 Line too long (120 > 88 characters)"
        enriched = _enrich_lint_output(raw, tech_stack=["python"])

        # First line should be the original, unchanged
        assert enriched.splitlines()[0] == raw
