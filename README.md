# RevFlow

RevFlow is an AI-assisted payment recovery platform for Razorpay merchants. It listens for payment webhooks, detects failed payments, opens recovery cases, and helps get that revenue back through retries, payment links, and customer emails — with an optional AI layer that recommends and can execute recovery actions.

## What RevFlow Does

When a customer's payment fails, that revenue is usually just lost. RevFlow sits between your Razorpay account and your business logic to catch these failures automatically:

- Receives `payment.failed` and `payment.captured` events from Razorpay
- Classifies why a payment failed and opens a recovery case for it
- Recommends and (optionally) executes a recovery action — retry, payment link, or email
- Tracks each case until it's `RECOVERED`, `EXHAUSTED`, or `CANCELLED`
- Gives merchants a dashboard to see recovery performance across their organization

It's a multi-tenant system — every merchant's data lives under their own `organization_id`, and users sign in with Google via Firebase.

## Main Features

- Google sign-in via Firebase, with automatic workspace creation for first-time users
- Signed and idempotent Razorpay webhook ingestion
- Automatic recovery case creation for failed payments
- Recovery actions: scheduled retries, Razorpay payment links, recovery emails
- Optional AI recommendation layer (multi-agent) — **off by default**, controlled by feature flags
- Background processing via Redis + Celery for anything that shouldn't block the request
- Merchant dashboard with recovery stats, case lists, and case detail views
- Tenant isolation on every recovery-related table

## End-to-End Workflow

1. A customer's payment fails on Razorpay.
2. Razorpay sends a `payment.failed` webhook to RevFlow.
3. RevFlow verifies the signature, checks the event hasn't been processed before, and stores it.
4. A payment record is created/updated and a recovery case is opened, classified by failure reason.
5. If AI recommendations are enabled, the multi-agent workflow proposes an action with a confidence score.
6. A recovery action is scheduled — a Celery worker executes the retry, generates a payment link, or sends an email.
7. If the customer later succeeds (a `payment.captured` event correlated to the earlier failure), the case is marked `RECOVERED`.
8. The merchant watches all of this happen in real time on the dashboard.

## High-Level Architecture

RevFlow is a monorepo with two applications:

- **`frontend/`** — Next.js dashboard the merchant uses
- **`revenue-recovery/`** — FastAPI backend that does the actual work

The backend talks to PostgreSQL for storage, Firebase Admin SDK for auth verification, Redis/Celery for background jobs, and the Razorpay SDK for payments and payment links. AI recommendations, when enabled, run through a small multi-agent workflow before anything is stored as an `ai_recovery_decisions` row.

## Architecture Diagram

![RevFlow Architecture](./architecture-diagram.png)

## Frontend Overview

Located in `frontend/`. A Next.js + TypeScript app styled with Tailwind CSS, using Recharts for charts, Lucide for icons, and Motion for animation.

Pages:
- Landing page
- Login (Firebase Google sign-in)
- Dashboard overview
- Recovery cases list and case detail
- Analytics

The frontend never talks to Razorpay or the database directly. It calls the backend through an API client that attaches the Firebase ID token on every request, and a Next.js rewrite forwards `/api/*` calls to the FastAPI backend so the browser only ever sees one origin.

## Backend Overview

Located in `revenue-recovery/`. A FastAPI app with all routes under `/api/v1`, using SQLAlchemy + PostgreSQL for storage, Alembic for migrations, the Firebase Admin SDK for token verification, the Razorpay SDK for payments and payment links, and Redis/Celery for background work. Interactive API docs are served at `/docs`.

## Authentication and Authorization

1. The user signs in with Google through Firebase Authentication on the frontend.
2. The frontend gets back a Firebase ID token and sends it as a `Bearer` token on every API request.
3. The backend verifies the token using the Firebase Admin SDK.
4. The verified email is mapped to an application user. First-time users get a private workspace (organization) created automatically.
5. Every user belongs to exactly one organization, and every query for recovery data is filtered by `organization_id`.

## Razorpay Webhook Processing

`POST /api/v1/webhooks/razorpay`

