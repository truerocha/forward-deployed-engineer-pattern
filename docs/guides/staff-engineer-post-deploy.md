# Staff Engineer: Post-Deploy Operations Guide

> **Prerequisite**: The Code Factory infrastructure has been deployed via `terraform apply`.
> **Audience**: Staff Engineer responsible for onboarding new projects into the factory.
> **Endpoints**: Run `terraform -chdir=infra/terraform output` to get live URLs.

---

## 1. Verify Infrastructure Health

Before onboarding any project, confirm all subsystems are operational:

```bash
bash scripts/validate-e2e-cloud.sh --profile $AWS_PROFILE
```

This checks:
- ✅ ECS cluster is running and accepting tasks
- ✅ ECR image exists and is current (pushed within 24h)
- ✅ EventBridge rules are active on the factory bus
- ✅ Bedrock model (Claude Haiku) is accessible
- ✅ Secrets Manager has valid ALM tokens
- ✅ S3 artifacts bucket is accessible
- ✅ API Gateway webhook endpoint responds

**If any check fails**, the script reports which subsystem is down and suggests remediation.

---

## 2. Onboard a New Project (Phase 0)

### Option A: Local Mode (from Kiro IDE)

1. Open the target project workspace in Kiro (e.g., cognitive-wafr)
2. Trigger the `fde-repo-onboard` hook (Agent Hooks panel → click ▶️)
3. Wait for scan to complete (~2-5 minutes depending on repo size)
4. Review the generated file at `.kiro/steering/fde-draft.md`
5. If satisfied, rename it:
   ```bash
   mv .kiro/steering/fde-draft.md .kiro/steering/fde.md
   ```
6. The FDE is now configured for this project

### Option B: Cloud Mode (via EventBridge)

```bash
AWS_PROFILE=$AWS_PROFILE aws events put-events --entries '[{
  "Source": "fde.onboarding",
  "DetailType": "fde.onboarding.requested",
  "Detail": "{\"repo_url\":\"https://github.com/YOUR_ORG/YOUR_REPO\",\"clone_depth\":1}",
  "EventBusName": "fde-dev-factory-bus"
}]' --region us-east-1
```

Artifacts land in S3 (get bucket name from `terraform output artifacts_bucket`):
- `s3://<BUCKET>/catalogs/{owner}/{repo}/catalog.db`
- `s3://<BUCKET>/catalogs/{owner}/{repo}/steering-draft.md`

Review and copy `steering-draft.md` to the target workspace's `.kiro/steering/fde.md`.

---

## 3. Configure GitHub Webhook

For the factory to receive events when issues are labeled `factory-ready`:

1. Go to the target repo's **Settings → Webhooks → Add webhook**
2. Configure:

| Field | Value |
|-------|-------|
| Payload URL | Get from `terraform -chdir=infra/terraform output webhook_github_url` |
| Content type | `application/json` |
| Secret | *(leave empty for now — add HMAC validation in production)* |
| Events | Select "Issues" and "Labels" |
| Active | ✅ |

3. Save and verify the ping event returns `200 OK`

### Trigger Mechanism

The factory responds to issues labeled `factory-ready`. The PM workflow is:
1. PM creates issue using the [task template](../templates/task-template-github.md)
2. PM adds the `factory-ready` label
3. Factory picks up the issue automatically

---

## 4. Verify End-to-End Flow

After webhook is configured, test with a real issue:

1. Create a test issue on the target repo with title: `[TEST] Factory E2E validation`
2. Add the `factory-ready` label
3. Watch for:
   - ECS task starts (check CloudWatch logs: `/ecs/fde-dev`)
   - Agent posts progress comments on the issue
   - Agent opens a PR when complete
4. Clean up: close the test issue and delete the test PR

---

## 5. Ongoing Operations

### Monitor Pipeline Health

```bash
# Check active/recent ECS tasks
AWS_PROFILE=$AWS_PROFILE aws ecs list-tasks \
  --cluster fde-dev-cluster \
  --region us-east-1

# Check CloudWatch for errors
AWS_PROFILE=$AWS_PROFILE aws logs filter-log-events \
  --log-group-name /ecs/fde-dev \
  --filter-pattern "ERROR" \
  --start-time $(date -v-1H +%s000) \
  --region us-east-1
```

### Re-scan a Project (Incremental)

If the codebase has changed significantly, re-run onboarding:
- The agent detects the commit SHA changed and performs a delta scan
- Only modified files are re-analyzed
- A `steering-diff.md` shows what changed vs. the current steering

### Rotate ALM Tokens

```bash
AWS_PROFILE=$AWS_PROFILE aws secretsmanager put-secret-value \
  --secret-id fde-dev/alm-tokens \
  --secret-string '{"github_pat":"ghp_NEW_TOKEN","gitlab_pat":"","bitbucket_pat":""}' \
  --region us-east-1
```

No restart needed — tokens are fetched at invocation time (ADR-014).

---

## 6. Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| Webhook returns 403 | API Gateway stage not deployed | `aws apigatewayv2 get-stages` — verify `$default` exists |
| ECS task fails immediately | Image not found in ECR | Re-push: `docker push` to ECR |
| Agent can't clone repo | Secrets Manager token expired | Rotate token (see §5) |
| Onboarding times out (>5min) | Repo too large (>100K files) | Set `force_full_scan: false` — sampling kicks in |
| No PR opened | Agent lacks repo write access | Verify GitHub PAT has `repo` scope |
| Bedrock returns 403 | Model access not enabled | AWS Console → Bedrock → Model access → Enable Haiku |

---

## Architecture Reference

```
┌─────────────────────────────────────────────────────────────┐
│                    Code Factory (AWS)                         │
│                                                              │
│  GitHub Issue ──webhook──→ API Gateway ──→ EventBridge       │
│       ↑                                        │             │
│       │ (status comments)                      ▼             │
│       │                              ECS Fargate Task        │
│       │                              ┌──────────────┐        │
│       └──────────────────────────────│ Strands Agent │       │
│                                      │ (Phase 1→4)  │        │
│                                      └──────┬───────┘        │
│                                             │                │
│                              ┌──────────────┼────────────┐   │
│                              ▼              ▼            ▼   │
│                           Bedrock        S3 Bucket    GitHub  │
│                          (Haiku)        (artifacts)   (PR)   │
└─────────────────────────────────────────────────────────────┘
```

---

## Related Documents

- [ADR-009: AWS Cloud Infrastructure](../adr/ADR-009-aws-cloud-infrastructure.md)
- [ADR-014: Secret Isolation](../adr/ADR-014-secret-isolation-and-dag-parallelism.md)
- [ADR-015: Repo Onboarding Agent](../adr/ADR-015-repo-onboarding-phase-zero.md)
- [ADR-016: Ephemeral Catalog](../adr/ADR-016-ephemeral-catalog-data-residency.md)
- [Flow 13: Cloud Orchestration](../flows/13-cloud-orchestration.md)
- [Flow 14: Repo Onboarding](../flows/14-repo-onboarding.md)
- [Deployment Setup](deployment-setup.md)
