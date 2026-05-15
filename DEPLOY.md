# Deploying Basebase to Railway

This guide matches the **five-service** layout described in [README.md](README.md): **Frontend**, **Backend (API)**, **Celery Worker**, **Celery Beat**, and **Redis**. **PostgreSQL** is expected to live elsewhere (typically **Supabase** with `pgvector`), not as a sixth Railway container.

## Prerequisites

- [Railway](https://railway.app) account and GitHub repo access
- **Supabase** project: Postgres + Auth (`SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `SUPABASE_ANON_KEY` — see root [`env.example`](env.example))
- **Nango** account for OAuth-backed connectors (`NANGO_SECRET_KEY`, `NANGO_PUBLIC_KEY`)
- LLM keys (at minimum `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` for embeddings/research, unless you standardize on another provider)

## Architecture

| Service        | Root directory | Role |
| -------------- | -------------- | ---- |
| Frontend       | `frontend`     | Vite build → static hosting; needs `VITE_*` at **build** time |
| Backend (API)  | `backend`      | FastAPI (`api.main:app`); healthcheck `GET /health` |
| Worker         | `backend`      | `python -m celery -A workers.celery_app worker --loglevel=info` (consumes the `default` queue) |
| Beat           | `backend`      | `python -m celery -A workers.celery_app beat --loglevel=info` + `ENABLE_CELERY_BEAT=true` |
| Redis          | Railway Redis  | Broker + result backend for Celery |

Set `DATABASE_URL` on **API** and **Worker** to your Supabase pooler or direct Postgres URI (with `+asyncpg` as in `env.example`). Run migrations from CI or a one-off shell:

```bash
cd backend && alembic upgrade head
```

## Step 1 — Redis

1. Railway project → **New** → **Database** → **Redis**
2. Note `REDIS_URL` for all Python services

## Step 2 — Backend (API)

1. **New** → **GitHub Repo** → select this repo  
2. **Settings → Source → Root Directory**: `backend`  
3. **Variables** (mirror production values from [`env.example`](env.example)), including at minimum:
   - `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `ENVIRONMENT`, `FRONTEND_URL`, `BACKEND_PUBLIC_URL`
   - `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `SUPABASE_ANON_KEY`
   - `NANGO_SECRET_KEY`, `NANGO_PUBLIC_KEY`
   - `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`
   - Optional per feature: `EXA_API_KEY`, `PERPLEXITY_API_KEY`, `SCRAPINGBEE_API_KEY`, `E2B_API_KEY`, `RESEND_API_KEY`, Slack/Twilio/Teams/Stripe keys
4. **Deploy → Healthcheck Path**: `/health`

## Step 3 — Celery worker

Duplicate the backend service (or create another service from the same repo, root `backend`) with **Start Command**:

```bash
python -m celery -A workers.celery_app worker --loglevel=info
```

Use the **same** `DATABASE_URL` and integration secrets as the API so sync and tool tasks can reach the DB and external systems. **Do not** pass legacy `-Q default,sync,workflows` — the app uses a single `default` queue ([`workers/celery_app.py`](backend/workers/celery_app.py)).

## Step 4 — Celery beat

Another `backend` service with:

```bash
python -m celery -A workers.celery_app beat --loglevel=info
```

**Required:** `ENABLE_CELERY_BEAT=true` and `REDIS_URL`. Optionally copy the worker env bundle so feature flags like `ENABLE_NIGHTLY_TOPIC_GRAPH` match production.

When enabled, Beat schedules hourly org sync, workflow timers, monitoring tasks, daily digests, and optional nightly topic graph jobs — see [`celery_app.py`](backend/workers/celery_app.py).

**Run only one Beat instance** to avoid duplicate schedules.

## Step 5 — Frontend

1. **New** → **GitHub Repo** → root directory `frontend`  
2. Set build-time variables (Railway “Variables” / build args):

| Variable | Example |
| -------- | ------- |
| `VITE_API_URL` | `https://<your-api>.railway.app` (no `/api` suffix) |
| `VITE_SUPABASE_URL` | `https://<project>.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon key |
| `VITE_NANGO_PUBLIC_KEY` | Same as `NANGO_PUBLIC_KEY` |
| `VITE_WWW_URL` (optional) | Marketing site origin |

3. After deploy, set backend `FRONTEND_URL` to the frontend origin (no trailing slash) and redeploy the API for CORS.

## Slack: Nango + Add-to-Slack

Use **one** Slack app for both Nango “Connect” and Basebase’s Add-to-Slack OAuth callback on the backend:

1. Slack app → **OAuth & Permissions** → Redirect URL: `https://<api-host>/api/auth/slack/oauth-callback`
2. Nango Slack integration → same redirect URL
3. Backend env: `BACKEND_PUBLIC_URL`, `SLACK_SIGNING_SECRET`, `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`

See README **Railway** section and [`backend/api/routes/auth.py`](backend/api/routes/auth.py) for details.

## Supabase Auth URLs

After changing app domain (e.g. to `app.basebase.com`):

1. Supabase → **Authentication** → **URL Configuration**
2. Set **Site URL** and **Redirect URLs** to your app origin (e.g. `https://app.basebase.com/**`)

## WebSockets

Ensure `VITE_API_URL` points at the **API** host. Railway supports WebSockets; the app uses `GET /ws/chat?token=<jwt>` ([`frontend/src/lib/api.ts`](frontend/src/lib/api.ts)).

## Troubleshooting

- **CORS** — `FRONTEND_URL` on the API must match the browser origin exactly (no trailing slash).
- **Nango / GitHub connect fails** — confirm `VITE_NANGO_PUBLIC_KEY` is present at **frontend build** time.
- **No scheduled jobs** — verify `ENABLE_CELERY_BEAT=true` on the Beat service and that a Worker is running.
- **Migrations** — use `MIGRATION_DATABASE_URL` with a direct (non-pooler) role if Supabase pooler blocks `alembic upgrade` (see comments in [`env.example`](env.example)).

## Local vs production

| Concern | Local | Production |
| ------- | ----- | ------------ |
| API | `http://localhost:8000` | Railway API URL |
| DB | Docker Postgres or Supabase | Supabase (recommended) |
| Redis | Docker / localhost | Railway Redis |
| Celery Beat | Off unless `ENABLE_CELERY_BEAT=true` | `true` on Beat only |
