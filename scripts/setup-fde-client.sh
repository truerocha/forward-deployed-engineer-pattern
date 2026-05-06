#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Setup FDE Client — Complete one-command setup for any project
# ═══════════════════════════════════════════════════════════════════
#
# Single command that takes a project from zero to factory-ready:
#   1. Installs FDE hooks into the target workspace (.kiro/)
#   2. Configures ALM integration (token + webhook + label)
#   3. Prints next steps (trigger onboarding in Kiro)
#
# Usage (from the forward-deployed-ai-pattern repo):
#   bash scripts/setup-fde-client.sh \
#     --target /path/to/your-project \
#     --platform github \
#     --repo owner/repo-name \
#     [--profile AWS_PROFILE]
#
# After this script completes:
#   1. Open the target project in Kiro
#   2. Trigger 'fde-repo-onboard' hook (generates steering)
#   3. Review .kiro/steering/fde-draft.md → rename to fde.md
#   4. Label issues 'factory-ready' → pipeline runs automatically
# ═══════════════════════════════════════════════════════════════════

set -uo pipefail

REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
SECRETS_ID="fde-${ENVIRONMENT}/alm-tokens"
TF_DIR="infra/terraform"
TARGET=""
PLATFORM=""
REPO=""

while [[ $# -gt 0 ]]; do
  case $1 in
    --target) TARGET="$2"; shift 2 ;;
    --platform) PLATFORM="$2"; shift 2 ;;
    --repo) REPO="$2"; shift 2 ;;
    --project-id) REPO="$2"; shift 2 ;;
    --workspace-id) REPO="$2"; shift 2 ;;
    --profile) export AWS_PROFILE="$2"; shift 2 ;;
    --region) REGION="$2"; shift 2 ;;
    *)
      echo "Usage:"
      echo "  bash scripts/setup-fde-client.sh \\"
      echo "    --target /path/to/project \\"
      echo "    --platform github --repo owner/repo \\"
      echo "    [--profile AWS_PROFILE]"
      exit 1
      ;;
  esac
done

if [[ -z "$TARGET" ]]; then echo "❌ --target is required"; exit 1; fi
if [[ ! -d "$TARGET" ]]; then echo "❌ Directory not found: $TARGET"; exit 1; fi
if [[ -z "$PLATFORM" ]]; then echo "❌ --platform is required (github, gitlab, asana)"; exit 1; fi
if [[ -z "$REPO" ]]; then echo "❌ --repo is required"; exit 1; fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FDE Client Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Target:   $TARGET"
echo "  Platform: $PLATFORM"
echo "  Repo:     $REPO"
echo ""

# ═══ PART 1: Install hooks ═══
echo "┌─── Part 1: Install FDE Hooks ───┐"
mkdir -p "$TARGET/.kiro/hooks" "$TARGET/.kiro/steering" "$TARGET/.kiro/specs"

cat > "$TARGET/.kiro/hooks/fde-repo-onboard.kiro.hook" << 'HOOK'
{
  "name": "FDE Repo Onboard",
  "version": "1.0.0",
  "description": "Scans this workspace and generates a project-specific FDE steering file.",
  "when": { "type": "userTriggered" },
  "then": {
    "type": "askAgent",
    "prompt": "Run the Repo Onboarding Agent in local mode. Scan the codebase structure, detect conventions, and generate .kiro/steering/fde-draft.md with pipeline chain, module boundaries, tech stack, and level patterns."
  }
}
HOOK

cat > "$TARGET/.kiro/hooks/fde-work-intake.kiro.hook" << 'HOOK'
{
  "name": "FDE Work Intake",
  "version": "1.0.0",
  "description": "Pulls 'factory-ready' issues from ALM and creates spec files.",
  "when": { "type": "userTriggered" },
  "then": {
    "type": "askAgent",
    "prompt": "Scan GitHub issues with the 'factory-ready' label. For each, create a spec in .kiro/specs/ with title, body, labels, and acceptance criteria. Set status to 'ready'."
  }
}
HOOK

cat > "$TARGET/.kiro/README.md" << 'README'
# FDE Integration

## Hooks
| Hook | What It Does |
|------|-------------|
| `fde-repo-onboard` | Scans codebase, generates steering |
| `fde-work-intake` | Reads 'factory-ready' issues, creates specs |

## Quick Start
1. Trigger `fde-repo-onboard` in Kiro
2. Review `.kiro/steering/fde-draft.md` → rename to `fde.md`
3. Label issues `factory-ready` → pipeline runs
README

echo "  ✅ Hooks installed"

# ═══ PART 2: ALM Integration ═══
echo ""
echo "┌─── Part 2: ALM Integration ($PLATFORM) ───┐"

