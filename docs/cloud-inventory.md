# Code Factory — Cloud Infrastructure Inventory

> Environment: `fde-dev` | Region: `us-east-1` | Account: `785640717688`
> Generated: 2026-05-07

---

## Networking (VPC)

| Component | ID | Details |
|-----------|-----|---------|
| VPC | `vpc-073e4f187210957cc` | CIDR: `10.0.0.0/16` |
| Private Subnet A | `subnet-0fef15518bb1df75c` | ECS tasks run here |
| Private Subnet B | `subnet-015c92d7d747214ae` | ECS tasks run here |
| ECS Security Group | `sg-066a7b2252c1af592` | `fde-dev-ecs-*` |

---

## CDN & Dashboard

| Component | ID | Details |
|-----------|-----|---------|
| CloudFront Distribution | `E2RBVCKZAI7R6I` | Status: Deployed |
| CloudFront Domain | — | `d3btj6a4igoa8k.cloudfront.net` |
| CloudFront ARN | — | `arn:aws:cloudfront::785640717688:distribution/E2RBVCKZAI7R6I` |
| Dashboard URL | — | https://d3btj6a4igoa8k.cloudfront.net |

---

## Storage (S3)

| Component | ID | Details |
|-----------|-----|---------|
| Factory Artifacts Bucket | `fde-dev-artifacts-785640717688` | Versioned, SSE-KMS, public access blocked |
| Dashboard Path | — | `s3://fde-dev-artifacts-785640717688/dashboard/` |
| Results Path | — | `s3://fde-dev-artifacts-785640717688/results/` |
| Extraction Reports Path | — | `s3://fde-dev-artifacts-785640717688/extraction/` |

---

## API Gateway

| Component | ID | Details |
|-----------|-----|---------|
| HTTP API | `4qhn5ly26e` | Name: `fde-dev-webhook-api`, Protocol: HTTP |
| Base URL | — | `https://4qhn5ly26e.execute-api.us-east-1.amazonaws.com` |
| Route: GitHub Webhook | — | `POST /webhook/github` |
| Route: GitLab Webhook | — | `POST /webhook/gitlab` |
| Route: Asana Webhook | — | `POST /webhook/asana` |
| Route: Dashboard Status | — | `GET /status/tasks` |
| Route: Dashboard Health | — | `GET /status/health` |
| Route: Task Reasoning | — | `GET /status/tasks/{task_id}/reasoning` |

---

## Lambda Functions

| Function | ARN | Runtime | Memory |
|----------|-----|---------|--------|
| `fde-dev-webhook-ingest` | `arn:aws:lambda:us-east-1:785640717688:function:fde-dev-webhook-ingest` | Python 3.12 | 128 MB |
| `fde-dev-dashboard-status` | `arn:aws:lambda:us-east-1:785640717688:function:fde-dev-dashboard-status` | Python 3.12 | 128 MB |
| `fde-dev-dag-fanout` | `arn:aws:lambda:us-east-1:785640717688:function:fde-dev-dag-fanout` | Python 3.12 | 128 MB |
| `fde-dev-dead-letter` | `arn:aws:lambda:us-east-1:785640717688:function:fde-dev-dead-letter` | Python 3.12 | 128 MB |

---

## DynamoDB Tables

| Table | Partition Key | Sort Key | Streams | GSIs |
|-------|--------------|----------|---------|------|
| `fde-dev-task-queue` | `task_id` (S) | — | NEW_AND_OLD_IMAGES | `status-created-index` |
| `fde-dev-agent-lifecycle` | `agent_instance_id` (S) | — | — | `status-created-index` |
| `fde-dev-prompt-registry` | `prompt_name` (S) | `version` (N) | — | — |
| `fde-dev-dora-metrics` | `metric_id` (S) | — | — | `task-index`, `type-index` |

---

## ECS (Fargate)

| Component | ID | Details |
|-----------|-----|---------|
| Cluster | `fde-dev-cluster` | ARN: `arn:aws:ecs:us-east-1:785640717688:cluster/fde-dev-cluster` |
| Task Definition (Strands Agent) | `fde-dev-strands-agent:6` | ARN: `arn:aws:ecs:us-east-1:785640717688:task-definition/fde-dev-strands-agent:6` |
| Task Definition (Onboarding) | `fde-dev-onboarding-agent` | Repo onboarding agent |
| Capacity Providers | — | FARGATE, FARGATE_SPOT |

