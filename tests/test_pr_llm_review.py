"""
BDD Scenarios: Agent-to-Agent PR Review (Task 5)

These tests validate the LLM-powered PR review capability. Since the LLM
is an external service, tests focus on:
1. Opt-in behavior (env var gating)
2. Prompt construction
3. Response parsing (various formats)
4. Graceful failure handling

Source: OpenAI "review effort handled agent-to-agent"
Impact: Reduces human review time by pre-screening PRs with LLM analysis
"""

import json
import os
from unittest.mock import patch

import pytest


# ═══════════════════════════════════════════════════════════════════
# Feature: LLM PR Review Opt-In Behavior
# ═══════════════════════════════════════════════════════════════════


class TestPRReviewOptIn:
    """
    Feature: LLM PR review is opt-in via environment variable
      As a Factory Operator
      I want LLM review to be opt-in
      So that it doesn't add latency unless explicitly enabled
    """

    def test_review_skipped_when_not_enabled(self):
        """
        Scenario: LLM review is skipped when env var is not set
          Given PR_REVIEW_LLM_ENABLED is not set
          When review_pr_with_llm is called
          Then it returns approved=True with "skipped" summary
          And no LLM call is made
        """
        from agents.pipeline_safety import review_pr_with_llm

        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PR_REVIEW_LLM_ENABLED", None)
            result = review_pr_with_llm(diff_text="+ some code")

        assert result.approved is True
        assert "skipped" in result.summary.lower()

    def test_review_skipped_when_disabled(self):
        """
        Scenario: LLM review is skipped when env var is "false"
          Given PR_REVIEW_LLM_ENABLED=false
          When review_pr_with_llm is called
          Then it returns approved=True with "skipped" summary
        """
        from agents.pipeline_safety import review_pr_with_llm

        with patch.dict(os.environ, {"PR_REVIEW_LLM_ENABLED": "false"}):
            result = review_pr_with_llm(diff_text="+ some code")

        assert result.approved is True
        assert "skipped" in result.summary.lower()

    def test_is_pr_review_enabled_true(self):
        """
        Scenario: is_pr_review_enabled returns True for valid values
          Given PR_REVIEW_LLM_ENABLED is "true", "1", or "yes"
          When is_pr_review_enabled is called
          Then it returns True
        """
        from agents.pipeline_safety import is_pr_review_enabled

        for value in ("true", "1", "yes", "True", "YES"):
            with patch.dict(os.environ, {"PR_REVIEW_LLM_ENABLED": value}):
                assert is_pr_review_enabled() is True

    def test_empty_diff_returns_approved(self):
        """
        Scenario: Empty diff is auto-approved
          Given PR_REVIEW_LLM_ENABLED=true
          And an empty diff
          When review_pr_with_llm is called
          Then it returns approved=True without calling the LLM
        """
        from agents.pipeline_safety import review_pr_with_llm

        with patch.dict(os.environ, {"PR_REVIEW_LLM_ENABLED": "true"}):
            result = review_pr_with_llm(diff_text="")

        assert result.approved is True
        assert "empty" in result.summary.lower()


# ═══════════════════════════════════════════════════════════════════
# Feature: Review Response Parsing
# ═══════════════════════════════════════════════════════════════════


