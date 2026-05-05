"""
BDD Scenarios: Observability Accessible to Agent (Task 6)

These tests validate that the observability tools (read_factory_metrics,
read_factory_health) are correctly defined and accessible to the Reporting Agent.

Source: OpenAI "logs, metrics, and traces exposed to Codex via local observability stack"
Impact: Gives the agent a feedback loop on its own performance

Note: tools.py requires strands SDK + AWS credentials (Docker-only dependencies).
These tests mock the environment to validate the tool design contract locally.
"""

import json
import sys
import os
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════
# Environment Setup: Mock strands + boto3 for local testing
# ═══════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def mock_cloud_deps(monkeypatch):
    """Mock strands and boto3 so tools.py can be imported locally."""
    # Mock strands
    if "strands" not in sys.modules:
        strands_mock = MagicMock()
        strands_mock.tool = lambda f: f
        sys.modules["strands"] = strands_mock

    # Mock boto3 client creation to avoid credential issues
    mock_s3 = MagicMock()
    mock_boto3 = MagicMock()
    mock_boto3.client.return_value = mock_s3

    # Patch boto3 in the tools module namespace
    monkeypatch.setitem(sys.modules, "boto3", mock_boto3)

    # Also mock requests (used by tools.py)
    if "requests" not in sys.modules:
        sys.modules["requests"] = MagicMock()

    # Force reimport of tools module with mocks
    if "agents.tools" in sys.modules:
        del sys.modules["agents.tools"]

    yield


# ═══════════════════════════════════════════════════════════════════
# Feature: Observability Tools Registration
# ═══════════════════════════════════════════════════════════════════


class TestObservabilityToolsRegistration:
    """
    Feature: Observability tools are registered with the Reporting Agent
      As a Reporting Agent
      I want access to factory metrics and health reports
      So that I can include performance data in completion reports
    """

    def test_read_factory_metrics_in_reporting_tools(self):
        """
        Scenario: read_factory_metrics is available to the Reporting Agent
          Given the REPORTING_TOOLS list
          When inspected
          Then it contains read_factory_metrics
        """
        from agents.tools import REPORTING_TOOLS, read_factory_metrics

        assert read_factory_metrics in REPORTING_TOOLS

    def test_read_factory_health_in_reporting_tools(self):
        """
        Scenario: read_factory_health is available to the Reporting Agent
          Given the REPORTING_TOOLS list
          When inspected
          Then it contains read_factory_health
        """
        from agents.tools import REPORTING_TOOLS, read_factory_health

        assert read_factory_health in REPORTING_TOOLS

    def test_observability_tools_not_in_engineering(self):
        """
        Scenario: Observability tools are NOT in Engineering tools (read-only separation)
          Given the ENGINEERING_TOOLS list
          When inspected
          Then it does NOT contain read_factory_metrics or read_factory_health
        """
        from agents.tools import ENGINEERING_TOOLS, read_factory_metrics, read_factory_health

        assert read_factory_metrics not in ENGINEERING_TOOLS
        assert read_factory_health not in ENGINEERING_TOOLS


# ═══════════════════════════════════════════════════════════════════
# Feature: Tool Function Signatures
# ═══════════════════════════════════════════════════════════════════


class TestObservabilityToolSignatures:
    """
    Feature: Observability tools have correct signatures
      As a Strands agent framework
      I want tools to be properly decorated and typed
      So that they can be invoked correctly
    """

    def test_read_factory_metrics_is_callable(self):
        """
        Scenario: read_factory_metrics is a callable tool
          Given the read_factory_metrics function
          Then it is callable
        """
        from agents.tools import read_factory_metrics

        assert callable(read_factory_metrics)

    def test_read_factory_health_is_callable(self):
        """
        Scenario: read_factory_health is a callable tool
          Given the read_factory_health function
          Then it is callable
        """
        from agents.tools import read_factory_health

        assert callable(read_factory_health)

    def test_read_factory_metrics_has_correct_signature(self):
        """
        Scenario: read_factory_metrics accepts task_id parameter
          Given the read_factory_metrics function
          Then its signature accepts task_id as a string parameter
        """
        import inspect
        from agents.tools import read_factory_metrics

        sig = inspect.signature(read_factory_metrics)
        assert "task_id" in sig.parameters

    def test_read_factory_health_has_correct_signature(self):
        """
        Scenario: read_factory_health accepts window_days parameter
          Given the read_factory_health function
          Then its signature accepts window_days with default 30
        """
        import inspect
        from agents.tools import read_factory_health

        sig = inspect.signature(read_factory_health)
        assert "window_days" in sig.parameters
        assert sig.parameters["window_days"].default == 30
