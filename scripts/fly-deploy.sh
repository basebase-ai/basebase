#!/usr/bin/env bash
# Deploy Basebase to Fly.io (API, worker, beat, frontend + Upstash Redis).
# Prerequisites: flyctl installed, `fly auth login`, project root `.env` with production values.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

if ! command -v fly >/dev/null 2>&1; then
  echo "Install flyctl: brew install flyctl"
  exit 1
fi

if ! fly auth whoami >/dev/null 2>&1; then
  echo "Run: fly auth login"
  exit 1
fi

if ! fly deploy --help >/dev/null 2>&1; then
  echo "flyctl is required"
  exit 1
fi

echo "Note: Fly trial accounts need a card on file before deploy."
echo "      https://fly.io/dashboard/teg-grenager/billing"
echo ""

if [[ ! -f .env ]]; then
  echo "Missing .env at repo root"
  exit 1
fi

# Load .env safely (handles values with spaces/special chars)
load_env() {
  "$ROOT/venv/bin/python" - <<'PY'
import shlex
from pathlib import Path
from dotenv import dotenv_values

for key, value in dotenv_values(Path(".env")).items():
    if value is None or value == "":
        continue
    print(f"export {key}={shlex.quote(str(value))}")
PY
}
# shellcheck disable=SC1090
eval "$(load_env)"

REGION="${FLY_REGION:-sjc}"

fly_apps_ensure() {
  local app="$1"
  if ! fly apps list 2>/dev/null | awk '{print $1}' | grep -qx "$app"; then
    fly apps create "$app" --org personal 2>/dev/null || fly apps create "$app"
  fi
}

# Internal Redis on Fly private network (avoids interactive Upstash CLI prompts)
FLY_REDIS_URL="redis://basebase-redis.internal:6379"
echo "==> Redis app (basebase-redis)"
fly_apps_ensure basebase-redis
(cd backend && fly deploy -c fly.redis.toml --app basebase-redis --ha=false)

if [[ "${REDIS_URL:-}" == *localhost* ]] || [[ -z "${REDIS_URL:-}" ]]; then
  export REDIS_URL="$FLY_REDIS_URL"
  echo "Using REDIS_URL=$REDIS_URL"
fi

# Production URLs on Fly (*.fly.dev until custom certs are added)
export ENVIRONMENT=production
export BACKEND_PUBLIC_URL="https://basebase-api.fly.dev"
export FRONTEND_URL="https://basebase-frontend.fly.dev"
export VITE_API_URL="https://basebase-api.fly.dev"

if [[ -z "${NANGO_PUBLIC_KEY:-}" ]] && [[ -n "${VITE_NANGO_PUBLIC_KEY:-}" ]]; then
  export NANGO_PUBLIC_KEY="$VITE_NANGO_PUBLIC_KEY"
fi

fly_apps_ensure basebase-api
fly_apps_ensure basebase-worker
fly_apps_ensure basebase-beat
fly_apps_ensure basebase-frontend

# Backend secrets (API + worker need full bundle; beat needs Redis + shared flags)
backend_secret_keys=(
  DATABASE_URL MIGRATION_DATABASE_URL REDIS_URL
  ANTHROPIC_API_KEY OPENAI_API_KEY GEMINI_API_KEY MINIMAX_API_KEY DEEPSEEK_API_KEY
  DEFAULT_PRIMARY_MODEL DEFAULT_CHEAP_MODEL ALL_MODEL_STRINGS
  NANGO_SECRET_KEY NANGO_PUBLIC_KEY
  SECRET_KEY ENVIRONMENT FRONTEND_URL BACKEND_PUBLIC_URL
  SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_JWT_SECRET
  SLACK_CLIENT_ID SLACK_CLIENT_SECRET SLACK_BOT_TOKEN SLACK_SIGNING_SECRET SUPPORT_SLACK_WEBHOOK_URL
  MICROSOFT_APP_ID MICROSOFT_APP_PASSWORD MICROSOFT_TENANT_ID
  TWILIO_ACCOUNT_SID TWILIO_AUTH_TOKEN TWILIO_PHONE_NUMBER TWILIO_VERIFY_SERVICE_SID
  TWILIO_WEBHOOK_URL WHATSAPP_WEBHOOK_URL
  GMAIL_CLIENT_ID GMAIL_CLIENT_SECRET SCRAPINGBEE_API_KEY
  PERPLEXITY_API_KEY EXA_API_KEY AIRTOP_API_KEY AIRTOP_KEY
  GOOGLE_ADS_DEVELOPER_TOKEN HUBSPOT_API_KEY HUBSPOT_PERSONAL_ACCESS_KEY
  GOOGLE_SHEETS_DOCS_SLIDES_API_KEY AIRTABLE_API_KEY TRELLO_API_KEY
  E2B_API_KEY PINECONE_API_KEY RESEND_API_KEY EMAIL_FROM
  STRIPE_SECRET_KEY STRIPE_WEBHOOK_SECRET STRIPE_PUBLISHABLE_KEY
)

set_backend_secrets() {
  local app="$1"
  local args=()
  for key in "${backend_secret_keys[@]}"; do
  local val="${!key:-}"
    if [[ -n "$val" ]]; then
      args+=("$key=$val")
    fi
  done
  if [[ ${#args[@]} -gt 0 ]]; then
    echo "==> fly secrets set (${#args[@]} vars) on $app"
    fly secrets set "${args[@]}" --app "$app"
  fi
}

set_backend_secrets basebase-api
set_backend_secrets basebase-worker
fly secrets set REDIS_URL="$REDIS_URL" ENABLE_CELERY_BEAT=true ENVIRONMENT=production --app basebase-beat

echo "==> Deploy API"
(cd backend && fly deploy --app basebase-api --ha=false)

echo "==> Deploy worker"
(cd backend && fly deploy -c fly.worker.toml --app basebase-worker --ha=false)

echo "==> Deploy beat"
(cd backend && fly deploy -c fly.beat.toml --app basebase-beat --ha=false)

echo "==> Deploy frontend"
FRONTEND_BUILD_ARGS=(
  --build-arg "VITE_API_URL=$VITE_API_URL"
  --build-arg "VITE_SUPABASE_URL=${VITE_SUPABASE_URL}"
  --build-arg "VITE_SUPABASE_ANON_KEY=${VITE_SUPABASE_ANON_KEY}"
  --build-arg "VITE_STRIPE_PUBLISHABLE_KEY=${VITE_STRIPE_PUBLISHABLE_KEY:-}"
)
if [[ -n "${VITE_NANGO_PUBLIC_KEY:-${NANGO_PUBLIC_KEY:-}}" ]]; then
  FRONTEND_BUILD_ARGS+=(--build-arg "VITE_NANGO_PUBLIC_KEY=${VITE_NANGO_PUBLIC_KEY:-$NANGO_PUBLIC_KEY}")
fi
(cd frontend && fly deploy --app basebase-frontend --ha=false "${FRONTEND_BUILD_ARGS[@]}")

echo ""
echo "Done. Smoke test:"
echo "  curl -s https://basebase-api.fly.dev/health"
echo "  open https://basebase-frontend.fly.dev"
echo ""
echo "After DNS: fly certs create api.basebase.com --app basebase-api"
echo "           fly certs create app.basebase.com --app basebase-frontend"
