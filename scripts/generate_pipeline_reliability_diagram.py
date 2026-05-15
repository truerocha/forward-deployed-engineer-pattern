"""
Pipeline Reliability Architecture — ADR-034 Fixes #1-#5

Spine: EventBridge → Router → Orchestrator → Agent → S3/DynamoDB
Branches: Reaper Lambda (scheduled), Retry Utils (inline)
"""
from diagrams import Cluster, Diagram, Edge
from diagrams.aws.compute import Lambda, ECS
from diagrams.aws.database import Dynamodb
from diagrams.aws.integration import Eventbridge
from diagrams.aws.management import Cloudwatch
from diagrams.aws.storage import S3

def cl(bgcolor, pencolor, fontcolor):
    return {
        "style": "rounded,filled", "fontsize": "11",
        "fontname": "Helvetica Bold", "labeljust": "l",
        "penwidth": "2", "margin": "14",
        "bgcolor": bgcolor, "pencolor": pencolor, "fontcolor": fontcolor,
    }

with Diagram("", filename="docs/architecture/pipeline-reliability",
             show=False, direction="LR",
             graph_attr={"ranksep": "1.2", "nodesep": "0.7",
                         "splines": "curved", "newrank": "true", "pad": "0.4"}):

    with Cluster("Event Ingestion", graph_attr=cl("#e8f0fe", "#1a73e8", "#1a73e8")):
        eb = Eventbridge("EventBridge\nWebhook")

    with Cluster("Orchestration\nRetry · Outbox · Plan", graph_attr=cl("#fef7e0", "#f9a825", "#f9a825")):
        orch = ECS("Orchestrator\nFargate")

    with Cluster("Persistence\nAtomic Counters · Plans", graph_attr=cl("#e8f5e9", "#43a047", "#43a047")):
        ddb = Dynamodb("DynamoDB\nTask Queue")

    with Cluster("Artifacts\nClassified Writes", graph_attr=cl("#fff3e0", "#ef6c00", "#e65100")):
        s3 = S3("S3\nResults")

    with Cluster("Self-Healing\nFix #1", graph_attr=cl("#f3e5f5", "#8e24aa", "#6a1b9a")):
        reaper = Lambda("Reaper\nLambda")
        cw = Cloudwatch("CloudWatch\n5min Rule")

    # Main spine (high weight)
    eb >> Edge(label="1. event", weight="10", style="bold", color="#1a73e8") >> orch
    orch >> Edge(label="2. persist plan", weight="10", style="bold", color="#f9a825") >> ddb
    orch >> Edge(label="3. write result", weight="10", style="bold", color="#ef6c00") >> s3

    # Self-healing branch (low weight)
    cw >> Edge(label="trigger", weight="1", style="dashed", color="#8e24aa") >> reaper
    reaper >> Edge(label="reap + retry", weight="1", style="dashed", color="#8e24aa") >> ddb