---

## ECR (Container Registry)

| Repository | URL |
|-----------|-----|
| Strands Agent | `785640717688.dkr.ecr.us-east-1.amazonaws.com/fde-dev-strands-agent` |
| Onboarding Agent | `785640717688.dkr.ecr.us-east-1.amazonaws.com/fde-dev-onboarding-agent` |

---

## EventBridge

| Component | ID | Details |
|-----------|-----|---------|
| Custom Event Bus | `fde-dev-factory-bus` | Receives ALM webhooks |
| Rule: GitHub factory-ready | `fde-dev-github-factory-ready` | Triggers ECS RunTask |
| Rule: GitLab factory-ready | `fde-dev-gitlab-factory-ready` | Triggers ECS RunTask |
| Rule: Asana factory-ready | `fde-dev-asana-factory-ready` | Triggers ECS RunTask |
| Rule: Onboarding trigger | `fde-dev-onboarding-trigger` | Triggers onboarding ECS task |
| Rule: Bus catch-all | `fde-dev-bus-catch-all` | Observability |

---

## Secrets Manager

| Secret | ARN |
|--------|-----|
| ALM Tokens (GitHub PAT, GitLab, Asana) | `arn:aws:secretsmanager:us-east-1:785640717688:secret:fde-dev/alm-tokens-R3BDG5` |

---

## CloudWatch

### Log Groups

| Log Group | Retention |
|-----------|-----------|
| `/ecs/fde-dev` | 30 days |
| `/apigateway/fde-dev-webhook` | 14 days |
| `/aws/lambda/fde-dev-dag-fanout` | — |
| `/aws/lambda/fde-dev-webhook-ingest` | — |
| `/aws/lambda/fde-dev-dead-letter` | — |
| `/aws/lambda/fde-dev-onboarding` | — |
| EventBridge bus log | — |

### Alarms

| Alarm | Target | Condition |
|-------|--------|-----------|
| `fde-dev-dag-fanout-errors` | DAG Lambda | Errors > 0 |
| `fde-dev-dag-fanout-throttles` | DAG Lambda | Throttles > 0 |
| `fde-dev-dag-fanout-duration` | DAG Lambda | Duration threshold |
| `fde-dev-dead-letter-invocations` | Dead Letter Lambda | Invocations > 0 |
| `fde-dev-eventbridge-failed-invocations` | EventBridge | Failed invocations |
| `fde-dev-webhook-api-4xx` | API Gateway | 4xx rate |
| `fde-dev-webhook-api-5xx` | API Gateway | 5xx rate |
| `fde-dev-task-queue-read-throttles` | DynamoDB | Read throttles |
| `fde-dev-task-queue-write-throttles` | DynamoDB | Write throttles |
| `fde-dev-onboarding-stage-latency` | Onboarding | Stage latency |
| `fde-dev-onboarding-total-duration` | Onboarding | Total duration |

---

## IAM Roles

| Role | Purpose |
|------|---------|
| `fde-dev-ecs-task-execution` | ECS task execution (pull images, write logs) |
| `fde-dev-ecs-task` | ECS task role (Bedrock, S3, DynamoDB, Secrets Manager) |
| `fde-dev-apigw-eventbridge` | API Gateway → EventBridge PutEvents |
| `fde-dev-eventbridge-ecs` | EventBridge → ECS RunTask |
| `fde-dev-dag-fanout-lambda` | DAG fan-out Lambda execution |
| `fde-dev-dead-letter-lambda` | Dead letter Lambda execution |
| `fde-dev-dashboard-status-role` | Dashboard status Lambda (DynamoDB read) |

---

## Pipeline Flow (End-to-End)

```
ALM (GitHub/GitLab/Asana)
  → API Gateway (4qhn5ly26e)
    → EventBridge (fde-dev-factory-bus)
      → [webhook_ingest Lambda] → DynamoDB (task_queue)
      → [ECS RunTask] → Fargate (fde-dev-strands-agent:6)
        → Bedrock (Claude Sonnet 4) → Agent Pipeline
          → DynamoDB (stage updates + events)
          → S3 (results + extraction reports)
          → GitHub API (PR creation + status comments)
            → Dashboard (d3btj6a4igoa8k.cloudfront.net)
              reads → [dashboard_status Lambda] → DynamoDB
```