class TestPRReviewResponseParsing:
    """
    Feature: Parse LLM review responses into structured results
      As a Pipeline Safety module
      I want to parse various LLM response formats
      So that the review result is always structured
    """

    def test_parse_clean_json(self):
        """
        Scenario: Parse a clean JSON response
          Given an LLM response with valid JSON
          When _parse_review_response is called
          Then it returns a PRReviewResult with correct fields
        """
        from agents.pipeline_safety import _parse_review_response

        response = json.dumps({
            "approved": False,
            "concerns": ["console.log left in production code"],
            "suggestions": ["Add error handling for edge case"],
            "summary": "Diff has debug code that should be removed",
        })

        result = _parse_review_response(response)

        assert result.approved is False
        assert len(result.concerns) == 1
        assert "console.log" in result.concerns[0]
        assert len(result.suggestions) == 1
        assert "Diff has debug code" in result.summary

    def test_parse_json_in_code_block(self):
        """
        Scenario: Parse JSON wrapped in markdown code block
          Given an LLM response with ```json ... ```
          When _parse_review_response is called
          Then it extracts and parses the JSON correctly
        """
        from agents.pipeline_safety import _parse_review_response

        response = """Here's my review:

```json
{
  "approved": true,
  "concerns": [],
  "suggestions": ["Consider adding a docstring"],
  "summary": "Clean implementation"
}
```
"""
        result = _parse_review_response(response)

        assert result.approved is True
        assert len(result.concerns) == 0
        assert len(result.suggestions) == 1

    def test_parse_invalid_json_graceful(self):
        """
        Scenario: Invalid JSON response is handled gracefully
          Given an LLM response that is not valid JSON
          When _parse_review_response is called
          Then it returns approved=True (non-blocking)
          And summary contains the raw text
        """
        from agents.pipeline_safety import _parse_review_response

        response = "This is not JSON at all, just free text review."
        result = _parse_review_response(response)

        assert result.approved is True
        assert "not JSON" in result.summary or "Could not parse" in result.summary

    def test_parse_partial_json(self):
        """
        Scenario: JSON with missing fields uses defaults
          Given an LLM response with only "approved" field
          When _parse_review_response is called
          Then missing fields get default values
        """
        from agents.pipeline_safety import _parse_review_response

        response = json.dumps({"approved": False})
        result = _parse_review_response(response)

        assert result.approved is False
        assert result.concerns == []
        assert result.suggestions == []


# ═══════════════════════════════════════════════════════════════════
# Feature: Prompt Construction
# ═══════════════════════════════════════════════════════════════════


class TestPRReviewPromptConstruction:
    """
    Feature: Build structured review prompts
      As a Pipeline Safety module
      I want well-structured prompts for the LLM
      So that reviews are consistent and actionable
    """

    def test_prompt_includes_diff(self):
        """
        Scenario: Prompt includes the diff text
          Given a diff and spec
          When _build_review_prompt is called
          Then the prompt contains the diff
        """
        from agents.pipeline_safety import _build_review_prompt

        prompt = _build_review_prompt(
            diff_text="+ def new_function():\n+     return 42",
            spec_content="Add a function that returns 42",
            constraint_text="- No print statements",
        )

        assert "new_function" in prompt
        assert "returns 42" in prompt
        assert "No print statements" in prompt

    def test_prompt_truncates_large_diffs(self):
        """
        Scenario: Large diffs are truncated to prevent token overflow
          Given a diff larger than 8000 characters
          When _build_review_prompt is called
          Then the diff is truncated with a marker
        """
        from agents.pipeline_safety import _build_review_prompt

        large_diff = "+" + "x" * 10000
        prompt = _build_review_prompt(large_diff, "", "")

        assert "truncated" in prompt.lower()
        assert len(prompt) < 12000

    def test_prompt_handles_empty_spec(self):
        """
        Scenario: Empty spec gets a placeholder message
          Given no spec content
          When _build_review_prompt is called
          Then the prompt includes a "no spec" placeholder
        """
        from agents.pipeline_safety import _build_review_prompt

        prompt = _build_review_prompt("+ code", "", "")

        assert "No spec provided" in prompt


# ═══════════════════════════════════════════════════════════════════
# Feature: PRReviewResult Dataclass
# ═══════════════════════════════════════════════════════════════════


class TestPRReviewResult:
    """
    Feature: PRReviewResult is well-structured
      As a consumer of review results
      I want a consistent dataclass with serialization
      So that results can be logged and persisted
    """

    def test_to_dict_serialization(self):
        """
        Scenario: PRReviewResult serializes to dict
          Given a PRReviewResult with all fields
          When to_dict is called
          Then all fields are present in the output
        """
        from agents.pipeline_safety import PRReviewResult

        result = PRReviewResult(
            approved=False,
            concerns=["issue 1"],
            suggestions=["suggestion 1"],
            summary="Needs fixes",
            model_id="test-model",
        )

        d = result.to_dict()
        assert d["approved"] is False
        assert d["concerns"] == ["issue 1"]
        assert d["suggestions"] == ["suggestion 1"]
        assert d["summary"] == "Needs fixes"
        assert d["model_id"] == "test-model"
        assert "timestamp" in d
