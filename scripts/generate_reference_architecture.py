#!/usr/bin/env python3
"""Generate AWS Reference Architecture — Autonomous Code Factory.

Adversarial-reviewed version. Fixes applied:
  - No hardcoded Github icon (system is multi-platform: GitHub/Asana/GitLab)
  - Cluster labels kept to 2 lines max (readable at normal zoom)
  - Narrative moved to edge labels (visible on the flow path)
  - Platform-neutral icons: Git (VCS), User (engineer), Codepipeline (delivery)

ILR Pre-Generation:
  Spine: Engineer → ALM → API GW → EventBridge → ECS → Bedrock → S3 → Delivery → Engineer
  Branches: ECS→DynamoDB, DynamoDB→Lambda, S3→CloudFront, ECS→CloudWatch
  Fan-out: ECS=3 (Bedrock, DynamoDB, CloudWatch) ✓
  Convergence: ECS=2 incoming (EventBridge, Lambda) — weight-managed
"""
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Fargate, Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import Eventbridge
from diagrams.aws.ml import Bedrock
from diagrams.aws.network import APIGateway, CloudFront
from diagrams.aws.security import SecretsManager
from diagrams.aws.storage import S3
from diagrams.aws.management import Cloudwatch
from diagrams.aws.devtools import Codepipeline
from diagrams.onprem.client import User
from diagrams.onprem.vcs import Git
import os

output_dir = "docs/architecture"
os.makedirs(output_dir, exist_ok=True)


def cl(bgcolor, pencolor, fontcolor):
    """Cluster style — concise labels, readable at normal zoom."""
    return {
        "style": "rounded,filled",
        "fontsize": "12",
        "fontname": "Helvetica Bold",
        "labeljust": "l",
        "penwidth": "2",
        "margin": "16",
        "bgcolor": bgcolor,
        "pencolor": pencolor,
        "fontcolor": fontcolor,
    }


with Diagram(
    "Autonomous Code Factory — AWS Reference Architecture",
    filename=f"{output_dir}/reference-architecture",
    show=False,
    direction="LR",
    graph_attr={
        "ranksep": "1.4",
        "nodesep": "0.8",
        "splines": "spline",
        "newrank": "true",
        "pad": "0.5",
        "fontname": "Helvetica",
        "fontsize": "13",
        "fontcolor": "#232F3E",
    },
):

    # ═══ EXTERNAL (outside AWS Cloud) ═══

    with Cluster("Staff Engineer", graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8")):
        engineer = User("Factory Operator\nWrites Specs")

    with Cluster("ALM Platforms", graph_attr=cl("#e8f0fe", "#1a73e8", "#1565c0")):
        alm = Git("GitHub · Asana\nGitLab")

    # ═══ AWS CLOUD ═══

    with Cluster(
        "AWS Cloud",
        graph_attr={
            "style": "rounded,dashed",
            "fontsize": "13",
            "fontname": "Helvetica Bold",
            "labeljust": "l",
            "penwidth": "2",
            "margin": "18",
            "pencolor": "#232F3E",
            "fontcolor": "#232F3E",
            "bgcolor": "#fafbfc",
        },
    ):

        # Ingestion
        with Cluster("Ingestion", graph_attr=cl("#fef7e0", "#f9a825", "#f57f17")):
            apigw = APIGateway("API Gateway\nWebhook Receiver")
            eb = Eventbridge("EventBridge\nFactory Bus")

        # Compute (VPC)
        with Cluster("Compute — VPC", graph_attr=cl("#fce4ec", "#e53935", "#b71c1c")):
            ecs = Fargate("ECS Fargate\nStrands Agent")

        # AI/ML
        with Cluster("AI/ML", graph_attr=cl("#e8f5e9", "#01A88D", "#015c5c")):
            bedrock = Bedrock("Amazon Bedrock\nClaude Sonnet 4.5")

        # Storage
        with Cluster("Storage", graph_attr=cl("#e8f5e9", "#7AA116", "#3d5c0a")):
            s3 = S3("S3 Artifacts\nKMS · Versioned")

        # State
        with Cluster("State + Security", graph_attr=cl("#f3e5f5", "#C925D1", "#6a1570")):
            ddb = Dynamodb("DynamoDB\n4 Tables")
            secrets = SecretsManager("Secrets Mgr\nALM Tokens")

        # DAG Parallelism
        with Cluster("DAG Parallelism", graph_attr=cl("#fce4ec", "#e53935", "#b71c1c")):
            dag_fn = Lambda("Lambda\nFan-Out")

        # Observability
        with Cluster("Observability", graph_attr=cl("#fff3e0", "#ef6c00", "#e65100")):
            cw = Cloudwatch("CloudWatch\n6 Alarms · SNS")

        # Delivery
        with Cluster("Delivery", graph_attr=cl("#e8f5e9", "#43a047", "#2e7d32")):
            cf = CloudFront("CloudFront\nDashboard")
            delivery = Codepipeline("Ship-Ready PR\nvia MCP")

    # ═══ MAIN FLOW — numbered spine (bold, weight=10) ═══

    engineer >> Edge(
        label="① NLSpec + BDD scenarios",
        color="#1a73e8", style="bold", weight="10",
    ) >> alm

    alm >> Edge(
        label="② Webhook (factory-ready)",
        color="#f9a825", style="bold", weight="10",
    ) >> apigw

    apigw >> Edge(
        label="③ PutEvents (data contract)",
        color="#f9a825", style="bold", weight="10",
    ) >> eb

    eb >> Edge(
        label="④ RunTask (FDE protocol)",
        color="#e53935", style="bold", weight="10",
    ) >> ecs

    ecs >> Edge(
        label="⑤ InvokeModel (3 phases)",
        color="#01A88D", style="bold", weight="10",
    ) >> bedrock

    bedrock >> Edge(
        label="⑥ Write results + reports",
        color="#7AA116", style="bold", weight="10",
    ) >> s3

    s3 >> Edge(
        label="⑦ Artifacts ready",
        color="#43a047", style="bold", weight="10",
    ) >> delivery

    delivery >> Edge(
        label="⑧ Approve outcome",
        color="#1a73e8", style="bold", weight="10",
    ) >> engineer

    # ═══ AUXILIARY FLOWS — branches (dashed, weight=1) ═══

    ecs >> Edge(
        label="Task state + DORA",
        color="#C925D1", style="dashed", weight="1",
    ) >> ddb

    secrets >> Edge(
        label="ALM tokens",
        color="#C925D1", style="dashed", weight="1",
    ) >> ecs

    ddb >> Edge(
        label="Streams → READY",
        color="#e53935", style="dashed", weight="1",
    ) >> dag_fn

    dag_fn >> Edge(
        label="Parallel RunTask",
        color="#e53935", style="dashed", weight="1",
    ) >> ecs

    ecs >> Edge(
        label="Metrics + Logs",
        color="#ef6c00", style="dashed", weight="1",
    ) >> cw

    s3 >> Edge(
        label="Dashboard origin",
        color="#43a047", style="dashed", weight="1",
    ) >> cf

    cf >> Edge(
        label="Factory health",
        color="#43a047", style="dashed", weight="1",
    ) >> engineer


print("✓ Reference architecture: docs/architecture/reference-architecture.png")
