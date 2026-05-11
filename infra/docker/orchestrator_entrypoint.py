"""
Orchestrator Entrypoint — Distributed Mode ECS Task Entry Point.

This is the entry point for the lightweight orchestrator container.
It receives the same EventBridge event as the monolith but instead of
executing agents sequentially in-process, it:

  1. Routes the event and extracts the data contract
  2. Clones the repo to EFS (shared workspace)
  3. Runs the Conductor to generate a WorkflowPlan
  4. Dispatches each agent as a separate ECS task via RunTask
  5. Monitors completion via DynamoDB SCD polling
  6. Handles push + PR creation after all agents complete

The orchestrator is stateless and lightweight (256 CPU, 512MB).
All heavy computation happens in the agent tasks it dispatches.

Feature flag: EXECUTION_MODE=distributed (this entrypoint)
Fallback: EXECUTION_MODE=monolith (original agent_entrypoint.py)

Ref: docs/design/distributed-squad-execution.md
Ref: ADR-020 (Conductor Orchestration Pattern)
"""

import json
import logging
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("fde.orchestrator-distributed")


def main() -> None:
    """Entry point for the distributed orchestrator ECS task."""
    logger.info("FDE Distributed Orchestrator starting...")
    logger.info(
        "Region: %s | Cluster: %s | Env: %s",
        os.environ.get("AWS_REGION", "us-east-1"),
        os.environ.get("ECS_CLUSTER_ARN", "not-set"),
        os.environ.get("ENVIRONMENT", "dev"),
    )

    # Write health sentinel
    try:
        with open("/tmp/orchestrator_ready", "w") as f:
            f.write("ready")
    except OSError:
        pass

    # Reconstruct the event from environment variables
    event = _reconstruct_event()
    if not event:
        logger.error("No event data found in environment. Exiting.")
        sys.exit(1)

    logger.info(
        "Event received: source=%s, issue=#%s",
        event.get("source", "unknown"),
        event.get("detail", {}).get("issue", {}).get("number", "?"),
    )

    # Import orchestration components
    from src.core.orchestration.conductor_integration import (
        should_use_conductor,
        generate_conductor_manifest,
    )
    from src.core.orchestration.distributed_orchestrator import (
        DistributedOrchestrator,
        SquadManifest,
        AgentSpec,
    )

    # Import monolith router for event parsing (reuses existing logic)
    sys.path.insert(0, "/app")
    from agents.router import AgentRouter
    from agents.scope_boundaries import check_scope
    from agents.autonomy import compute_autonomy_level
    from agents import task_queue

    # Route the event
    router = AgentRouter()
    decision = router.route_event(event)

    if not decision.should_process:
        logger.info("Event skipped: %s", decision.skip_reason)
        sys.exit(0)

    data_contract = decision.data_contract
    task_id = data_contract.get("task_id", f"TASK-{int(time.time())}")

    # Scope check
    scope_result = check_scope(data_contract)
    if not scope_result.in_scope:
        logger.warning("Task rejected by scope: %s", scope_result.rejection_reason)
        sys.exit(0)

    # Autonomy level
    autonomy_result = compute_autonomy_level(data_contract)
    organism_level = _infer_organism_level(data_contract)

    logger.info(
        "Task %s: autonomy=%s, organism=%s, confidence=%s",
        task_id, autonomy_result.level, organism_level, scope_result.confidence_level,
    )

    # Update task queue
    task_queue.update_task_stage(task_id, "orchestrating")
    task_queue.append_task_event(
        task_id, "reasoning",
        "Distributed orchestrator activated",
        phase="intake",
        criteria=f"Autonomy: {autonomy_result.level} | Organism: {organism_level}",
        context="Using Conductor pattern for dynamic workflow generation. "
                "Each agent runs as an independent ECS task with isolated resources.",
    )

    # Generate workflow plan via Conductor
    if should_use_conductor(organism_level):
        logger.info("Conductor activated for organism level %s", organism_level)
        manifest = generate_conductor_manifest(
            task_id=task_id,
            project_id=data_contract.get("repo", "unknown"),
            task_description=decision.prompt[:500],
            organism_level=organism_level,
            user_value_statement=data_contract.get("title", ""),
            autonomy_level=int(autonomy_result.level.replace("L", "")),
            knowledge_context={"repo": data_contract.get("repo", "")},
        )
    else:
        logger.info("Simple task (organism %s) - using default manifest", organism_level)
        manifest = _build_default_manifest(task_id, data_contract, autonomy_result)

    # Clone repo to EFS workspace
    workspace_path = _clone_to_efs(task_id, data_contract)

    # Dispatch via DistributedOrchestrator
    orchestrator = DistributedOrchestrator(
        ecs_cluster_arn=os.environ.get("ECS_CLUSTER_ARN", ""),
        agent_task_family=os.environ.get("AGENT_TASK_FAMILY", ""),
        agent_subnets=os.environ.get("AGENT_SUBNETS", "").split(","),
        agent_security_group=os.environ.get("AGENT_SECURITY_GROUP", ""),
        scd_table=os.environ.get("SCD_TABLE", ""),
        metrics_table=os.environ.get("METRICS_TABLE", ""),
    )

    logger.info(
        "Dispatching %d agents across %d stages",
        manifest.total_agents(),
        manifest.stage_count(),
    )

    results = orchestrator.execute(manifest)

    # Assess results
    all_completed = all(r.status.value == "COMPLETED" for r in results)
    logger.info(
        "Pipeline %s: %d/%d stages completed",
        "COMPLETED" if all_completed else "PARTIAL",
        sum(1 for r in results if r.status.value == "COMPLETED"),
        len(results),
    )

    # Push + PR (if workspace ready and all stages completed)
    if all_completed and workspace_path:
        task_queue.update_task_stage(task_id, "review")
        _push_and_deliver(task_id, workspace_path, data_contract)

    task_queue.update_task_stage(task_id, "completion")
    task_queue.append_task_event(
        task_id, "reasoning",
        f"Pipeline {'completed' if all_completed else 'partial'}",
        phase="completion",
        criteria=f"Stages: {sum(1 for r in results if r.status.value == 'COMPLETED')}/{len(results)}",
        context="Distributed execution finished. All agent outputs persisted in SCD.",
    )

    logger.info("Distributed orchestrator complete. Exiting.")
    sys.exit(0 if all_completed else 1)


