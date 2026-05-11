#!/usr/bin/env python3
"""
Generate Distributed Execution Architecture Diagram.

Follows diagram-engineering.md steering rules:
  - LR direction (horizontal spine)
  - weight=10 for spine, weight=1 for branches
  - Numbered flow steps on main path
  - No orphan nodes
  - Convergence eliminated via intermediate nodes
  - Color-coded clusters per domain
  - Descriptive 2-line node labels

Spine: Webhook -> EventBridge -> Orchestrator -> Conductor -> Agents -> SCD -> Delivery
Branches: EFS (workspace), S3 (artifacts), CloudWatch+Portal (observability)

Usage:
    python3 scripts/generate_distributed_architecture.py
    # Output: docs/architecture/distributed-execution.png
"""

from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import ECS, Fargate
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import Eventbridge
from diagrams.aws.management import Cloudwatch
from diagrams.aws.network import CloudFront
from diagrams.aws.storage import EFS, S3
from diagrams.onprem.vcs import Github


def cl(bgcolor, pencolor, fontcolor):
    """Cluster styling helper."""
    return {
        "style": "rounded,filled",
        "fontsize": "11",
        "fontname": "Helvetica Bold",
        "labeljust": "l",
        "penwidth": "2",
        "margin": "14",
        "bgcolor": bgcolor,
        "pencolor": pencolor,
        "fontcolor": fontcolor,
    }


def main():
    with Diagram(
        "",
        filename="docs/architecture/distributed-execution",
        show=False,
        direction="LR",
        graph_attr={
            "pad": "0.4",
            "ranksep": "1.4",
            "nodesep": "0.8",
            "splines": "spline",
            "newrank": "true",
            "fontname": "Helvetica",
            "label": (
                "Distributed Execution Architecture\n"
                "Spine: Webhook > EventBridge > Orchestrator > Conductor > Agent Tasks > SCD > PR Delivery\n"
                "Two-Way Door: execution_mode=monolith|distributed (Terraform variable, <30s rollback)"
            ),
            "labelloc": "t",
            "fontsize": "13",
            "fontcolor": "#333333",
        },
        outformat="png",
    ):
        # -- Control Plane (blue) --
        with Cluster(
            "Control Plane\nIAM \xb7 Secrets Manager \xb7 EventBridge Bus",
            graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8"),
        ):
            webhook = Github("1. GitHub\nWebhook")
            eventbridge = Eventbridge("2. EventBridge\nRoute + Filter")

        # -- Orchestration (gray) --
        with Cluster(
            "Orchestration Plane\n256 CPU \xb7 512MB \xb7 Stateless Dispatcher",
            graph_attr=cl("#f5f5f5", "#666666", "#333333"),
        ):
            orchestrator = ECS("3. Orchestrator\nClone + Dispatch")
            conductor = Fargate("4. Conductor\nPlan Generation")

        # -- Execution Plane (orange) --
        with Cluster(
            "Execution Plane\nParallel ECS Tasks \xb7 Per-Agent Logs \xb7 Independent Retry",
            graph_attr=cl("#fff3e0", "#ef6c00", "#e65100"),
        ):
            agent_a = Fargate("5a. Developer\n4GB reasoning")
            agent_b = Fargate("5b. Security\n4GB reasoning")
            agent_c = Fargate("5c. Reporter\n1GB fast")

        # -- Data Plane (green) --
        with Cluster(
            "Data Plane\nShared Context Document \xb7 EFS Workspace \xb7 S3 Artifacts",
            graph_attr=cl("#e8f5e9", "#43a047", "#2e7d32"),
        ):
            scd = Dynamodb("6. DynamoDB\nSCD (state)")
            efs = EFS("EFS\n/workspaces/")
            s3 = S3("S3\nArtifacts")

        # -- Output (delivery) --
        with Cluster(
            "Delivery",
            graph_attr=cl("#fff3e0", "#ef6c00", "#e65100"),
        ):
            pr = Github("7. Push + PR\nforce-with-lease")

        # -- Observability (purple) --
        with Cluster(
            "Observability\nOTEL \xb7 X-Ray \xb7 Per-Agent Streams",
            graph_attr=cl("#f3e5f5", "#8e24aa", "#6a1b9a"),
        ):
            cw = Cloudwatch("CloudWatch\nPer-Agent Logs")
            portal = CloudFront("Portal\nPipeline Activity")

        # === SPINE (weight=10) ===

        webhook >> Edge(
            label="1. factory-ready", color="#1a73e8", style="bold", weight="10",
        ) >> eventbridge

        eventbridge >> Edge(
            label="2. RunTask", color="#666666", style="bold", weight="10",
        ) >> orchestrator

        orchestrator >> Edge(
            label="3. generate plan", color="#666666", style="bold", weight="10",
        ) >> conductor

        conductor >> Edge(
            label="4. dispatch (parallel)", color="#ef6c00", style="bold", weight="10",
        ) >> agent_a

        agent_a >> Edge(
            label="5. write SCD", color="#43a047", style="bold", weight="10",
        ) >> scd

        scd >> Edge(
            label="6. all stages done", color="#ef6c00", style="bold", weight="10",
        ) >> pr

        # === PARALLEL DISPATCH (weight=3) ===

        conductor >> Edge(
            label="4b. dispatch", color="#ef6c00", weight="3",
        ) >> agent_b

        conductor >> Edge(
            label="4c. dispatch", color="#ef6c00", weight="3",
        ) >> agent_c

        agent_b >> Edge(color="#43a047", weight="2") >> scd
        agent_c >> Edge(color="#43a047", weight="2") >> scd

        # === BRANCHES (weight=1) ===

        # EFS: orchestrator clones once, agents read
        orchestrator >> Edge(
            label="clone repo", color="#43a047", style="dashed", weight="1",
        ) >> efs

        agent_a >> Edge(color="#43a047", style="dashed", weight="1") >> efs
        agent_b >> Edge(color="#43a047", style="dashed", weight="1") >> efs

        # S3: agents persist full outputs
        agent_a >> Edge(
            label="artifacts", color="#43a047", style="dashed", weight="1",
        ) >> s3

        # Observability: agents emit to CloudWatch
        agent_a >> Edge(color="#8e24aa", style="dotted", weight="1") >> cw
        agent_b >> Edge(color="#8e24aa", style="dotted", weight="1") >> cw
        agent_c >> Edge(color="#8e24aa", style="dotted", weight="1") >> cw

        # Portal reads from SCD + CloudWatch
        scd >> Edge(
            label="status API", color="#8e24aa", style="dotted", weight="1",
        ) >> portal
        cw >> Edge(color="#8e24aa", style="dotted", weight="1") >> portal


if __name__ == "__main__":
    main()
    print("\u2705 Diagram generated: docs/architecture/distributed-execution.png")
