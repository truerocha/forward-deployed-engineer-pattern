# AWS Deployment Setup Guide

> Time: 10–15 minutes (first time), 2 minutes (subsequent deploys)
> Prerequisite: AWS account with AdministratorAccess (or scoped IAM permissions)
> Validation: `terraform -chdir=infra/terraform validate`

This guide covers the prerequisites for deploying the Code Factory infrastructure stack to AWS via Terraform.

---

## Prerequisites

| Tool | Minimum Version | Install |
|------|----------------|---------|
| Terraform | >= 1.5.0 | `brew install terraform` or [terraform.io/downloads](https://developer.hashicorp.com/terraform/downloads) |
| AWS CLI v2 | >= 2.x | `brew install awscli` or [docs.aws.amazon.com/cli](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) |
| Docker | >= 24.x | [docker.com/get-docker](https://www.docker.com/get-docker) (needed for building agent images) |
| Python | >= 3.12 | `brew install python@3.12` or [python.org](https://www.python.org/downloads/) |

---

## Step 1: Configure AWS SSO Profile

The factory uses AWS IAM Identity Center (SSO) for authentication. Configure your profile once:

```bash
aws configure sso --profile your-sso-profile
```

You'll be prompted for:

| Field | Example Value |
|-------|--------------|
| SSO session name | `my-sso` |
| SSO start URL | `https://your-org.awsapps.com/start` |
| SSO region | `us-east-1` |
| SSO registration scopes | `sso:account:access` |
| Account ID | `YOUR_ACCOUNT_ID` |
| Role name | `AdministratorAccess` |
| CLI default region | `us-east-1` |
| CLI default output | `json` |

This creates an entry in `~/.aws/config`. You only need to do this once.

### Alternative: Static Credentials

If you're not using SSO, configure static credentials:

```bash
aws configure --profile your-sso-profile
# Enter: AWS Access Key ID, Secret Access Key, region, output format
```

Or export directly:

```bash
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_DEFAULT_REGION="us-east-1"
```

---

## Step 2: Authenticate (Every Session)

SSO sessions expire (typically 8–12 hours). Before any Terraform operation, authenticate:

```bash
aws sso login --profile your-sso-profile
```

This opens a browser for the OAuth flow. After approval, your session is cached locally.

### Verify Authentication

```bash
aws sts get-caller-identity --profile your-sso-profile
```

Expected output:

```json
{
  "UserId": "AROA...:your-username",
  "Account": "YOUR_ACCOUNT_ID",
  "Arn": "arn:aws:sts::YOUR_ACCOUNT_ID:assumed-role/AWSReservedSSO_AdministratorAccess_.../your-username"
}
```

### Set the Profile for Terraform

Terraform reads credentials via the `AWS_PROFILE` environment variable:

```bash
export AWS_PROFILE=your-sso-profile
```

Add to your shell rc file (`~/.zshrc` or `~/.bashrc`) for persistence:

```bash
echo 'export AWS_PROFILE=your-sso-profile' >> ~/.zshrc
```

---

## Step 3: Configure Terraform Variables

The stack uses a variables file. Copy the example and customize:

```bash
cp infra/terraform/factory.tfvars.example infra/terraform/factory.tfvars
```

Edit `infra/terraform/factory.tfvars`:

```hcl
# Required
aws_region  = "us-east-1"
environment = "dev"            # dev | staging | prod

# Optional — observability
alert_email = "ops@your-org.com"  # Leave empty to skip SNS email subscription

# Optional — compute
agent_cpu    = "1024"          # 1 vCPU
agent_memory = "2048"          # 2 GB
```

Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `environment` | `dev` | Controls naming, retention policies, and force-delete behavior |
| `alert_email` | `""` | Email for pipeline failure alerts (SNS subscription) |
| `bedrock_model_id` | `anthropic.claude-sonnet-4-5-20250929-v1:0` | Foundation model for agent inference |
| `enable_ecs_service` | `false` | Set `true` for always-on agent (vs. event-triggered tasks) |
| `enable_agentcore` | `false` | Enable Bedrock AgentCore Runtime integration |

---

## Step 4: Initialize Terraform

Run once (or after adding new providers/modules):

```bash
terraform -chdir=infra/terraform init
```

If you've previously initialized and need to update providers:

```bash
terraform -chdir=infra/terraform init -upgrade
```

---

## Step 5: Plan and Apply

Always plan before applying:

```bash
# Plan (review what will be created)
AWS_PROFILE=your-sso-profile terraform -chdir=infra/terraform plan -var-file=factory.tfvars

# Apply (create resources)
AWS_PROFILE=your-sso-profile terraform -chdir=infra/terraform apply -var-file=factory.tfvars
```

Expected plan output for a fresh deployment: **74 to add, 0 to change, 0 to destroy**.

### What Gets Created

| Resource Category | Count | Examples |
|-------------------|-------|---------|
| Networking (VPC) | ~12 | VPC, subnets, route tables, NAT gateway, security groups |
| Compute (ECS) | ~8 | Cluster, task definition, capacity providers, ECR repo |
| Storage | ~6 | S3 bucket, DynamoDB tables (4), Secrets Manager |
| Eventing | ~8 | EventBridge bus + rules, API Gateway + routes |
| DAG Fan-Out | ~6 | Lambda, IAM role, DynamoDB Stream mapping, log group |
| Observability | ~12 | SNS topic, dead-letter Lambda, 6 CloudWatch alarms, IAM, logs |
| IAM | ~10 | Task roles, execution roles, policies |

---

## Common Errors

| Error | Cause | Fix |
|-------|-------|-----|
| `No valid credential sources found` | SSO session expired or `AWS_PROFILE` not set | `aws sso login --profile your-sso-profile` then `export AWS_PROFILE=your-sso-profile` |
| `No configuration files` | Running terraform from wrong directory | Use `-chdir=infra/terraform` or `cd infra/terraform` first |
| `failed to refresh cached credentials, no EC2 IMDS role found` | Running outside AWS (no instance role) and no local credentials | Authenticate via SSO or static credentials |
| `Error: Unsupported Terraform Core version` | Terraform < 1.5.0 | Upgrade: `brew upgrade terraform` |
| `command not found: terraform` | Terraform not installed | `brew install terraform` |

---

## Teardown

To destroy all resources:

```bash
AWS_PROFILE=your-sso-profile terraform -chdir=infra/terraform destroy -var-file=factory.tfvars
```

Or use the project teardown script:

```bash
bash scripts/teardown-fde.sh --terraform
```

Dry-run first:

```bash
bash scripts/teardown-fde.sh --dry-run
```

---

## Post-Deploy: Store ALM Tokens

After the stack is deployed, store your ALM tokens in Secrets Manager (see [auth-setup.md](./auth-setup.md) for token creation):

```bash
AWS_PROFILE=your-sso-profile aws secretsmanager put-secret-value \
  --secret-id "fde-dev/alm-tokens" \
  --secret-string '{
    "GITHUB_TOKEN": "ghp_...",
    "ASANA_ACCESS_TOKEN": "1/...",
    "GITLAB_TOKEN": "glpat-..."
  }'
```

---

## Post-Deploy: Confirm SNS Subscription

If you set `alert_email`, check your inbox for the SNS subscription confirmation email and click **Confirm subscription**. Until confirmed, alerts won't be delivered.

---

## Quick Reference (Copy-Paste)

```bash
# Full deploy sequence
aws sso login --profile your-sso-profile
export AWS_PROFILE=your-sso-profile
terraform -chdir=infra/terraform init
terraform -chdir=infra/terraform plan -var-file=factory.tfvars
terraform -chdir=infra/terraform apply -var-file=factory.tfvars
```

---

## Related

- ALM token setup: `docs/guides/auth-setup.md`
- Architecture: `docs/adr/ADR-009-aws-cloud-infrastructure.md`
- Observability: `docs/adr/ADR-014-secret-isolation-and-dag-parallelism.md`
- Cloud orchestration flow: `docs/flows/13-cloud-orchestration.md`
- E2E validation: `scripts/validate-e2e-cloud.sh`