def _reconstruct_event() -> dict:
    """Reconstruct EventBridge event from environment variables."""
    event_json = os.environ.get("EVENT_JSON", "")
    if event_json:
        return json.loads(event_json)

    source = os.environ.get("EVENT_SOURCE", "")
    detail_type = os.environ.get("EVENT_DETAIL_TYPE", "")
    detail_json = os.environ.get("EVENT_DETAIL", "")

    if source and detail_json:
        return {
            "source": source,
            "detail-type": detail_type,
            "detail": json.loads(detail_json),
        }

    return {}


def _infer_organism_level(data_contract: dict) -> str:
    """Infer organism level from task characteristics."""
    task_type = data_contract.get("type", "feature")
    if task_type == "bugfix":
        return "O2"
    elif task_type == "refactor":
        return "O3"
    elif task_type == "feature":
        return "O3"
    elif task_type == "architecture":
        return "O4"
    return "O3"


def _build_default_manifest(task_id: str, data_contract: dict, autonomy_result) -> SquadManifest:
    """Build a simple default manifest for O1/O2 tasks."""
    from src.core.orchestration.distributed_orchestrator import AgentSpec, SquadManifest

    return SquadManifest(
        task_id=task_id,
        project_id=data_contract.get("repo", "unknown"),
        organism_level="O2",
        user_value_statement=data_contract.get("title", ""),
        autonomy_level=int(autonomy_result.level.replace("L", "")),
        stages={
            1: [AgentSpec(role="swe-developer-agent", model_tier="reasoning", stage=1)],
            2: [AgentSpec(role="reporting-agent", model_tier="fast", stage=2)],
        },
    )


def _clone_to_efs(task_id: str, data_contract: dict) -> str:
    """Clone the target repo to EFS workspace."""
    import subprocess
    import boto3

    repo = data_contract.get("repo", "")
    if not repo:
        logger.warning("No repo in data contract - skipping clone")
        return ""

    workspace_base = "/workspaces"
    workspace_path = f"{workspace_base}/{task_id}/{repo.split('/')[-1]}"

    # Fetch PAT
    secrets_id = f"fde-{os.environ.get('ENVIRONMENT', 'dev')}/alm-tokens"
    try:
        client = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        secret = client.get_secret_value(SecretId=secrets_id)
        tokens = json.loads(secret["SecretString"])
        github_pat = tokens.get("github_pat", "")
    except Exception as e:
        logger.error("Failed to fetch PAT: %s", e)
        return ""

    clone_url = f"https://x-access-token:{github_pat}@github.com/{repo}.git"

    try:
        os.makedirs(os.path.dirname(workspace_path), exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--depth", "50", clone_url, workspace_path],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logger.error("Clone failed: %s", result.stderr[:200])
            return ""

        logger.info("Cloned %s to EFS: %s", repo, workspace_path)
        return workspace_path

    except Exception as e:
        logger.error("Clone exception: %s", e)
        return ""


def _push_and_deliver(task_id: str, workspace_path: str, data_contract: dict) -> None:
    """Push and create PR from the EFS workspace."""
    logger.info("Push + PR delivery from EFS workspace: %s", workspace_path)
    # Agents write to EFS during their execution.
    # After all agents complete, the orchestrator pushes the combined result.
    # Reuses the workspace_setup.push_and_create_pr logic.
    from agents.workspace_setup import WorkspaceContext, push_and_create_pr

    repo = data_contract.get("repo", "")
    issue_number = data_contract.get("issue_number", 0)
    title = data_contract.get("title", "Task completion")

    workspace = WorkspaceContext(
        repo_path=workspace_path,
        branch_name=f"feature/GH-{issue_number}-distributed",
        repo_full_name=repo,
        issue_number=issue_number,
        ready=True,
    )

    pr_title = f"feat(GH-{issue_number}): {title}"
    pr_body = (
        f"## Distributed Pipeline Execution\n\n"
        f"**Task ID**: {task_id}\n"
        f"**Mode**: Distributed (Conductor pattern)\n"
        f"**Issue**: #{issue_number}\n"
    )

    result = push_and_create_pr(workspace, pr_title, pr_body)
    if result.get("pr_url"):
        logger.info("PR delivered: %s", result["pr_url"])
    else:
        logger.warning("PR delivery failed: %s", result.get("error", "unknown"))


if __name__ == "__main__":
    main()