case "$PLATFORM" in
  gitlab)
    echo "  ⚠️  GitLab: hooks installed. Manual token setup: docs/guides/auth-setup.md"
    ;;
  asana)
    echo "  ⚠️  Asana: hooks installed. Manual token setup: docs/guides/auth-setup.md"
    ;;
  github)
    ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text --region "$REGION" 2>/dev/null)
    if [[ -z "$ACCOUNT_ID" ]]; then
      echo "  ❌ AWS credentials not valid. Run: aws sso login"
      echo "  Hooks installed but ALM skipped. Re-run after auth."
      exit 1
    fi

    SECRET_JSON=$(aws secretsmanager get-secret-value \
      --secret-id "$SECRETS_ID" --region "$REGION" \
      --query 'SecretString' --output text 2>/dev/null) || SECRET_JSON=""

    TOKEN=""
    if [[ -n "$SECRET_JSON" ]]; then
      TOKEN=$(echo "$SECRET_JSON" | python3 -c "
import sys,json
try:
  s=json.load(sys.stdin); t=s.get('github_pat','')
  print(t if t and not t.startswith('placeholder') else '')
except: print('')
" 2>/dev/null)
    fi

    if [[ -n "$TOKEN" ]]; then
      echo "  ✅ Token found"
    else
      echo "  Creating GitHub token..."
      open "https://github.com/settings/tokens/new?scopes=repo,project&description=fde-code-factory" 2>/dev/null || \
        echo "  Open: https://github.com/settings/tokens/new?scopes=repo,project&description=fde-code-factory"
      echo ""; read -rp "  Paste token (ghp_...): " TOKEN
      if [[ -z "$TOKEN" || ! "$TOKEN" == ghp_* ]]; then echo "  ❌ Invalid"; exit 1; fi
      NEW_SECRET=$(echo "$SECRET_JSON" | python3 -c "
import sys,json
try: s=json.load(sys.stdin)
except: s={}
s['github_pat']='$TOKEN'; print(json.dumps(s))
" 2>/dev/null)
      [[ -z "$NEW_SECRET" ]] && NEW_SECRET="{\"github_pat\":\"$TOKEN\",\"gitlab_pat\":\"\",\"bitbucket_pat\":\"\"}"
      aws secretsmanager put-secret-value --secret-id "$SECRETS_ID" \
        --secret-string "$NEW_SECRET" --region "$REGION" >/dev/null 2>&1
      echo "  ✅ Token stored"
    fi

    GITHUB_USER=$(curl -s -H "Authorization: Bearer $TOKEN" \
      -H "Accept: application/vnd.github.v3+json" \
      https://api.github.com/user 2>/dev/null | python3 -c "
import sys,json
try: print(json.load(sys.stdin).get('login',''))
except: print('')
")
    [[ -z "$GITHUB_USER" ]] && { echo "  ❌ Token invalid"; exit 1; }
    echo "  ✅ Authenticated: $GITHUB_USER"

    WEBHOOK_URL=$(terraform -chdir="$TF_DIR" output -raw webhook_github_url 2>/dev/null)
    if [[ -n "$WEBHOOK_URL" ]]; then
      HOOK_EXISTS=$(curl -s -H "Authorization: Bearer $TOKEN" \
        -H "Accept: application/vnd.github.v3+json" \
        "https://api.github.com/repos/$REPO/hooks" 2>/dev/null | python3 -c "
import sys,json
try:
  hooks=json.load(sys.stdin)
  print('yes' if any('$WEBHOOK_URL' in h.get('config',{}).get('url','') for h in hooks) else 'no')
except: print('no')
")
      if [[ "$HOOK_EXISTS" == "yes" ]]; then
        echo "  ✅ Webhook exists"
      else
        curl -s -o /dev/null -H "Authorization: Bearer $TOKEN" \
          -H "Accept: application/vnd.github.v3+json" \
          -X POST "https://api.github.com/repos/$REPO/hooks" \
          -d "{\"name\":\"web\",\"active\":true,\"events\":[\"issues\",\"label\"],\"config\":{\"url\":\"$WEBHOOK_URL\",\"content_type\":\"json\",\"insecure_ssl\":\"0\"}}"
        echo "  ✅ Webhook created"
      fi
    fi

    LABEL_CHECK=$(curl -s -o /dev/null -w "%{http_code}" \
      -H "Authorization: Bearer $TOKEN" -H "Accept: application/vnd.github.v3+json" \
      "https://api.github.com/repos/$REPO/labels/factory-ready")
    if [[ "$LABEL_CHECK" != "200" ]]; then
      curl -s -o /dev/null -H "Authorization: Bearer $TOKEN" \
        -H "Accept: application/vnd.github.v3+json" \
        -X POST "https://api.github.com/repos/$REPO/labels" \
        -d '{"name":"factory-ready","color":"7C3AED","description":"Triggers Code Factory"}'
    fi
    echo "  ✅ Label 'factory-ready' ready"
    ;;
  *) echo "  ❌ Unknown platform"; exit 1 ;;
esac

# ═══ SUMMARY ═══
DASHBOARD_URL=$(terraform -chdir="$TF_DIR" output -raw dashboard_url 2>/dev/null || echo "")
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🟢 FDE Client Ready"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  Next:"
echo "    1. Open $(basename "$TARGET") in Kiro"
echo "    2. Trigger 'FDE Repo Onboard' (Agent Hooks → ▶️)"
echo "    3. Review fde-draft.md → rename to fde.md"
echo "    4. Label issues 'factory-ready'"
echo ""
[[ -n "$DASHBOARD_URL" ]] && echo "  Dashboard: $DASHBOARD_URL"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
