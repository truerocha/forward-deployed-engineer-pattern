#!/usr/bin/env python3
"""Generate Autonomous Code Factory architecture diagram.

ILR Analysis:
  Spine: ALM → Spec → Agent Execution → CI/CD → Ship-Readiness → Delivery
  Branches: Notes (off Execution), Meta-Agent (off Delivery), MCP (off all)
  Decorative: Global Steerings, Credentials (in cluster labels)
"""
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda
from diagrams.aws.devtools import Codebuild, Codepipeline
from diagrams.aws.integration import StepFunctions
from diagrams.aws.management import Cloudwatch
from diagrams.aws.storage import S3
from diagrams.onprem.client import User
from diagrams.onprem.vcs import Github
from diagrams.programming.framework import React
from diagrams.custom import Custom
import os

output_dir = "docs/architecture"
os.makedirs(output_dir, exist_ok=True)

def cl(bgcolor, pencolor, fontcolor):
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

with Diagram(
    "",
    filename=f"{output_dir}/autonomous-code-factory",
    show=False,
    direction="LR",
    graph_attr={
        "ranksep": "1.4",
        "nodesep": "0.8",
        "splines": "spline",
        "newrank": "true",
        "pad": "0.5",
        "fontname": "Helvetica",
    },
):
    # === SPINE: Left to Right ===

    # 1. Staff Engineer (Entry)
    with Cluster("Staff Engineer\nFactory Operator", graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8")):
        engineer = User("Writes Specs\nApproves Outcomes")

    # 2. Work Intake
    with Cluster("Work Intake\nGitHub Issues · Asana", graph_attr=cl("#e8f0fe", "#1a73e8", "#1565c0")):
        alm = Github("ALM\nSource")

    # 3. Spec Control Plane
    with Cluster("Spec Control Plane\nNLSpec · BDD Scenarios", graph_attr=cl("#fef7e0", "#f9a825", "#f57f17")):
        spec = S3("Spec\n.kiro/specs/")

    # 4. Agent Execution
    with Cluster("Agent Execution\nDoR · Adversarial · TDD · DoD", graph_attr=cl("#fce4ec", "#e53935", "#b71c1c")):
        agent = StepFunctions("Kiro Agent\n13 Hooks")

    # 5. CI/CD
    with Cluster("CI/CD Pipeline\nGitHub Actions · GitLab CI", graph_attr=cl("#e8f5e9", "#43a047", "#2e7d32")):
        cicd = Codepipeline("Pipeline\nLint · Test · Build")

    # 6. Ship-Readiness
    with Cluster("Ship-Readiness\nDocker · Playwright · BDD", graph_attr=cl("#fff3e0", "#ef6c00", "#e65100")):
        ship = Codebuild("Validation\nE2E · Holdout")

    # 7. Delivery
    with Cluster("Delivery\nSemantic Commit · MR", graph_attr=cl("#e8f5e9", "#43a047", "#1b5e20")):
        delivery = Github("MR/PR\nvia MCP")

    # === SPINE EDGES (high weight) ===
    engineer >> Edge(label="1. Write Spec", color="#1a73e8", style="bold", weight="10") >> alm
    alm >> Edge(label="2. NLSpec", color="#f9a825", style="bold", weight="10") >> spec
    spec >> Edge(label="3. Execute", color="#e53935", style="bold", weight="10") >> agent
    agent >> Edge(label="4. Push", color="#43a047", style="bold", weight="10") >> cicd
    cicd >> Edge(label="5. Validate", color="#ef6c00", style="bold", weight="10") >> ship
    ship >> Edge(label="6. Release", color="#43a047", style="bold", weight="10") >> delivery
    delivery >> Edge(label="7. Approve", color="#1a73e8", style="bold", weight="10") >> engineer

    # === BRANCHES (low weight) ===

    # Notes (off Agent Execution)
    with Cluster("Cross-Session Learning\nNotes · Working Memory", graph_attr=cl("#f3e5f5", "#8e24aa", "#6a1b9a")):
        notes = S3("Notes\n.kiro/notes/")

    agent >> Edge(label="Hindsight", color="#8e24aa", style="dashed", weight="1") >> notes

    # Meta-Agent (off Delivery)
    with Cluster("Meta-Agent\nHealth Report · Prompt Refinement", graph_attr=cl("#f3e5f5", "#8e24aa", "#4a148c")):
        meta = Lambda("Meta\nAnalysis")

    delivery >> Edge(label="Feedback", color="#8e24aa", style="dashed", weight="1") >> meta

print("Architecture diagram generated: docs/architecture/autonomous-code-factory.png")
