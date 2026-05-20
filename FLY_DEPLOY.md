# Deploy Basebase to Fly.io

Emergency / production deploy using Docker on [Fly.io](https://fly.io). Supabase stays external.

## Prerequisites

1. **Billing**: Fly trial accounts must add a card at [fly.io/dashboard](https://fly.io/dashboard) → Billing (deploy fails with 422 otherwise).
2. **CLI**: `brew install flyctl && fly auth login`
3. **Env**: Production values in repo root [`.env`](.env)

## CI/CD (GitHub Actions)

On every **push to `main`**, after [Conformance Tests](.github/workflows/conformance-tests.yml) pass, [.github/workflows/fly-deploy.yml](.github/workflows/fly-deploy.yml) deploys:

| Change in | Deploys |
|-----------|---------|
| `backend/**` | API, Celery worker, Celery beat |
| `frontend/**` | Frontend |

**One-time setup** (repo admin):

1. Create a Fly deploy token (deploys all apps in your org):

   ```bash
   fly auth token
   ```

   Copy the full token (starts with `FlyV1 `).

2. GitHub → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:
   - `FLY_API_TOKEN` = token from step 1
   - Optional: `VITE_NANGO_PUBLIC_KEY` if you use Nango OAuth in the UI

3. Merge the workflow to `main`. The next green conformance run on `main` triggers deploy.

**Manual deploy from GitHub**: Actions → **Deploy to Fly.io** → **Run workflow**.

`basebase-redis` is not in CI (image-only, rarely changes). Redeploy with `./scripts/fly-deploy.sh` or `fly deploy -c fly.redis.toml --app basebase-redis` if needed.

## One-command deploy

```bash
./scripts/fly-deploy.sh
```

This creates/updates:

| Fly app | Config | Role |
|---------|--------|------|
| `basebase-redis` | [backend/fly.redis.toml](backend/fly.redis.toml) | Internal Redis (`redis://basebase-redis.internal:6379`) |
| `basebase-api` | [backend/fly.toml](backend/fly.toml) | FastAPI, health `GET /health` |
| `basebase-worker` | [backend/fly.worker.toml](backend/fly.worker.toml) | Celery worker |
| `basebase-beat` | [backend/fly.beat.toml](backend/fly.beat.toml) | Celery beat (`ENABLE_CELERY_BEAT=true`) |
| `basebase-frontend` | [frontend/fly.toml](frontend/fly.toml) | Vite build + nginx |

Production URLs:

- API: `https://api.basebase.com`
- App: `https://app.basebase.com`
- Fly defaults (fallback): `https://basebase-api.fly.dev`, `https://basebase-frontend.fly.dev`

## Manual steps (optional)

```bash
# Redis
cd backend && fly deploy -c fly.redis.toml --app basebase-redis

# API
fly secrets import --app basebase-api < <(./scripts/fly-secrets-export.sh)
cd backend && fly deploy --app basebase-api

# Worker / beat
cd backend && fly deploy -c fly.worker.toml --app basebase-worker
cd backend && fly deploy -c fly.beat.toml --app basebase-beat

# Frontend (build-time VITE_* args)
cd frontend && fly deploy --app basebase-frontend \
  --build-arg VITE_API_URL=https://basebase-api.fly.dev \
  --build-arg VITE_SUPABASE_URL=... \
  --build-arg VITE_SUPABASE_ANON_KEY=...
```

## Custom domains

```bash
fly certs create api.basebase.com --app basebase-api
fly certs create app.basebase.com --app basebase-frontend
```

Update DNS per `fly certs show`, then set secrets:

```bash
fly secrets set BACKEND_PUBLIC_URL=https://api.basebase.com FRONTEND_URL=https://app.basebase.com --app basebase-api
```

Redeploy frontend with `VITE_API_URL=https://api.basebase.com`.

## Upstash Redis (optional)

To use managed Redis instead of `basebase-redis`:

```bash
fly redis create --name basebase-redis --region sjc --enable-eviction --no-replicas
```

Set `REDIS_URL` from `fly redis status` and skip the `basebase-redis` app deploy in the script.

## Verify

```bash
curl -s https://basebase-api.fly.dev/health
fly status --app basebase-api
fly logs --app basebase-worker
```
