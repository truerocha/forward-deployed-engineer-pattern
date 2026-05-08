#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Deploy Dashboard — Uploads the Code Factory dashboard to S3
# and injects runtime configuration (API URL) from Terraform outputs.
#
# Usage:
#   bash scripts/deploy-dashboard.sh [--profile PROFILE]
#
# What it does:
#   1. Reads API Gateway URL from terraform output (no hardcoding)
#   2. Injects the URL into the dashboard HTML via <meta> tag
#   3. Uploads to S3 with SSE-S3 (AES256) encryption (required for CloudFront OAC)
#   4. Invalidates CloudFront cache
#   5. Prints the dashboard URL
#
# Prerequisites:
#   - AWS credentials authenticated (aws sso login)
#   - Terraform applied (infra/terraform)
#   - infra/dashboard/index.html exists
# ═══════════════════════════════════════════════════════════════════

set -uo pipefail

REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
TF_DIR="infra/terraform"
DASHBOARD_SRC="infra/dashboard/index.html"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --profile) export AWS_PROFILE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    *) echo "Usage: bash scripts/deploy-dashboard.sh [--profile PROFILE]"; exit 1 ;;
  esac
done

echo "━━━ Deploy Dashboard ━━━"

# 1. Resolve values from Terraform outputs (no hardcoded IDs)
echo "  → Reading terraform outputs..."
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "$REGION" 2>/dev/null)
if [[ -z "$ACCOUNT_ID" ]]; then
  echo "  ❌ AWS credentials not valid. Run: aws sso login"
  exit 1
fi

API_URL=$(terraform -chdir="$TF_DIR" output -raw webhook_api_url 2>/dev/null)
BUCKET=$(terraform -chdir="$TF_DIR" output -raw artifacts_bucket 2>/dev/null)
DASHBOARD_URL=$(terraform -chdir="$TF_DIR" output -raw dashboard_url 2>/dev/null || echo "")

if [[ -z "$API_URL" || -z "$BUCKET" ]]; then
  echo "  ❌ Cannot read terraform outputs. Run: terraform apply -var-file=factory.tfvars"
  exit 1
fi

echo "  ✅ Account: $ACCOUNT_ID"
echo "  ✅ API URL: $API_URL"
echo "  ✅ Bucket: $BUCKET"

# 2. Inject API URL into dashboard HTML
echo "  → Injecting API URL into dashboard..."
TEMP_DIR="/tmp/dashboard-deploy-$$"
mkdir -p "$TEMP_DIR"
cp -r "$(dirname "$DASHBOARD_SRC")/"* "$TEMP_DIR/"
sed -i.bak "s|<meta name=\"factory-api-url\" content=\"\">|<meta name=\"factory-api-url\" content=\"$API_URL\">|" \
  "$TEMP_DIR/index.html"
rm -f "$TEMP_DIR/index.html.bak"

# 3. Upload with SSE-S3 (required for CloudFront OAC — KMS blocks OAC reads)
echo "  → Syncing dashboard to s3://$BUCKET/dashboard/ (SSE-S3)..."
aws s3 sync "$TEMP_DIR/" "s3://$BUCKET/dashboard/" \
  --sse AES256 \
  --delete \
  --region "$REGION" >/dev/null

rm -rf "$TEMP_DIR"

# 4. Invalidate CloudFront cache
if [[ -n "$DASHBOARD_URL" ]]; then
  CF_DIST_ID=$(terraform -chdir="$TF_DIR" state show aws_cloudfront_distribution.dashboard 2>/dev/null \
    | grep "^    id " | awk '{print $3}' | tr -d '"')

  if [[ -n "$CF_DIST_ID" ]]; then
    echo "  → Invalidating CloudFront cache ($CF_DIST_ID)..."
    aws cloudfront create-invalidation \
      --distribution-id "$CF_DIST_ID" \
      --paths "/*" \
      --region "$REGION" >/dev/null 2>&1
    echo "  ✅ Cache invalidation in progress"
  fi
fi

# 5. Done
echo ""
echo "═══════════════════════════════════════════════════════════"
if [[ -n "$DASHBOARD_URL" ]]; then
  echo "  🟢 Dashboard deployed: $DASHBOARD_URL"
else
  echo "  🟢 Dashboard uploaded to s3://$BUCKET/dashboard/"
fi
echo "  📊 Status API: $API_URL/status/tasks"
echo "═══════════════════════════════════════════════════════════"
