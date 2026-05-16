"""
A2A Agent Invocation Tool — Intentional Agent-to-Agent Communication.

This tool enables squad agents to invoke other specialized agents via the
A2A protocol when their reasoning determines they need collaboration.

Unlike the SquadBridge (which is orchestrator-driven), this tool is
AGENT-DRIVEN: the executing agent decides when to call another agent
based on its own cognitive assessment of the task.

Design Principles (from fde-design-swe-sinapses.md):
  - Synapse 6 (Transparency): Agent explicitly states WHY it needs another agent
  - Synapse 7 (Harness Primacy): The tool enforces protocol contracts
  - A2A Protocol: Stateful, async-capable, opaque (black-box) agent communication

When to use this tool:
  - Agent needs factual research it cannot produce from context alone → pesquisa
  - Agent needs a structured deliverable with feedback loop → escrita
  - Agent needs independent adversarial review of its work → revisao

When NOT to use:
  - Simple code lookups (use query_code_kb instead — it's faster)
  - Tasks the agent can complete with its own tools
  - Trivial questions that don't warrant inter-agent communication

Ref: ADR-034 (A2A Protocol), fde-design-swe-sinapses.md (Synapse 6-7)
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# A2A Agent Registry — discovered via Cloud Map DNS in ECS
A2A_AGENTS = {
    "pesquisa": {
        "endpoint": os.environ.get("A2A_PESQUISA_URL", "http://pesquisa.fde.local:9001"),
        "description": "Factual research agent — collects data, attributes sources, scores confidence",
        "use_when": "You need verified facts, source attribution, or data collection that requires web/API access",
    },
    "escrita": {
        "endpoint": os.environ.get("A2A_ESCRITA_URL", "http://escrita.fde.local:9002"),
        "description": "Engineering/writing agent — produces structured deliverables with iterative rework",
        "use_when": "You need a structured document, code artifact, or deliverable that benefits from feedback loops",
    },
    "revisao": {
        "endpoint": os.environ.get("A2A_REVISAO_URL", "http://revisao.fde.local:9003"),
        "description": "Review agent — provides independent quality assessment with structured feedback",
        "use_when": "You need adversarial review, quality scoring, or approval/rejection of your work",
    },
}


def invoke_a2a_agent(
    agent_name: str,
    task_description: str,
    context: str = "",
    wait_for_completion: bool = True,
) -> dict[str, Any]:
    """Invoke a specialized A2A agent for collaboration.

    Use this tool when your reasoning determines you need another agent's
    capabilities. State clearly WHY you need this agent — transparency
    in inter-agent communication is a governance requirement.

    Args:
        agent_name: Which agent to invoke. One of: "pesquisa", "escrita", "revisao"
        task_description: Clear description of what you need the agent to do.
            Be specific — the receiving agent is autonomous and will interpret this.
        context: Optional context to pass (research data, prior work, constraints).
            Keep concise — the agent has its own tools for deep investigation.
        wait_for_completion: If True, blocks until the agent responds.
            If False, returns a workflow_id for async polling.

    Returns:
        Dict with the agent's response:
        - status: "completed" | "failed" | "pending"
        - result: The agent's structured output (varies by agent type)
        - workflow_id: For tracking in DynamoDB checkpoints
        - response_ms: Latency of the invocation

    Example usage in agent reasoning:
        "I need factual data about AWS Lambda cold start times that I cannot
        produce from my current context. Invoking pesquisa agent."

        result = invoke_a2a_agent(
            agent_name="pesquisa",
            task_description="Research AWS Lambda cold start times for Python 3.12 runtime with 512MB memory. Include p50 and p99 latency data from official AWS documentation.",
            context="Building a performance analysis for the task dispatch pipeline."
        )
    """
    if agent_name not in A2A_AGENTS:
        return {
            "status": "failed",
            "error": f"Unknown agent '{agent_name}'. Available: {list(A2A_AGENTS.keys())}",
            "result": None,
        }

    agent_config = A2A_AGENTS[agent_name]
    endpoint = agent_config["endpoint"]

    logger.info(
        "A2A invocation: %s → %s | task: %s",
        "self", agent_name, task_description[:80],
    )

    try:
        import httpx
        from src.core.a2a.observability import trace_a2a_invocation

        # Construct A2A JSON-RPC payload
        payload = {
            "jsonrpc": "2.0",
            "method": "tasks/send",
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"type": "text", "text": task_description}],
                },
                "metadata": {
                    "context": context,
                    "source_agent": os.environ.get("AGENT_NAME", "squad-agent"),
                    "task_id": os.environ.get("TASK_ID", "unknown"),
                },
            },
            "id": f"a2a-{agent_name}-{os.urandom(4).hex()}",
        }

        timeout = 120.0 if wait_for_completion else 10.0

        with trace_a2a_invocation(agent_name, task_description, endpoint):
            response = httpx.post(
                f"{endpoint}/a2a",
                json=payload,
                timeout=timeout,
                headers={"Content-Type": "application/json"},
            )

        if response.status_code == 200:
            result_data = response.json()
            return {
                "status": "completed",
                "result": result_data.get("result", result_data),
                "workflow_id": result_data.get("id", ""),
                "response_ms": int(response.elapsed.total_seconds() * 1000),
                "agent": agent_name,
            }
        else:
            return {
                "status": "failed",
                "error": f"HTTP {response.status_code}: {response.text[:200]}",
                "result": None,
                "agent": agent_name,
            }

    except ImportError as e:
        # Graceful degradation if httpx not available
        logger.warning("A2A tool unavailable (missing dep): %s", str(e))
        return {
            "status": "failed",
            "error": f"A2A client dependency missing: {str(e)}",
            "result": None,
        }
    except httpx.ConnectError:
        return {
            "status": "failed",
            "error": f"Cannot reach {agent_name} at {endpoint} — service may not be running",
            "result": None,
            "agent": agent_name,
        }
    except httpx.TimeoutException:
        return {
            "status": "failed",
            "error": f"Timeout invoking {agent_name} (>{timeout}s)",
            "result": None,
            "agent": agent_name,
        }
    except Exception as e:
        logger.error("A2A invocation failed: %s", str(e)[:200])
        return {
            "status": "failed",
            "error": str(e)[:200],
            "result": None,
            "agent": agent_name,
        }


def list_a2a_agents() -> dict[str, Any]:
    """List available A2A agents and their capabilities.

    Use this to discover what agents are available for collaboration
    before deciding whether to invoke one.

    Returns:
        Dict of available agents with descriptions and usage guidance.
    """
    return {
        name: {
            "description": config["description"],
            "use_when": config["use_when"],
            "endpoint": config["endpoint"],
        }
        for name, config in A2A_AGENTS.items()
    }
