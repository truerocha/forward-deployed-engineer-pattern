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
PORTAL_SRC="infra/portal-src"
DASHBOARD_DIR="infra/dashboard"
DASHBOARD_SRC="$DASHBOARD_DIR/index.html"
BUILD_FIRST=false

# Default AWS profile for SSO authentication
export AWS_PROFILE="${AWS_PROFILE:-profile-rocand}"

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --profile) export AWS_PROFILE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    --build) BUILD_FIRST=true; shift ;;
    *) echo "Usage: bash scripts/deploy-dashboard.sh [--profile PROFILE] [--build]"; exit 1 ;;
  esac
done

echo "━━━ Deploy Dashboard ━━━"

# 0. Optionally rebuild portal from source
if [[ "$BUILD_FIRST" == "true" ]]; then
  echo "  → Building portal from source ($PORTAL_SRC)..."
  if ! (cd "$PORTAL_SRC" && npm run build); then
    echo "  ❌ Portal build failed"
    exit 1
  fi
  # Sync build output to dashboard directory
  rm -rf "$DASHBOARD_DIR/assets"
  cp -r "$PORTAL_SRC/dist/assets" "$DASHBOARD_DIR/assets"
  cp "$PORTAL_SRC/dist/index.html" "$DASHBOARD_DIR/index.html"
  echo "  ✅ Portal built and synced to $DASHBOARD_DIR"
fi

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
cp -r "$DASHBOARD_DIR/"* "$TEMP_DIR/"
sed -i.bak "s|<meta name=\"factory-api-url\" content=\"\">|<meta name=\"factory-api-url\" content=\"$API_URL\">|" \
  "$TEMP_DIR/index.html"
rm -f "$TEMP_DIR/index.html.bak"

# 3. Upload with SSE-S3 (required for CloudFront OAC — KMS blocks OAC reads)
echo "  → Syncing dashboard to s3://$BUCKET/dashboard/ (SSE-S3)..."

# Sync HTML files with text/html content type
aws s3 cp "$TEMP_DIR/index.html" "s3://$BUCKET/dashboard/index.html" \
  --sse AES256 \
  --content-type "text/html; charset=utf-8" \
  --cache-control "no-cache, no-store, must-revalidate" \
  --region "$REGION" >/dev/null

# Sync JS assets with immutable cache (content-hashed filenames)
if [[ -d "$TEMP_DIR/assets" ]]; then
  aws s3 sync "$TEMP_DIR/assets/" "s3://$BUCKET/dashboard/assets/" \
    --sse AES256 \
    --cache-control "public, max-age=31536000, immutable" \
    --delete \
    --region "$REGION" >/dev/null
fi

# Sync images if present
if [[ -d "$TEMP_DIR/img" ]]; then
  aws s3 sync "$TEMP_DIR/img/" "s3://$BUCKET/dashboard/img/" \
    --sse AES256 \
    --cache-control "public, max-age=86400" \
    --delete \
    --region "$REGION" >/dev/null
fi

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
