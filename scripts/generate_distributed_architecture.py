#!/usr/bin/env python3
"""
Generate distributed architecture diagram for the Forward Deployed AI Pattern.

Spine (LR): EventBridge → Orchestrator (EFS clone) → Conductor (plan) →
            Agent Tasks (parallel) → SCD (DynamoDB) → Push+PR

Clusters:
  - Control Plane (blue): EventBridge, execution_mode switch
  - Orchestration (gray): Orchestrator container, Conductor
  - Execution (orange): Agent Task A/B/C (parallel)
  - Data Plane (green): EFS workspace, DynamoDB SCD, S3 artifacts
  - Observability (purple): CloudWatch per-agent logs, Portal

Usage:
    pip install diagrams
    python3 scripts/generate_distributed_architecture.py
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECS, Fargate
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import Eventbridge
from diagrams.aws.management import Cloudwatch
from diagrams.aws.network import CloudFront
from diagrams.aws.storage import EFS, S3
from diagrams.onprem.vcs import Github


def main():
    graph_attr = {
        "rankdir": "LR",
        "splines": "curved",
        "nodesep": "0.8",
        "ranksep": "1.2",
        "fontsize": "14",
        "fontname": "Helvetica",
        "bgcolor": "white",
    }

    with Diagram(
        "Distributed Execution Architecture",
        filename="docs/architecture/distributed-execution",
        show=False,
        direction="LR",
        graph_attr=graph_attr,
        outformat="png",
    ):
        # ── Control Plane (blue) ──────────────────────────────────────
        with Cluster("Control Plane", graph_attr={"bgcolor": "#e3f2fd", "style": "rounded"}):
            eventbridge = Eventbridge("EventBridge\nTrigger")
            exec_mode = Eventbridge("execution_mode\nswitch")

        # ── Orchestration (gray) ──────────────────────────────────────
        with Cluster("Orchestration", graph_attr={"bgcolor": "#f5f5f5", "style": "rounded"}):
            orchestrator = ECS("Orchestrator\n(EFS clone)")
            conductor = Fargate("Conductor\n(plan generation)")

        # ── Execution (orange) ────────────────────────────────────────
        with Cluster("Execution", graph_attr={"bgcolor": "#fff3e0", "style": "rounded"}):
            agent_a = Fargate("Agent Task A\n(reasoning)")
            agent_b = Fargate("Agent Task B\n(reasoning)")
            agent_c = Fargate("Agent Task C\n(fast)")

        # ── Data Plane (green) ────────────────────────────────────────
        with Cluster("Data Plane", graph_attr={"bgcolor": "#e8f5e9", "style": "rounded"}):
            efs = EFS("EFS\nWorkspace")
            dynamodb = Dynamodb("DynamoDB\nSCD")
            s3 = S3("S3\nArtifacts")

        # ── Observability (purple) ────────────────────────────────────
        with Cluster("Observability", graph_attr={"bgcolor": "#f3e5f5", "style": "rounded"}):
            cloudwatch = Cloudwatch("CloudWatch\nPer-Agent Logs")
            portal = CloudFront("Portal")

        # ── Delivery ──────────────────────────────────────────────────
        push_pr = Github("Push + PR")

        # ── Spine (weight=10 for straight path) ──────────────────────
        eventbridge >> Edge(label="route", color="darkblue", weight="10") >> exec_mode
        exec_mode >> Edge(label="distributed", color="gray", weight="10") >> orchestrator
        orchestrator >> Edge(label="plan", color="gray", weight="10") >> conductor
        conductor >> Edge(label="dispatch", color="darkorange", weight="10") >> agent_a
        agent_a >> Edge(label="SCD write", color="darkgreen", weight="10") >> dynamodb
        dynamodb >> Edge(label="deliver", color="black", weight="10") >> push_pr

        # ── Parallel agent branches (weight=1) ───────────────────────
        conductor >> Edge(label="dispatch", color="darkorange", weight="1") >> agent_b
        conductor >> Edge(label="dispatch", color="darkorange", weight="1") >> agent_c
        agent_b >> Edge(color="darkgreen", weight="1") >> dynamodb
        agent_c >> Edge(color="darkgreen", weight="1") >> dynamodb

        # ── Data plane connections (weight=1) ─────────────────────────
        orchestrator >> Edge(label="clone", color="green", weight="1") >> efs
        agent_a >> Edge(color="green", style="dashed", weight="1") >> efs
        agent_b >> Edge(color="green", style="dashed", weight="1") >> efs
        agent_c >> Edge(color="green", style="dashed", weight="1") >> efs
        agent_a >> Edge(color="green", style="dashed", weight="1") >> s3
        agent_b >> Edge(color="green", style="dashed", weight="1") >> s3
        agent_c >> Edge(color="green", style="dashed", weight="1") >> s3

        # ── Observability connections (weight=1) ──────────────────────
        agent_a >> Edge(color="purple", style="dotted", weight="1") >> cloudwatch
        agent_b >> Edge(color="purple", style="dotted", weight="1") >> cloudwatch
        agent_c >> Edge(color="purple", style="dotted", weight="1") >> cloudwatch
        cloudwatch >> Edge(color="purple", style="dotted", weight="1") >> portal
        dynamodb >> Edge(color="purple", style="dotted", weight="1") >> portal


if __name__ == "__main__":
    main()
    print("✅ Diagram generated: docs/architecture/distributed-execution.png")
