# Basebase: Agentic Intelligence for Companies

Basebase is an **agentic intelligence framework** that connects to the siloed tools and data sources your business already uses — CRM, email, calendars, Slack, issue trackers, code repos, meeting transcripts, and more — and exposes a unified AI agent (called "**Basebase**") in the **web app**, **Slack**, **Microsoft Teams**, **SMS (Twilio)**, and **WhatsApp** so team members work faster, smarter, and with full context.

Instead of switching between a dozen tabs, employees ask **Basebase** questions in natural language — via the **web app** or any connected messenger — and get instant, data-backed answers, reports, and actions across every connected system.

## Architecture

![Basebase System Architecture](docs/architecture.png)

## Connector Documentation

### What Can Basebase Do?

- **Answer questions across all your data** — "What deals closed this quarter?", "Show me all emails with Acme Corp", "What's on my calendar tomorrow?"
- **Take action on your behalf** — Update CRM records, send emails, post to Slack channels, create issues in Linear — all with an approval workflow for safety
- **Automate recurring work** — Schedule daily deal summaries, stale-deal alerts, weekly pipeline reports, post-sync analysis — delivered to Slack or email on a cron
- **Generate reports and artifacts** — Interactive charts, PDF reports, dashboards — created on demand from live data
- **Enrich your data** — Pull in company and contact intelligence from Apollo.io automatically
- **Search semantically** — Full-text and vector search across emails, meetings, messages, and notes
- **Remember context** — Persistent memory across conversations so the agent learns your preferences over time

### Integrated Data Sources

