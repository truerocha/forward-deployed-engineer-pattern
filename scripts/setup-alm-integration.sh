#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Setup ALM Integration — Token + Webhook + Label configuration
# ═══════════════════════════════════════════════════════════════════
#
# Single command to configure ALM platform integration with the Code Factory.
# Supports: GitHub, GitLab, Asana (per ADR-006, ADR-008)
#
# Usage:
#   bash scripts/setup-alm-integration.sh --platform github --repo owner/repo [--profile PROFILE]
#   bash scripts/setup-alm-integration.sh --platform gitlab --project-id 12345 [--profile PROFILE]
#   bash scripts/setup-alm-integration.sh --platform asana --workspace-id xyz [--profile PROFILE]
#
# Prerequisites:
#   - AWS credentials authenticated (aws sso login)
#   - Terraform applied (infra/terraform)
#   - Admin access to the target repo/project/workspace
# ═══════════════════════════════════════════════════════════════════

set -uo pipefail

REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
SECRETS_ID="fde-${ENVIRONMENT}/alm-tokens"
TF_DIR="infra/terraform"
PLATFORM=""
REPO=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --platform) PLATFORM="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --project-id) REPO="$2"; shift 2 ;;
    --workspace-id) REPO="$2"; shift 2 ;;
    --profile) export AWS_PROFILE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    *)
      echo "Usage:"
      echo "  bash scripts/setup-alm-integration.sh --platform github --repo owner/repo"
      echo "  bash scripts/setup-alm-integration.sh --platform gitlab --project-id 12345"
      echo "  bash scripts/setup-alm-integration.sh --platform asana --workspace-id xyz"
      exit 1
      ;;
  esac
done

if [[ -z "$PLATFORM" ]]; then
  echo "❌ --platform is required. Options: github, gitlab, asana"
  exit 1
fi

case "$PLATFORM" in
  github)
    if [[ -z "$REPO" ]]; then echo "❌ --repo is required for GitHub."; exit 1; fi
    ;;
  gitlab)
    if [[ -z "$REPO" ]]; then echo "❌ --project-id is required for GitLab."; exit 1; fi
    echo "⚠️  GitLab integration: use docs/guides/auth-setup.md for manual setup."
    exit 0
    ;;
  asana)
    if [[ -z "$REPO" ]]; then echo "❌ --workspace-id is required for Asana."; exit 1; fi
    echo "⚠️  Asana integration: use docs/guides/auth-setup.md for manual setup."
    exit 0
    ;;
  *) echo "❌ Unknown platform: $PLATFORM"; exit 1 ;;
esac

# GitHub flow continues below
OWNER="${REPO%%/*}"
REPO_NAME="${REPO##*/}"

echo ""
echo "━━━ GitHub Integration Setup ━━━"
echo "  Repository: $REPO"
echo "  Environment: $ENVIRONMENT"
echo ""

# ① Check existing token
echo "① Checking Secrets Manager for existing token..."

EXISTING_TOKEN=""
SECRET_JSON=$(aws secretsmanager get-secret-value \
  --secret-id "$SECRETS_ID" --region "$REGION" \
  --query 'SecretString' --output text 2>/dev/null) || SECRET_JSON=""

