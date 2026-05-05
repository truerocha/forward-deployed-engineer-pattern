"""
E2E Orchestrator Test — Validates handle_event() wires all modules correctly.

This test proves the REAL data travel through the Orchestrator:
  Data Contract → Scope Check → Autonomy → Gate Resolution → Execution Plan
  → Constraint Extraction → Agent Execution → Milestone Tracking

Unlike node-scoped tests, this calls orchestrator.handle_event() and asserts
the composed system behavior. Docker-only dependencies (strands, boto3 S3)
are mocked at the boundary.

Anti-pattern avoided: "Node-scoped verification" (COE-052)
"""

import json
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch

import pytest

# ── Mock Docker-only dependencies at import time ──
# strands SDK is only available in the ECS Fargate container.
# It has submodules (strands.models.bedrock) that need explicit mocking.
_strands_mock = MagicMock()
sys.modules.setdefault("strands", _strands_mock)
sys.modules.setdefault("strands.models", _strands_mock.models)
sys.modules.setdefault("strands.models.bedrock", _strands_mock.models.bedrock)
# Make @tool decorator a passthrough
_strands_mock.tool = lambda f: f

# requests (used by tools.py)
sys.modules.setdefault("requests", MagicMock())

# Patch boto3.client to avoid credential issues on module-level S3 client creation
import boto3 as _real_boto3
_real_boto3.client = MagicMock(return_value=MagicMock())


# ═══════════════════════════════════════════════════════════════════
# Feature: Orchestrator E2E Data Travel
# ═══════════════════════════════════════════════════════════════════


class TestOrchestratorE2E:
    """
    Feature: handle_event() wires scope → autonomy → gates → plan → execution
      As a Code Factory
      I want handle_event() to compose all modules correctly
      So that a data contract produces the right pipeline behavior end-to-end
    """

    def _create_orchestrator(self, plans_dir: str):
        """Create an Orchestrator with mocked external dependencies."""
        from agents.orchestrator import Orchestrator
        from agents.registry import AgentRegistry
        from agents.router import AgentRouter

        registry = AgentRegistry(
            default_model_id="anthropic.claude-sonnet-4-20250514-v1:0",
            aws_region="us-east-1",
        )
        router = AgentRouter()

        return Orchestrator(
            registry=registry,
            router=router,
            factory_bucket="test-bucket",
            plans_dir=plans_dir,
        )

    def _make_github_event(self, data_contract: dict) -> dict:
        """Create a GitHub-style EventBridge event that the Router can process."""
        return {
            "source": "fde.github.webhook",
            "detail-type": "GitHub Webhook",
            "detail": {
                "action": "labeled",
                "issue": {
                    "number": 42,
                    "title": data_contract.get("title", "Test task"),
                    "body": self._format_issue_body(data_contract),
                    "labels": [{"name": "factory-ready"}],
                    "repository_url": "https://api.github.com/repos/test-org/test-repo",
                },
            },
        }

    def _format_issue_body(self, data_contract: dict) -> str:
        """Format a data contract as a GitHub issue body matching the form template.

        The Router's _extract_github_contract expects:
        - Task Type: plain text value under ### header
        - Engineering Level: plain text value
        - Tech Stack: checkbox items (- [x] Python)
        - Acceptance Criteria: checklist items (- criterion)
        - Constraints: plain text block
        """
        sections = []
        if data_contract.get("type"):
            sections.append(f"### Task Type\n\n{data_contract['type']}")
        if data_contract.get("level"):
            sections.append(f"### Engineering Level\n\n{data_contract['level']}")
        if data_contract.get("tech_stack"):
            checkboxes = "\n".join(f"- [x] {t}" for t in data_contract["tech_stack"])
            sections.append(f"### Tech Stack\n\n{checkboxes}")
        if data_contract.get("acceptance_criteria"):
            criteria = "\n".join(f"- [x] {c}" for c in data_contract["acceptance_criteria"])
            sections.append(f"### Acceptance Criteria\n\n{criteria}")
        if data_contract.get("constraints"):
            sections.append(f"### Constraints\n\n{data_contract['constraints']}")
        if data_contract.get("related_docs"):
            docs = "\n".join(data_contract["related_docs"])
            sections.append(f"### Related Documents\n\n{docs}")
        return "\n\n".join(sections)

    def test_bugfix_l2_high_confidence_e2e(self):
        """
        Scenario: Bugfix L2 high confidence flows through handle_event
          Given a data contract with type=bugfix, level=L2, high confidence signals
          When handle_event is called on the Orchestrator
          Then:
            1. Task is NOT rejected (scope check passes)
            2. Execution plan is created on disk
            3. Result status is "completed" or "partial" (agents may not be registered)
            4. The plan file exists after execution
        """
        from agents.execution_plan import load_plan
        from pathlib import Path

        with tempfile.TemporaryDirectory() as plans_dir:
            orchestrator = self._create_orchestrator(plans_dir)

            data_contract = {
                "type": "bugfix",
                "level": "L2",
                "tech_stack": ["Python", "FastAPI"],
                "title": "Fix null pointer in user service",
                "acceptance_criteria": [
                    "User endpoint returns 200 for valid requests",
                    "Null user_id returns 400 with error message",
                    "Existing tests still pass",
                ],
                "constraints": "Do not change the API contract",
                "related_docs": ["docs/api-spec.md"],
            }

            event = self._make_github_event(data_contract)
            result = orchestrator.handle_event(event)

            # Should NOT be rejected or skipped
            assert result["status"] not in ("rejected", "skipped"), f"Unexpected: {result}"

            # Should have milestone tracking in result
            assert "milestones_completed" in result
            assert "milestones_total" in result
            assert result["milestones_total"] > 0

            # Execution plan should be persisted
            plan_files = list(Path(plans_dir).rglob("execution_plan.json"))
            assert len(plan_files) >= 1, f"No plan file found after execution"

    def test_out_of_scope_task_rejected_by_orchestrator(self):
        """
        Scenario: Production deploy task is rejected at scope check
          Given a data contract requesting production deploy
          When handle_event is called
          Then the result status is "rejected"
          And the reason is "production_deploy_forbidden"
        """
        with tempfile.TemporaryDirectory() as plans_dir:
            orchestrator = self._create_orchestrator(plans_dir)

            data_contract = {
                "type": "infrastructure",
                "level": "L3",
                "tech_stack": ["Terraform"],
                "title": "Deploy to production immediately",
                "acceptance_criteria": ["Deploy to production and verify"],
            }

            event = self._make_github_event(data_contract)
            result = orchestrator.handle_event(event)

            assert result["status"] == "rejected"
            assert "production_deploy_forbidden" in result["reason"]

    def test_execution_plan_persisted_after_handle_event(self):
        """
        Scenario: Execution plan is saved to disk during handle_event
          Given a valid data contract
          When handle_event completes (even partially)
          Then an execution_plan.json file exists in plans_dir
        """
        from pathlib import Path

        with tempfile.TemporaryDirectory() as plans_dir:
            orchestrator = self._create_orchestrator(plans_dir)

            data_contract = {
                "type": "documentation",
                "level": "L3",
                "tech_stack": ["Python"],
                "title": "Update README",
                "acceptance_criteria": ["README reflects current state", "CHANGELOG updated"],
                "constraints": "No code changes",
            }

            event = self._make_github_event(data_contract)
            result = orchestrator.handle_event(event)

            # If not rejected, a plan should exist
            if result["status"] != "rejected":
                # Find any plan file in the plans_dir
                plan_files = list(Path(plans_dir).rglob("execution_plan.json"))
                assert len(plan_files) >= 1, f"No plan file found. Result: {result}"