| Category                | Sources                                                                 |
| ----------------------- | ----------------------------------------------------------------------- |
| **CRM**                 | HubSpot, Salesforce, Attio                                              |
| **Email**               | Gmail, Microsoft Outlook                                                |
| **Calendar**            | Google Calendar, Microsoft Calendar                                     |
| **Messaging**           | Slack (messages, DMs, channels)                                         |
| **Meeting Transcripts** | Fireflies, Zoom, Granola (meeting notes via MCP)                       |
| **Issue Tracking**      | Linear, Asana, Jira, Trello                                             |
| **Code & Repos**        | GitHub (repos, commits, PRs)                                            |
| **File Storage**        | Google Drive (Docs, Sheets, Slides)                                    |
| **Data Enrichment**     | Apollo.io (contacts & companies)                                        |
| **TV Analytics**        | iSpot.tv                                                                |
| **Extensibility**       | Generic [MCP](https://modelcontextprotocol.io) server connector (`mcp`) |
| **Built-in / custom**   | Web search (Exa / Perplexity), code sandbox (E2B), Twilio SMS, artifacts, interactive mini-apps (`apps`) — toggled or configured in-app; not Nango OAuth |

**OAuth-backed sources** use [Nango](https://nango.dev) — tokens are securely stored and auto-refreshed. Built-in connectors use API keys or server-side toggles (see [`env.example`](env.example) and [`backend/connectors/registry.py`](backend/connectors/registry.py)).

### How Users Interact

- **Web App** — Full-featured React interface with real-time chat (WebSocket-streamed), a data browser, semantic search, workflow manager, workstreams, daily digests, topic graph (“Graph Magic”), generated mini-apps (Sandpack), and a pending-changes approval panel for CRM writes.
- **Slack** — DM the bot or @mention it in any channel. Basebase reads the thread context and responds inline. Conversations sync between Slack and the web app where applicable.
- **Microsoft Teams** — Bot Framework integration for Teams chat surfaces ([`backend/messengers/teams.py`](backend/messengers/teams.py), [`/api/teams`](backend/api/routes/teams_events.py)).
- **SMS & WhatsApp** — Twilio-backed messengers for text conversations ([`backend/messengers/sms.py`](backend/messengers/sms.py), [`backend/messengers/whatsapp.py`](backend/messengers/whatsapp.py)).

### Synchronous and Asynchronous Agent Operation

Basebase supports multiple execution modes:

- **Synchronous (real-time)** — Users chat with Basebase via WebSocket. Tool calls execute inline and results stream back token-by-token.
- **Asynchronous (background)** — Workflows run on a Celery task queue. Scheduled (cron), event-driven (e.g. "after every data sync"), or manually triggered.
- **Agent Swarms** — Complex tasks can be decomposed into prompt-based workflows that spawn child agents, each tackling a sub-problem. `run_workflow` can wait for a child (`wait_for_completion=true`) or fire-and-forget. `foreach` batches work over an inline list or an `items_query` SQL result, calling another tool or a workflow per row.

## Tech Stack

- **Frontend**: React 18 + TypeScript + Tailwind CSS + Vite + Zustand (primary state) + TanStack React Query + Plotly.js (charts) + react-markdown; **Sandpack** (`@codesandbox/sandpack-react`) for generated mini-apps; **Cosmograph** (`@cosmograph/react`) for topic-graph visualization; **Stripe** Elements for billing
- **Backend**: Python 3.11 + FastAPI + SQLAlchemy (async)
- **Database**: PostgreSQL 15 with JSONB + pgvector (embeddings) — production typically uses [Supabase](https://supabase.com) Postgres
- **Task Queue**: Celery + Redis (async workflows, scheduled jobs, bulk `foreach`, digests, monitoring)
- **Cache**: Redis
- **Auth**: [Supabase](https://supabase.com) — Google OAuth, email/password, session management, and waitlist / invite gating
- **AI**: Provider-agnostic layer ([`services/llm_adapter.py`](backend/services/llm_adapter.py), [`services/llm_provider.py`](backend/services/llm_provider.py)) — defaults to **Anthropic Claude** (`claude-opus-4-6`, `claude-haiku-4-5-20251001` per [`config.py`](backend/config.py)); optional keys for OpenAI, MiniMax, Gemini, Qwen, DeepSeek. **OpenAI** for embeddings and research fallback (`OPENAI_RESEARCH_MODEL`, GPT‑5 family)
- **Web search**: Exa and/or Perplexity (`EXA_API_KEY`, `PERPLEXITY_API_KEY`); **ScrapingBee** for `fetch_url`; **E2B** for sandboxed code (`E2B_API_KEY`)
- **OAuth (Integrations)**: [Nango](https://nango.dev) — unified OAuth for external SaaS connectors
- **Billing**: Stripe ([`api/routes/billing.py`](backend/api/routes/billing.py))
- **ML (workstreams)**: hdbscan, UMAP, scikit-learn ([`requirements.txt`](backend/requirements.txt))
- **PDF Generation**: WeasyPrint (+ PyMuPDF / openpyxl for attachments and spreadsheets)
- **Deployment**: Docker + docker-compose (dev), Railway (production)

## Quick Start

### Prerequisites

**Runtime**

- Python 3.10+
- Node.js 18+
- PostgreSQL 15+ with the `pgvector` extension (local Docker or [Supabase](https://supabase.com))
- Redis (local or Docker)

**Required to run the core app** (see root [`env.example`](env.example) for names and comments)

- `DATABASE_URL`, `REDIS_URL`, `SECRET_KEY`, `ENVIRONMENT`, `FRONTEND_URL`
- `SUPABASE_URL`, `SUPABASE_JWT_SECRET`, `SUPABASE_ANON_KEY` (auth + JWT verification)
- `NANGO_SECRET_KEY`, `NANGO_PUBLIC_KEY`
- At least one LLM provider key — typically `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` (embeddings + research fallback)

**Per feature (enable as needed)**

- Web search: `EXA_API_KEY` and/or `PERPLEXITY_API_KEY`
- `fetch_url` scraping: `SCRAPINGBEE_API_KEY`
- Sandboxed code (`code_sandbox`): `E2B_API_KEY`
- Transactional email (invites, etc.): `RESEND_API_KEY`, `EMAIL_FROM`
- SMS / WhatsApp (Twilio messengers): `TWILIO_*` variables in `env.example`
- Slack bot + Events API: `SLACK_SIGNING_SECRET`, `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `BACKEND_PUBLIC_URL`
- Microsoft Teams bot: `MICROSOFT_APP_ID`, `MICROSOFT_APP_PASSWORD`, `MICROSOFT_TENANT_ID` (single-tenant)
- Subscriptions: `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY`
- Optional LLMs: `MINIMAX_API_KEY`, `GEMINI_API_KEY`, `QWEN_API_KEY`, `DEEPSEEK_API_KEY` (see `env.example`)

### 1. Clone and configure environment

```bash
git clone https://github.com/basebase-ai/basebase.git
cd basebase
cp env.example .env
```

Edit `.env` with your credentials — start from [`env.example`](env.example) and fill the **Required** block first, then optional keys for messengers, billing, and tools you use.

### 2. Install system dependencies

WeasyPrint (PDF generation) requires native libraries:

**macOS:**

```bash
brew install cairo pango gdk-pixbuf libffi redis
brew services start redis
```

**Ubuntu/Debian:**

```bash
sudo apt-get update
sudo apt-get install -y build-essential python3-dev libcairo2 libpango-1.0-0 \
  libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info redis-server
sudo systemctl start redis
```

### 3. Start the backend

```bash
cd backend
python3 -m venv venv
source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Run database migrations
alembic upgrade head

# Start the API server
uvicorn api.main:app --reload
```

The API will be available at http://localhost:8000 (docs at http://localhost:8000/docs).

### 4. Start the frontend

In a new terminal:

```bash
cd frontend
npm install
npm run dev
```

The app will be available at http://localhost:5173.

### 5. Configure integrations (optional)

In your [Nango dashboard](https://app.nango.dev), create integrations matching the IDs in [`backend/config.py`](backend/config.py) (`NANGO_*_INTEGRATION_ID`) for each OAuth provider you need, for example:

- **CRM**: `hubspot`, `salesforce`, `attio`
- **Email**: `google-mail` (Gmail)
- **Calendar**: `google-calendar`, `microsoft` (calendar + mail as configured in Nango)
- **Messaging**: `slack`
- **Meetings**: `fireflies`, `zoom`, `granola-mcp` (Granola)
- **Issue tracking**: `linear`, `asana`, plus Jira/Trello per your Nango app names
- **Code**: `github`
- **Files**: `google-drive`
- **Enrichment**: `apollo`

**Not configured in Nango** (built-in or API-key connectors): `web_search`, `code_sandbox`, `twilio`, `artifacts`, `apps`, `mcp`, `ispot_tv` — see `BUILTIN_CONNECTORS` in [`backend/config.py`](backend/config.py) and [`/api/connectors`](backend/api/routes/connectors.py).

### Alternative: Docker Compose

To run everything in containers:

```bash
docker-compose up -d
cd backend && alembic upgrade head
```

- Frontend: http://localhost:5173
- API: http://localhost:8000

## Railway Deployment

This monorepo deploys to Railway as **5 services** from a single GitHub repo. **PostgreSQL** is not a Railway service in this layout — use **Supabase** (or another Postgres host) with `pgvector` and set `DATABASE_URL` on the API and workers.

```
┌───────────────────────────────────────────────────────┐
│  Railway Project                                      │
│                                                       │
│  ┌──────────────┐  ┌──────────────┐                  │
│  │   Frontend   │  │   Backend    │                  │
│  │    (APP)     │  │    (API)     │                  │
│  └──────────────┘  └──────┬───────┘                  │
│                           │                          │
│  ┌──────────────┐  ┌──────┴───────┐                  │
│  │    Beat      │  │    Worker    │                  │
│  │ (scheduler)  │  │  (executor)  │                  │
│  └──────┬───────┘  └──────┬───────┘                  │
│         │                 │                          │
│         └────────┬────────┘                          │
│                  ▼                                   │
│           ┌─────────────┐                            │
│           │    Redis    │                            │
│           └─────────────┘                            │
└───────────────────────────────────────────────────────┘
```

### Service Configuration

| Service           | Root Directory | Start Command                                                                 | Healthcheck |
| ----------------- | -------------- | ----------------------------------------------------------------------------- | ----------- |
| **Frontend**      | `frontend`     | (default)                                                                     | None        |
| **Backend (API)** | `backend`      | (default — uses Dockerfile CMD)                                              | `/health`   |
| **Beat**          | `backend`      | `python -m celery -A workers.celery_app beat --loglevel=info`                 | None        |
| **Worker**        | `backend`      | `python -m celery -A workers.celery_app worker --loglevel=info`               | None        |
| **Redis**         | —              | Railway Redis template                                                        | —           |

Workers consume the **`default`** Celery queue only ([`workers/celery_app.py`](backend/workers/celery_app.py)); do not pass legacy `-Q default,sync,workflows`.

### Beat schedule (production)

Set **`ENABLE_CELERY_BEAT=true`** on the **Beat** service. Without it, the beat schedule is empty and periodic tasks do not run ([`celery_app.py`](backend/workers/celery_app.py)).

When enabled, Beat schedules include (among others): hourly sync for all orgs, scheduled-workflow checker (every minute), workflow event processor (every 10s), dependency monitoring, meeting sweeps, monitoring heartbeat watchdog, action-ledger retention (daily), daily digests (08:00 UTC), and optionally **nightly topic graph** when `ENABLE_NIGHTLY_TOPIC_GRAPH=true`.

### Setup Steps

1. **Create Redis service:**
   - New → Database → Redis
   - Railway auto-creates `REDIS_URL`

2. **Provision Postgres** (e.g. Supabase) with `pgvector` and set `DATABASE_URL` on API + Worker.

3. **Create each app service:**
   - New → GitHub Repo → select this repo
   - Set **Root Directory** in Settings → Source
   - Set **Custom Start Command** in Settings → Deploy (for beat/worker only)
   - Remove healthcheck for beat/worker (they don't serve HTTP)

4. **Share environment variables:**
   - Backend, Beat, Worker: at minimum `DATABASE_URL`, `REDIS_URL`, and the same app secrets as local `env.example` for features you use.
   - **Beat** also needs `ENABLE_CELERY_BEAT=true` and `REDIS_URL`. Optionally mirror the worker `.env` on Beat so future schedules can read the same flags without a separate env group.
   - Use Railway's variable references to share `REDIS_URL` from the Redis service

5. **Add healthcheck for API only:**
   - Backend (API) → Settings → Deploy → Healthcheck Path: `/health`

### Scaling Workers

Workers can be horizontally scaled - just duplicate the worker service. All workers pull from the same Redis queue, tasks are automatically distributed.

**Important:** Never run more than one Beat instance (causes duplicate scheduled tasks).

### Environment Variables by Service

| Variable | Frontend | Backend | Beat | Worker |
| -------- | -------- | ------- | ---- | ------ |
| `DATABASE_URL` | ❌ | ✅ | ❌ | ✅ |
| `REDIS_URL` | ❌ | ✅ | ✅ | ✅ |
| `ENABLE_CELERY_BEAT` | ❌ | ❌ | `true` | ❌ |
| `ENABLE_NIGHTLY_TOPIC_GRAPH` | ❌ | optional | optional | optional |
| `ANTHROPIC_API_KEY` (and/or other LLM keys) | ❌ | ✅ | ❌ | ✅ |
| `OPENAI_API_KEY` | ❌ | ✅ | ❌ | ✅ |
| `EXA_API_KEY` / `PERPLEXITY_API_KEY` | ❌ | ✅ | ❌ | ✅ |
| `SCRAPINGBEE_API_KEY`, `E2B_API_KEY` | ❌ | ✅ | ❌ | ✅ |
| `NANGO_SECRET_KEY` | ❌ | ✅ | ❌ | ✅ |
| `SUPABASE_*`, `SECRET_KEY`, `FRONTEND_URL`, `BACKEND_PUBLIC_URL` | ❌ | ✅ | ❌ | ✅ |
| `SLACK_*`, Twilio, Teams, Stripe, Resend, … | ❌ | as needed | ❌ | as needed |
| `VITE_*` vars | ✅ | ❌ | ❌ | ❌ |

Frontend only needs `VITE_*` environment variables at build time. Workers need the same provider and integration secrets as the API for tool execution and sync jobs.

## Project Structure

```
basebase/
├── backend/
│   ├── access_control/    # Permission checks and data protection
│   ├── agents/            # LLM orchestration, tool registry, tool execution
│   ├── api/
│   │   ├── auth_middleware.py  # JWT / auth context for routes
│   │   └── routes/        # FastAPI route modules (mounted in api/main.py)
│   ├── connectors/        # Integration connectors + registry discovery
│   ├── db/                # SQL helpers; Alembic migrations live in db/migrations/
│   ├── messengers/        # Slack, Teams, web, SMS, WhatsApp message pipelines
│   ├── models/            # SQLAlchemy models
│   ├── scripts/           # Utility scripts (e.g. dbq.py, seeding)
│   ├── services/          # LLM adapters, Nango, email, embeddings, billing, …
│   ├── tests/             # Test suite
│   ├── utils/             # Shared helpers (e.g. JSX transpilation for apps)
│   └── workers/
│       └── tasks/         # Celery tasks (sync, workflows, digests, topic graph, …)
├── frontend/
│   └── src/
│       ├── api/           # Typed API helpers (daily digests, workstreams, …)
│       ├── components/    # App shell, Chat, Data, Workflows, …
│       │   ├── apps/      # Sandpack mini-app viewer / gallery
│       │   ├── documents/ # Documents gallery
│       │   ├── public/    # Public artifact / app views
│       │   ├── shared/    # Shared UI pieces
│       │   └── widgets/   # Embeddable widgets / previews
│       ├── hooks/         # WebSocket, org, viewport, …
│       ├── lib/           # Supabase client, API base URL, branding
│       ├── store/         # Zustand stores
│       └── types/         # TypeScript definitions
├── docs/                  # Diagrams and extra docs
├── supabase/              # Supabase-related assets (if used)
└── docker-compose.yml
```

## State Management

The frontend uses **Zustand** (`frontend/src/store/index.ts`) as the primary state store. The app is WebSocket-first — most data updates come from real-time server events, which update the store directly.

**React Query** (TanStack) is used sparingly for isolated CRUD operations (e.g., workflows, team members).

## Nango Integration

We use [Nango](https://nango.dev) for **OAuth-backed** SaaS connectors:

- **Tokens in Nango** — OAuth tokens are stored and encrypted in Nango (not in app code paths that duplicate secrets)
- **Automatic refresh** — Tokens are refreshed automatically
- **Unified API** — Same pattern for all OAuth connectors
- **Pre-built integrations** — 150+ integrations available in Nango

### Connecting an Integration

1. Frontend calls `GET /api/auth/connect/{provider}?user_id={user_id}`
2. Backend returns Nango Connect URL
3. User is redirected to Nango's OAuth flow
4. After OAuth, Nango redirects back to frontend
5. Frontend calls `POST /api/auth/callback` to record the connection

## API Endpoints

Routers are mounted in [`backend/api/main.py`](backend/api/main.py). Use **OpenAPI** at `/docs` for the full path list. Summary by prefix:

| Prefix | Purpose |
| ------ | ------- |
| `/api/auth` | Sign-in sync, orgs, Nango connect/callback, integrations |
| `/api/connectors` | Connector registry metadata + inbound webhooks (`POST /webhook/{provider}/{organization_id}`) |
| `/api/sync` | Trigger and inspect data syncs |
| `/api/chat` | Conversations, messages, uploads, legacy `GET /api/chat/history` |
| `/api/apps`, `/api/artifacts`, `/api/drive`, `/api/data` | Mini-apps, artifacts, Drive helpers, tabular data APIs |
| `/api/workflows`, `/api/workstreams` | Workflows, semantic workstreams; daily digests via Home apps + `temp_data` |
| `/api/memories`, `/api/search` | User/org memories, search |
| `/api/billing`, `/api/notifications`, `/api/deals`, `/api/support` | Stripe billing, notifications, deals, support |
| `/api/waitlist` | Public waitlist + admin invite/list routes under `/api/waitlist/admin/...` |
| `/api/slack`, `/api/twilio`, `/api/whatsapp`, `/api/teams` | Messenger / bot webhooks and Slack utilities |
| `/api/public` | Authenticated public previews; **share routes** (org slug + artifact/app IDs) are mounted at the app root for public links |
| `/api/admin-dashboard`, `/api/admin-topic-graph` | Admin dashboards and topic-graph operations |
| `/api` (shared) | Tool settings, change sessions, action ledger (see `tool_settings`, `change_sessions`, `action_ledger` routers) |

### Real-time chat

| Path | Protocol | Notes |
| ---- | -------- | ----- |
| `/ws/chat` | WebSocket | JWT passed as a **query parameter** (e.g. `?token=...` — see [`frontend/src/hooks/useWebSocket.ts`](frontend/src/hooks/useWebSocket.ts)); subscribes to agent task streams managed by [`api/websockets.py`](backend/api/websockets.py) |

### Waitlist (public website)

| Path | Method | Description |
| ---- | ------ | ----------- |
| `/api/waitlist` | POST | Submit waitlist application |
| `/api/waitlist/admin` | GET | List waitlist entries (admin auth) |
| `/api/waitlist/admin/{user_id}/invite` | POST | Invite user from waitlist |

## Claude Tool Architecture

The chat pipeline uses the **LLM adapter** ([`services/llm_adapter.py`](backend/services/llm_adapter.py)) with tool calling against synced and live connector data. Here's how it works:

### Flow

```
User Message → WebSocket → Orchestrator → LLM API (Anthropic / OpenAI / …)
                                              ↓
                                        Model decides:
                                        - Text response → stream to user
                                        - Tool call → execute & continue
                                              ↓
                              Tool Result → LLM API → Final Response
```

### Backend Components

| File | Responsibility |
| ---- | ---------------- |
| [`agents/orchestrator.py`](backend/agents/orchestrator.py) | Conversation loop, streaming, tool execution across providers |
| [`agents/registry.py`](backend/agents/registry.py) | Tool metadata, categories, approval defaults, status strings |
| [`agents/tools.py`](backend/agents/tools.py) | Tool execution and connector dispatch |
| [`api/websockets.py`](backend/api/websockets.py) | WebSocket endpoint, task subscriptions, fan-out to clients |

### Available Tools

Tools are organized by category ([`agents/registry.py`](backend/agents/registry.py)):

**Local Read** (always safe, no approval):

| Tool | Description |
| ---- | ----------- |
| `run_sql_query` | Read-only `SELECT` with org scoping and `semantic_embed()` for vector search |
| `search_documents` | Search titles/descriptions of artifacts across conversations |
| `list_connected_connectors` | Refresh and return capabilities manifest for connected connectors |
| `get_connector_docs` | Fetch connector-specific usage docs before calling query/write/run |
| `think` | Optional planning step (hidden from status UI) |

**External Read** (live APIs; may incur cost):

| Tool | Description |
| ---- | ----------- |
| `query_on_connector` | On-demand reads — e.g. web search, Apollo, Google Drive, Granola — via connector-specific query strings |

**Local Write** (internal / tracked):

| Tool | Description |
| ---- | ----------- |
| `run_sql_write` | `INSERT`/`UPDATE`/`DELETE` on internal tables; CRM entity writes go through pending review |
| `initiate_connector` | Start OAuth / connect flow for a new provider |
| `run_workflow` | Run another workflow by id (composition); optional wait |
| `foreach` | Batch over SQL `items_query` or inline list — tool mode or nested `workflow_id` |
| `manage_memory` | Save / update / delete durable user-scoped memories |
| `keep_notes` | Workflow-scoped notes (`workflow_only`) |

**External Write** (mutations and side effects outside direct SQL):

| Tool | Description |
| ---- | ----------- |
| `write_on_connector` | Connector writes — CRM records, issues, Drive files, `artifacts`, `apps`, etc. |
| `run_on_connector` | Connector actions — Slack/Email/SMS, `fetch_url`, sandbox `execute_command`, … |
| `trigger_sync` | Kick off a background sync for a provider |

### Tool Execution Flow

1. User sends a message over `/ws/chat` (or a messenger delivers it through the same orchestrator path).
2. `ChatOrchestrator` streams from the configured model with [`get_tool_defs`](backend/agents/registry.py).
3. On each `tool_use`, the server emits a **short status line** from [`format_tool_status`](backend/agents/registry.py) (e.g. “Querying your database”, “Reading HubSpot docs”) so Slack/Teams/web clients can show progress spinners.
4. `execute_tool()` in [`agents/tools.py`](backend/agents/tools.py) runs the tool, results are appended to the conversation, and the model continues until a final assistant message.

### Frontend Display

[`Chat.tsx`](frontend/src/components/Chat.tsx) renders streamed markdown and **status/progress events** from the server — it does not embed tool schemas. Heavy logic stays in Python on the backend.

## Agent Tool Categories

The agent's tools are organized by risk level with an approval system for safety:

| Category           | Approval               | Examples                                                             |
| ------------------ | ---------------------- | -------------------------------------------------------------------- |
| **Local Read**     | None                   | `run_sql_query`, `search_documents`, `list_connected_connectors`, `get_connector_docs` |
| **Local Write**    | Tracked                | `run_sql_write` (internal tables), `initiate_connector`, `run_workflow`, `foreach`, memories |
| **External Read**  | None                   | `query_on_connector` (web search, Drive, Apollo, …)                  |
| **External Write** | User approval required | `write_on_connector`, `run_on_connector` (CRM, Slack, email, SMS, …), `trigger_sync` |

Users review and approve risky external writes in the **Pending Changes** panel before they execute.

## Workflows

Basebase workflows automate recurring agent tasks:

- **Schedule-based** — Cron expressions (e.g. "every weekday at 9am")
- **Event-based** — Triggered by system events (e.g. "after data sync completes")
- **Manual** — Triggered on demand by users or other workflows

Workflows can be defined as natural-language prompts (the agent interprets and executes them) or as structured step sequences. Actions include SQL queries, LLM processing, Slack messages, emails, and SMS.

## Features

- **Agentic Intelligence** — AI agent with tool access across connected data sources and live connectors
- **20+ integrations** — CRM, email, calendar, Slack/Teams, issue trackers, code, meetings, files, enrichment, TV analytics, MCP, and built-ins (web search, sandbox, SMS, artifacts, apps)
- **Multi-channel** — Web app, Slack, Microsoft Teams, SMS (Twilio), and WhatsApp
- **Real-time streaming** — WebSocket-first chat with token streaming and background task catch-up
- **Automated workflows** — Scheduled, event-driven, and manual runs (`run_workflow`, `foreach`)
- **Agent composition** — Workflows call child workflows; `foreach` batches tools or workflows over SQL or lists
- **Approval workflow** — External connector writes go through pending review where required
- **Semantic search** — Vector search across activities and related entities
- **Artifacts & mini-apps** — Plotly charts, PDFs, markdown docs, and Sandpack-powered interactive apps
- **Public sharing** — Linkable public views for apps and artifacts when enabled ([`/api/public`](backend/api/routes/public.py))
- **Daily digests & workstreams** — Per-user digest generation and semantic conversation clustering on Home
- **Topic graph (“Graph Magic”)** — Optional nightly topic graph over org content ([`services/topic_graph.py`](backend/services/topic_graph.py))
- **Data enrichment** — Apollo.io and web-search connectors
- **Persistent memory** — User-scoped memories recalled at conversation start
- **Multiple conversations** — Threads with org-scoped visibility options
- **Data normalization** — Synced external data lands in shared relational tables
- **Supabase auth** — Google OAuth, email/password, waitlist and invite flows
- **Unified OAuth (Nango)** — OAuth connectors delegate token lifecycle to Nango
- **Stripe billing & credits** — Subscriptions and usage credits ([`/api/billing`](backend/api/routes/billing.py))

## License

MIT