if [[ -n "$SECRET_JSON" ]]; then
  EXISTING_TOKEN=$(echo "$SECRET_JSON" | python3 -c "
import sys,json
try:
  s=json.load(sys.stdin)
  t=s.get('github_pat','')
  print(t if t and not t.startswith('placeholder') else '')
except: print('')
" 2>/dev/null)
fi

if [[ -n "$EXISTING_TOKEN" ]]; then
  echo "  ✅ Token found (${EXISTING_TOKEN:0:8}...)"
  TOKEN="$EXISTING_TOKEN"
else
  echo "  ⚠️  No valid token found."
  echo ""
  echo "② Create a GitHub Personal Access Token:"
  echo "   → Name: fde-code-factory"
  echo "   → Expiration: 90 days"
  echo "   → Scopes: ✅ repo, ✅ project"
  echo ""
  open "https://github.com/settings/tokens/new?scopes=repo,project&description=fde-code-factory" 2>/dev/null || \
    echo "   Open: https://github.com/settings/tokens/new?scopes=repo,project&description=fde-code-factory"
  echo ""
  read -rp "   Paste your token (ghp_...): " TOKEN
  if [[ -z "$TOKEN" || ! "$TOKEN" == ghp_* ]]; then
    echo "  ❌ Invalid token. Must start with 'ghp_'"; exit 1
  fi

  echo ""
  echo "③ Storing token in Secrets Manager..."
  NEW_SECRET=$(echo "$SECRET_JSON" | python3 -c "
import sys,json
try: s=json.load(sys.stdin)
except: s={}
s['github_pat']='$TOKEN'
print(json.dumps(s))
" 2>/dev/null)
  [[ -z "$NEW_SECRET" ]] && NEW_SECRET="{\"github_pat\":\"$TOKEN\",\"gitlab_pat\":\"\",\"bitbucket_pat\":\"\"}"
  aws secretsmanager put-secret-value --secret-id "$SECRETS_ID" \
    --secret-string "$NEW_SECRET" --region "$REGION" >/dev/null 2>&1
  echo "  ✅ Token stored"
fi

# ④ Validate
echo ""
echo "④ Validating token..."
GITHUB_USER=$(curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  https://api.github.com/user 2>/dev/null | python3 -c "
import sys,json
try: print(json.load(sys.stdin).get('login',''))
except: print('')
")
if [[ -z "$GITHUB_USER" ]]; then
  echo "  ❌ Token validation failed."; exit 1
fi
echo "  ✅ Authenticated as: $GITHUB_USER"

REPO_CHECK=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/$REPO")
if [[ "$REPO_CHECK" != "200" ]]; then
  echo "  ❌ Cannot access $REPO (HTTP $REPO_CHECK)"; exit 1
fi
echo "  ✅ Repo access confirmed"

# ⑤ Webhook
echo ""
echo "⑤ Configuring webhook..."
WEBHOOK_URL=$(terraform -chdir="$TF_DIR" output -raw webhook_github_url 2>/dev/null)
if [[ -z "$WEBHOOK_URL" ]]; then
  echo "  ❌ Cannot read webhook URL. Run: terraform apply"; exit 1
fi

EXISTING_HOOKS=$(curl -s -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/$REPO/hooks" 2>/dev/null)
HOOK_EXISTS=$(echo "$EXISTING_HOOKS" | python3 -c "
import sys,json
try:
  hooks=json.load(sys.stdin)
  print('yes' if any('$WEBHOOK_URL' in h.get('config',{}).get('url','') for h in hooks) else 'no')
except: print('no')
")

if [[ "$HOOK_EXISTS" == "yes" ]]; then
  echo "  ✅ Webhook already configured"
else
  HOOK_RESULT=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    -X POST "https://api.github.com/repos/$REPO/hooks" \
    -d "{\"name\":\"web\",\"active\":true,\"events\":[\"issues\",\"label\"],\"config\":{\"url\":\"$WEBHOOK_URL\",\"content_type\":\"json\",\"insecure_ssl\":\"0\"}}")
  if [[ "$HOOK_RESULT" == "201" ]]; then
    echo "  ✅ Webhook created: $WEBHOOK_URL"
  else
    echo "  ⚠️  HTTP $HOOK_RESULT — may need admin access. Manual: Settings → Webhooks → $WEBHOOK_URL"
  fi
fi

# ⑥ Label
echo ""
echo "⑥ Ensuring 'factory-ready' label..."
LABEL_CHECK=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  "https://api.github.com/repos/$REPO/labels/factory-ready")
if [[ "$LABEL_CHECK" == "200" ]]; then
  echo "  ✅ Label exists"
else
  curl -s -o /dev/null \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/vnd.github.v3+json" \
    -X POST "https://api.github.com/repos/$REPO/labels" \
    -d '{"name":"factory-ready","color":"7C3AED","description":"Triggers the Code Factory pipeline"}'
  echo "  ✅ Label 'factory-ready' created"
fi

# Summary
echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  🟢 GitHub integration complete for $REPO"
echo ""
echo "  Next steps:"
echo "  1. Open $REPO_NAME workspace in Kiro"
echo "  2. Trigger 'fde-repo-onboard' hook → generates steering"
echo "  3. Review .kiro/steering/fde-draft.md → rename to fde.md"
echo "  4. Label any issue 'factory-ready' → pipeline starts"
echo ""
echo "  Dashboard: $(terraform -chdir="$TF_DIR" output -raw dashboard_url 2>/dev/null || echo 'N/A')"
echo "═══════════════════════════════════════════════════════════"
