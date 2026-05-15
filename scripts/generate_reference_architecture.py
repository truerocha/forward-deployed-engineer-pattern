#!/usr/bin/env python3
"""Generate AWS Reference Architecture — Autonomous Code Factory.

Updated 2026-05-15 to reflect:
  - ADR-029: Cognitive Autonomy (depth-calibrated squad composition)
  - ADR-030: Cognitive Router (dual-path EventBridge routing)
  - ADR-032: Extension Opt-In System (fde-profile.json)
  - ADR-033: Design Phase Injector (brown-field elevation + DDD)
  - ADR-027: ICRL Feedback Loop (review → learning → rework)
  - ADR-031: Cloudscape Portal (observability dashboard)

ILR Pre-Generation:
  Spine: Engineer → ALM → API GW → EventBridge → Cognitive Router → ECS → Bedrock → S3 → Delivery → Engineer
  Branches: ECS→DynamoDB, DynamoDB→Lambda, S3→CloudFront, ECS→CloudWatch, Lambda→ECS(rework)
  New nodes: Cognitive Router (between EB and ECS), Lambda(Review Feedback)
  Fan-out: ECS=3 (Bedrock, DynamoDB, CloudWatch) ✓
  Convergence: ECS=2 incoming (Router, Lambda) — weight-managed
"""
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Fargate, Lambda
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import Eventbridge, StepFunctions
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

        # Ingestion + Routing
        with Cluster("Ingestion + Routing\nCognitive Router (ADR-030)", graph_attr=cl("#fef7e0", "#f9a825", "#f57f17")):
            apigw = APIGateway("API Gateway\nWebhook Receiver")
            eb = Eventbridge("EventBridge\nFactory Bus")

        # Compute (VPC) — includes Design Phase Injector
        with Cluster("Compute — VPC\nDesign Phase Injector (ADR-033)", graph_attr=cl("#fce4ec", "#e53935", "#b71c1c")):
            ecs = Fargate("ECS Fargate\nConductor + Agents")

        # AI/ML
        with Cluster("AI/ML", graph_attr=cl("#e8f5e9", "#01A88D", "#015c5c")):
            bedrock = Bedrock("Amazon Bedrock\nClaude Sonnet 4.5")

        # Storage
        with Cluster("Storage", graph_attr=cl("#e8f5e9", "#7AA116", "#3d5c0a")):
            s3 = S3("S3 Artifacts\nKMS · Versioned")

        # State + ICRL
        with Cluster("State + ICRL\nEpisode Store (ADR-027)", graph_attr=cl("#f3e5f5", "#C925D1", "#6a1570")):
            ddb = Dynamodb("DynamoDB\n5 Tables + ICRL")
            secrets = SecretsManager("Secrets Mgr\nALM Tokens")

        # Review Feedback Loop
        with Cluster("Review Feedback\nCircuit Breaker (ADR-027)", graph_attr=cl("#fce4ec", "#e53935", "#b71c1c")):
            review_fn = Lambda("Lambda\nReview Classifier")

        # Observability
        with Cluster("Observability\nCloudscape Portal (ADR-031)", graph_attr=cl("#fff3e0", "#ef6c00", "#e65100")):
            cw = Cloudwatch("CloudWatch\n6 Alarms · X-Ray")

        # Delivery
        with Cluster("Delivery", graph_attr=cl("#e8f5e9", "#43a047", "#2e7d32")):
            cf = CloudFront("CloudFront\nDashboard + Portal")
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
        label="④ Cognitive Router → RunTask",
        color="#e53935", style="bold", weight="10",
    ) >> ecs

    ecs >> Edge(
        label="⑤ InvokeModel (design + code)",
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
        label="Task state + DORA + ICRL",
        color="#C925D1", style="dashed", weight="1",
    ) >> ddb

    secrets >> Edge(
        label="ALM tokens",
        color="#C925D1", style="dashed", weight="1",
    ) >> ecs

    # Review Feedback Loop (ADR-027)
    alm >> Edge(
        label="PR review event",
        color="#e53935", style="dashed", weight="1",
    ) >> review_fn

    review_fn >> Edge(
        label="Rework → RunTask",
        color="#e53935", style="dashed", weight="1",
    ) >> ecs

    ecs >> Edge(
        label="Metrics + Traces",
        color="#ef6c00", style="dashed", weight="1",
    ) >> cw

    s3 >> Edge(
        label="Dashboard origin",
        color="#43a047", style="dashed", weight="1",
    ) >> cf

    cf >> Edge(
        label="Cloudscape Portal",
        color="#43a047", style="dashed", weight="1",
    ) >> engineer


print("✓ Reference architecture: docs/architecture/reference-architecture.png")