- Reads the **raw** request body (needed for signature verification — don't let anything re-serialize it first)
- Validates the `X-Razorpay-Signature` header using HMAC-SHA256
- Requires a Razorpay event ID and rejects payloads that don't have one
- Validates the payload shape with Pydantic
- Uses the event ID for idempotency — replays of the same event are safely ignored
- Stores every event in `webhook_events`, then processes `payment.failed` and `payment.captured`
- Correlates a later successful payment with an earlier failure so recovery cases can close correctly

```mermaid
sequenceDiagram
    participant RP as Razorpay (Test Mode)
    participant API as FastAPI
    participant SVC as Webhook Service
    participant DB as PostgreSQL
  participant TASK as Celery Task

    RP->>API: POST /api/v1/webhooks/razorpay<br/>(raw body + X-Razorpay-Signature + X-Razorpay-Event-Id)
  API->>API: Verify HMAC-SHA256 signature on raw body
    alt invalid signature
        API-->>RP: 400 Bad Request
    else valid signature
    API->>API: Require event ID and parse payload (Pydantic)
        API->>SVC: handle_razorpay_webhook(event_id, event)
    SVC->>DB: Check provider + event_id
        alt duplicate
            SVC-->>API: ignored_duplicate
        else new event
      SVC->>DB: INSERT webhook_events row and flush
      SVC->>SVC: Process payment and recovery state
      SVC->>DB: Commit event and derived state
      opt unmatched payment capture
        SVC->>TASK: Queue payment-link resolution
      end
            SVC-->>API: processed
        end
        API-->>RP: 200 OK
    end
```

## Payment Recovery Workflow

1. A failed payment is classified by failure reason.
2. A recovery case is opened and recovery actions are tracked against it.
3. Retry attempts can be scheduled, or the case can sit waiting on customer action.
4. A Razorpay payment link can be generated and a recovery email sent.
5. A case ends up `RECOVERED`, `EXHAUSTED`, or `CANCELLED`. A matching `payment.captured` event can resolve a case directly.

## AI Recovery Workflow

RevFlow includes an optional multi-agent recommendation flow: **Strategist → Historical Intelligence → Critic → Final Decision**. It looks at customer history, past recovery outcomes, the failure reason, and policy constraints to propose an action with a confidence score.

Every AI decision is stored with its recommended action, confidence, reasoning, provider, model, whether it was accepted, whether it was executed, and the eventual outcome.

Two separate flags control this, and both default off:
- `AI_ENABLED` — whether recommendations are generated at all
- `AI_AGENT_ENABLED` — whether an accepted recommendation is allowed to actually execute

AI is not "always on," and an accepted recommendation is not automatically executed unless both flags allow it.

## Background Jobs with Redis and Celery

Redis is the Celery broker. Celery workers run the tasks that shouldn't block an API response: payment retries, sending recovery emails, resolving payment-link captures, customer recovery flows, and executing AI-approved actions.

**The Celery worker (and Redis) must be running**, or nothing scheduled through them will ever complete — retries and emails will just sit queued.

## Customer Communication and Payment Links

When a recovery action calls for it, RevFlow can generate a Razorpay payment link and send the customer a recovery email containing it. In development, emails go through a console provider (printed to logs); in production, this is backed by an SMTP or Resend provider.

## Database and Tenant Isolation

PostgreSQL tables:

| Table | Purpose |
|---|---|
| `organizations` | Merchant tenants |
| `users` | App users, mapped from Firebase identities |
| `webhook_events` | Raw Razorpay events, for idempotency and auditing |
| `payments` | Payment records |
| `recovery_cases` | One per failed payment being recovered |
| `recovery_actions` | Actions taken/scheduled against a case |
| `payment_links` | Razorpay payment links generated for recovery |
| `recovery_communications` | Emails/messages sent to customers |
| `ai_recovery_decisions` | Stored AI recommendations and outcomes |

Every merchant-owned table carries an `organization_id`, and all backend queries filter on it. There is no cross-tenant read path — if a merchant's dashboard shows no data, the first thing to check is whether `organization_id` actually matches between the user and the rows.

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/api/v1/webhooks/razorpay` | Razorpay webhook receiver |
| GET | `/api/v1/recovery/stats` | Recovery performance stats |
| GET | `/api/v1/recovery/cases` | List recovery cases |
| GET | `/api/v1/recovery/cases/{case_id}` | Case detail |
| POST | `/api/v1/recovery/cases/{case_id}/retry` | Schedule a retry |
| POST | `/api/v1/recovery/cases/{case_id}/recover-now` | Trigger immediate recovery |

Full interactive docs live at `http://localhost:8000/docs`.

## Project Structure

```
revflow/
├── frontend/              # Next.js dashboard
│   ├── app/                # pages: landing, login, dashboard, cases, analytics
│   ├── lib/                 # API client, Firebase config
│   └── ...
└── revenue-recovery/       # FastAPI backend
    ├── app/
    │   ├── api/              # routers: health, webhooks, recovery, analytics
    │   ├── services/         # webhook, payment, recovery, AI services
    │   ├── agents/           # strategist, historical, critic, final decision
    │   ├── models/           # SQLAlchemy models
    │   ├── tasks/            # Celery tasks
    │   └── main.py
    ├── alembic/              # migrations
    └── tests/
```

## Prerequisites

- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- Node.js 18+ and npm
- PostgreSQL (local or hosted)
- Redis (local or hosted)
- A Firebase project (Authentication + a service account for Admin SDK)
- A Razorpay account in test mode

## Environment Variables

Never commit real secrets — `.env` files should always be in `.gitignore`.

**Backend (`revenue-recovery/.env`):**

```
APP_ENV=development
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/revflow
RAZORPAY_KEY_ID=rzp_test_your_key
RAZORPAY_KEY_SECRET=your_razorpay_secret
RAZORPAY_WEBHOOK_SECRET=your_webhook_secret
FIREBASE_PROJECT_ID=your_firebase_project_id
FIREBASE_CLIENT_EMAIL=your_firebase_service_account_email
FIREBASE_PRIVATE_KEY=your_firebase_private_key
REDIS_URL=redis://localhost:6379/0
AI_ENABLED=false
AI_AGENT_ENABLED=false
```

**Frontend (`frontend/.env.local`):**

```
NEXT_PUBLIC_FIREBASE_API_KEY=your_firebase_api_key
NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN=your_project.firebaseapp.com
NEXT_PUBLIC_FIREBASE_PROJECT_ID=your_firebase_project_id
NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET=your_project.appspot.com
NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID=your_sender_id
NEXT_PUBLIC_FIREBASE_APP_ID=your_firebase_app_id
BACKEND_URL=http://localhost:8000
```

## Local Installation

Clone the repo, then set up each app.

**Backend:**

```bash
cd revenue-recovery
uv sync
```

**Frontend:**

```bash
cd frontend
npm install
```

## Database Migration Setup

With `DATABASE_URL` set in `revenue-recovery/.env`:

```bash
cd revenue-recovery
uv run alembic upgrade head
```

## Running the Backend

```bash
cd revenue-recovery
uv run uvicorn app.main:app --reload --port 8000
```

Also start a Celery worker in a separate terminal so background jobs actually run:

```bash
cd revenue-recovery
uv run celery -A app.tasks worker --loglevel=info --pool=solo
```

(`--pool=solo` is the simplest option on Windows; on Linux/macOS you can drop it.)

- Backend: http://localhost:8000
- Health check: http://localhost:8000/health
- Swagger docs: http://localhost:8000/docs

## Running the Frontend

```bash
cd frontend
npm run dev
```

- Frontend: http://localhost:3000

## Running Tests

```bash
cd revenue-recovery
uv run pytest
```

Frontend linting:

```bash
cd frontend
npm run lint
```

## Razorpay Test-Mode Setup

1. Use your Razorpay **test mode** keys for `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`.
2. Since Razorpay needs a public URL to deliver webhooks, expose your local backend with a tunnel (e.g. zrok, ngrok) pointing at `http://localhost:8000`.
3. In the Razorpay dashboard, register a webhook pointing to `https://<your-tunnel-url>/api/v1/webhooks/razorpay`.
4. Set the same secret you configured in the dashboard as `RAZORPAY_WEBHOOK_SECRET`.
5. Trigger a test failed payment and confirm a row appears in `webhook_events` and a recovery case is created.

## Troubleshooting

- **Firebase token verification fails** — check `FIREBASE_PROJECT_ID` / `FIREBASE_CLIENT_EMAIL` / `FIREBASE_PRIVATE_KEY` are correct and the private key's newlines weren't mangled.
- **Expired Firebase token** — the frontend should refresh the ID token; if requests suddenly start 401ing, sign out and back in.
- **No application user / workspace found** — confirm the first-login workspace-creation step actually ran; check backend logs for that request.
- **Dashboard shows no data** — almost always an `organization_id` mismatch between the signed-in user and the rows being queried.
- **PostgreSQL connection errors** — verify `DATABASE_URL`, that Postgres is running, and that migrations have been applied.
- **Nothing happens after a retry/email is scheduled** — Redis and/or the Celery worker isn't running. Start both.
- **Invalid Razorpay webhook signature** — the webhook secret in `.env` doesn't match what's configured in the Razorpay dashboard, or the raw body was modified before verification.
- **Duplicate webhook events** — expected and safe; RevFlow ignores already-processed event IDs by design.
- **Frontend can't reach the backend** — check the Next.js rewrite config and that `BACKEND_URL` points at the running backend.
- **Missing environment variables** — the backend will generally fail fast on startup; check the error message for which key is missing.

## Security Notes

- Webhook signatures are verified with HMAC-SHA256 before any payload is trusted.
- All API requests are authenticated via Firebase ID tokens, verified server-side.
- All recovery data is scoped to the requesting user's `organization_id` — no cross-tenant access.
- Webhook processing is idempotent by event ID, so retried deliveries can't create duplicate records.
- No real secrets, private keys, or customer data are ever committed — `.env` files stay out of version control.

## Roadmap

- Broader AI provider support and tuning of agent confidence thresholds
- Additional recovery channels beyond email and payment links
- Deeper analytics on recovery-rate trends by failure reason
- Expanded automated test coverage across the AI decision pipeline

## Project Status

RevFlow is under active development. Authentication, multi-tenant organizations, webhook processing, the recovery workflow, background jobs, and the dashboard are implemented and working; the AI recommendation/execution layer is feature-flagged and off by default until it's been tuned further.
