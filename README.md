# Revenue Recovery Agent

**Phase 1: Razorpay Test Mode + Backend Foundation**

An AI-powered revenue recovery platform, built incrementally. Phase 1 establishes the
foundation: receiving, validating, and safely storing Razorpay payment webhooks.

> This is Phase 1 of a multi-phase build. Later phases will add a decision engine, an
> AI/LangGraph agent workflow, ML-based customer scoring, automated recovery actions, and
> a React dashboard. None of that exists yet, on purpose — see [Roadmap](#roadmap).

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Environment Variables](#environment-variables)
- [Installation (Windows)](#installation-windows)
- [Database Setup](#database-setup)
- [Running Locally](#running-locally)
- [Razorpay Test Mode Setup](#razorpay-test-mode-setup)
- [Webhook Setup](#webhook-setup)
- [Testing](#testing)
- [Project Structure](#project-structure)
- [Security Notes](#security-notes)
- [What This Phase Teaches](#what-this-phase-teaches)
- [Roadmap](#roadmap)

---

## Project Overview

The end goal of this project is a system that can answer:

> "A ₹85,000 payment failed. Why did it fail, how valuable is this customer, what is the
> best recovery action, is that action allowed by policy, did the action recover the
> money, and how much revenue has the system recovered?"

Phase 1 only builds the first link in that chain: **reliably receiving and recording
Razorpay payment events.** Nothing here makes decisions, retries payments, or talks to
an LLM — that's deliberate. A recovery engine is only as trustworthy as the event data
feeding it, so this phase focuses entirely on getting that data pipeline correct,
secure, and idempotent.

## Architecture

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

Full target architecture (later phases will fill in the rest):

```text
                    Razorpay
                  Test / Live
                       |
                       | Webhooks
                       v
                   FastAPI            <-- Phase 1 (this phase)
                       |
                       v
                  PostgreSQL          <-- Phase 1 (this phase)
                       |
                       v
                Revenue Recovery
                     Engine           <-- future phase
                       |
              +--------+--------+
              |                 |
             LLM               ML    <-- future phase
              |                 |
              +--------+--------+
                       v
                   LangGraph
                Agent Workflow        <-- future phase
                       |
                       v
                 Policy Engine        <-- future phase
                       |
              +--------+--------+
              v        v        v
            Retry    Notify   Escalate  <-- future phase
              |        |        |
              +--------+--------+
                       v
                  Observe Result     <-- future phase
                       |
                       v
                 Revenue Metrics     <-- future phase
                       |
                       v
                React Dashboard      <-- future phase
```

## Tech Stack

| Layer          | Technology                       |
|----------------|-----------------------------------|
| Web framework  | FastAPI                          |
| Validation     | Pydantic v2 / pydantic-settings  |
| ORM            | SQLAlchemy 2.x                   |
| Migrations     | Alembic                          |
| Database       | PostgreSQL                       |
| DB driver      | psycopg 3                        |
| Payments       | Razorpay Python SDK (Test Mode)  |
| Testing        | pytest, httpx, FastAPI TestClient|

Not used yet (future phases): Redis, Celery, LangChain, LangGraph, an LLM, ML scoring,
React, Docker, CI/CD.

## Prerequisites

- **Python 3.11+** (developed/tested on 3.12)
- **PostgreSQL** running locally (or accessible via a connection string)
- A **Razorpay account** with Test Mode access (free to create)
- **Windows** development environment (commands below use PowerShell/cmd)
- A tunneling tool to expose localhost to Razorpay's webhook servers — see
  [Webhook Setup](#webhook-setup) for why we use **zrok**, not ngrok

## Environment Variables

Copy `.env.example` to `.env` and fill in real values:

```text
APP_ENV=development

RAZORPAY_KEY_ID=rzp_test_xxxxxxxxxxxxxxxx
RAZORPAY_KEY_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx
RAZORPAY_WEBHOOK_SECRET=xxxxxxxxxxxxxxxxxxxxxxxx

DATABASE_URL=postgresql+psycopg://revenue_recovery:revenue_recovery@localhost:5432/revenue_recovery

LOG_LEVEL=INFO
```

**Never commit `.env`.** It's already listed in `.gitignore`. Secrets belong only in
your local `.env` file or your deployment platform's secret manager — never in source
code. If a secret is committed to Git, it remains recoverable from history forever, even
after being deleted in a later commit; anyone with repo access (including in a public
fork or a leaked clone) can extract it.

## Installation (Windows)

Open PowerShell in the project root:

```powershell
# 1. Create and activate a virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# If PowerShell blocks script execution, run this once (as your user, not admin):
# Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

# 2. Install dependencies
pip install -r requirements.txt

# 3. Create your .env file
copy .env.example .env
# then edit .env in your editor of choice
```

## Database Setup

Install PostgreSQL locally (e.g. via the official installer, or `winget install
PostgreSQL.PostgreSQL`), then create the database and user:

```powershell
# Open psql as the postgres superuser (adjust as needed for your install)
psql -U postgres
```

```sql
CREATE USER revenue_recovery WITH PASSWORD 'revenue_recovery';
CREATE DATABASE revenue_recovery OWNER revenue_recovery;
\q
```

Update `DATABASE_URL` in `.env` if you used different credentials, then run migrations:

```powershell
alembic upgrade head
```

This creates the single `webhook_events` table Phase 1 needs. You should see:

```text
INFO  [alembic.runtime.migration] Running upgrade  -> 120e07d931a3, create webhook_events table
```

## Running Locally

```powershell
uvicorn app.main:app --reload
```

Visit:
- `http://127.0.0.1:8000/health` — should return `{"status": "healthy"}`
- `http://127.0.0.1:8000/docs` — interactive Swagger UI, useful for manually inspecting
  the webhook endpoint's schema

## Razorpay Test Mode Setup

1. **Create a Razorpay account** at [dashboard.razorpay.com](https://dashboard.razorpay.com)
   if you don't have one. New accounts start in Test Mode.
2. **Confirm you're in Test Mode** — there's a mode toggle in the dashboard sidebar/header.
   Test Mode transactions never move real money and don't require KYC to start using.
3. **Generate Test API keys**: Dashboard → Settings → API Keys → "Generate Test Key".
   Copy the Key ID (`rzp_test_...`) and Key Secret into `.env` as `RAZORPAY_KEY_ID` and
   `RAZORPAY_KEY_SECRET`. The secret is shown only once — store it now.
4. **Create the webhook** (Dashboard → Settings → Webhooks → "+ Add New Webhook"):
   - **Webhook URL**: your public tunnel URL (see [Webhook Setup](#webhook-setup)) +
     `/api/v1/webhooks/razorpay`
   - **Secret**: choose any strong random string. This is *not* your API key secret — it's
     a separate value used only to sign webhook payloads. Put the same value in `.env` as
     `RAZORPAY_WEBHOOK_SECRET`.
   - **Active Events**: check `payment.captured` and `payment.failed` at minimum.
   - When prompted for an OTP while creating/editing a Test Mode webhook, Razorpay's
     documented default Test Mode OTP is `754081`.
5. **Trigger test payments**: use Razorpay's [Test Card/UPI
   numbers](https://razorpay.com/docs/payments/payments/test-card-upi-details/) against a
   test Checkout integration, or use the Razorpay Dashboard's "Test payment" flows where
   available. A test card ending in a specific pattern (check current Razorpay docs, as
   these test values can change) reliably produces a `payment.failed` event — useful for
   exercising this phase's primary use case.

> Razorpay's dashboard UI and exact test-value conventions do change over time. If
> anything above doesn't match what you see, treat the [Razorpay Docs](https://razorpay.com/docs/)
> as the source of truth, not this README.

## Webhook Setup

Razorpay needs a **public** HTTPS URL to deliver webhooks to — it cannot reach
`localhost` directly. You need a tunneling tool.

**Important:** Razorpay's webhook configuration currently **blacklists several common
tunneling domains for security reasons, including `ngrok.io` and `loca.lt`.** Razorpay's
own documentation recommends **[zrok](https://docs.zrok.io/docs/zrok/getting-started)**
for exposing localhost during webhook development. Use zrok, not ngrok, or your webhook
URL will be rejected when you try to save it in the Razorpay dashboard.

```powershell
# after installing zrok per https://docs.zrok.io/docs/zrok/getting-started
zrok share public http://127.0.0.1:8000
```

zrok will print a public HTTPS URL (e.g. `https://abcd1234.share.zrok.io`). Use
`<that-url>/api/v1/webhooks/razorpay` as the Webhook URL when creating the webhook in the
Razorpay dashboard (step 4 above).

### Testing `payment.failed` end-to-end

1. Start the app (`uvicorn app.main:app --reload`) and your zrok tunnel.
2. Trigger a test payment that fails (see step 5 above).
3. Watch your `uvicorn` terminal — you should see log lines like:
   ```text
   2026-01-15 10:22:03 | INFO | app.services.webhook_service | Processed payment.failed | payment_id=pay_... order_id=order_... amount=8500000 currency=INR status=failed error_code=BAD_REQUEST_ERROR
   ```
4. Verify signature validation worked (no `400` in the logs for this event).
5. Verify storage:
   ```powershell
   psql -U revenue_recovery -d revenue_recovery -c "SELECT event_id, event_type, status, received_at FROM webhook_events ORDER BY received_at DESC LIMIT 5;"
   ```
6. Re-trigger delivery of the **same** event from the Razorpay Dashboard (Webhooks →
   your webhook → recent deliveries → "Resend") and confirm the log shows
   `ignored_duplicate` and the row count in `webhook_events` for that `event_id` stays at 1.

## Testing

Tests run entirely offline — no real Razorpay account or live PostgreSQL required. They
use an in-memory SQLite database and locally-generated HMAC signatures that match
Razorpay's documented signing algorithm exactly.

```powershell
pytest -v
```

Expected: **14 passed**. Coverage includes:

| Test class              | What it verifies                                              |
|--------------------------|-----------------------------------------------------------------|
| `TestValidSignature`     | Correctly-signed `payment.failed`/`payment.captured` events are accepted, processed, and persisted with correct fields |
| `TestInvalidSignature`   | Wrong or missing `X-Razorpay-Signature` → `400`, nothing persisted |
| `TestUnsupportedEvent`   | Event types outside Phase 1's scope (e.g. `payment.authorized`) are acknowledged (`200`, so Razorpay doesn't retry forever) but not marked "processed" |
| `TestDuplicateEvent`     | The same `X-Razorpay-Event-Id` delivered twice is only stored/processed once |
| `TestMalformedPayload`   | Invalid JSON or a body missing required fields → `400`, nothing persisted |
| `test_health.py`         | `GET /health` → `200` |

## Razorpay Standard Checkout (Test Mode UPI)

Payment Links remain the recovery flow's emailed/customer-facing path. Standard Checkout is
an additional, small browser page for creating a Razorpay Order and testing direct UPI payment
events without consuming Payment Link quota.

1. Start PostgreSQL and Redis, then run `uv run alembic upgrade head`.
2. Start the API with `uv run uvicorn app.main:app --reload` and Celery with
   `uv run celery -A app.tasks.celery_app worker --loglevel=info --pool=solo`.
3. Start the same HTTPS tunnel used for the Razorpay webhook, and configure the Test Mode
   webhook URL as `<tunnel>/api/v1/webhooks/razorpay`. Enable `payment.captured` and
   `payment.failed` in the Razorpay dashboard.
4. Open `http://127.0.0.1:8000/api/v1/payments/checkout` and create an INR order.
5. In Razorpay Checkout select UPI. In Test Mode, enter `success@razorpay` to simulate a
   capture or `failure@razorpay` to simulate a failure. These are Razorpay's documented test
   UPI IDs; no real money moves. See Razorpay's
   [current Test UPI documentation](https://razorpay.com/docs/payments/payments/test-upi-details/).
6. A successful browser response is signature-verified by `POST /api/v1/payments/checkout/verify`.
   It deliberately remains `verified_pending_webhook`: only the signed webhook changes payment
   state. A `payment.captured` event marks the persisted payment `SUCCESS`; a `payment.failed`
   event enters the existing recovery workflow.

The browser receives only the Test Mode Key ID, order ID, amount in paise, and currency. The
Razorpay secret never leaves the server. Razorpay's
[Standard Checkout integration guide](https://razorpay.com/docs/payments/payment-gateway/web-integration/standard/integration-steps/)
explains why the server must verify the returned signature and why webhooks remain authoritative.

## Project Structure

```text
revenue-recovery/
|
+-- app/
|   +-- main.py                    FastAPI app instance, router registration, lifespan
|   |
|   +-- core/
|   |   +-- config.py              Pydantic Settings (env-var driven configuration)
|   |   +-- logging.py             Structured logging setup
|   |
|   +-- api/routes/
|   |   +-- health.py              GET /health
|   |   +-- webhooks.py            POST /api/v1/webhooks/razorpay -- HTTP layer only
|   |
|   +-- schemas/
|   |   +-- webhook.py             Pydantic models for Razorpay's webhook payload shape
|   |
|   +-- services/
|   |   +-- razorpay_client.py     Signature verification (Razorpay-specific mechanics)
|   |   +-- webhook_service.py     Idempotency + storage business logic
|   |
|   +-- models/
|   |   +-- webhook_event.py       SQLAlchemy ORM model: the webhook_events table
|   |
|   +-- db/
|       +-- session.py             Engine, session factory, declarative Base
|
+-- alembic/
|   +-- env.py                     Wired to app Settings + ORM metadata
|   +-- versions/
|       +-- ..._create_webhook_events_table.py
|
+-- tests/
|   +-- conftest.py                Fixtures: in-memory DB, test client, sample payloads
|   +-- test_health.py
|   +-- test_webhooks.py
|
+-- .env.example
+-- .gitignore
+-- requirements.txt
+-- alembic.ini
+-- pyproject.toml
+-- README.md
```

**Why this separation matters:**
- `api/routes/webhooks.py` only knows about HTTP (status codes, headers, request/response
  bodies). It has no idea what "idempotency" means.
- `services/razorpay_client.py` only knows Razorpay-specific mechanics (HMAC signature
  verification). It has no idea what a database is.
- `services/webhook_service.py` only knows business rules (has this event been seen
  before? what do we do with a supported vs. unsupported event type?). It has no idea
  what HTTP status code the caller will eventually return.

If Razorpay changes their signing mechanism, only `razorpay_client.py` changes. If we add
a second payment provider, `webhook_service.py`'s shape barely changes (the `provider`
column already exists for exactly this reason) and only the routes/schemas grow.

## Security Notes

- **Secrets** (`RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`, `DATABASE_URL`) live only
  in `.env`, which is gitignored. Never hardcode them.
- **Signature verification is mandatory and happens first.** No payload is parsed, logged
  in detail, or stored until its signature is verified against the raw request body.
  Razorpay's docs are explicit that the signature must be computed over the *raw* body,
  not a re-serialized version of parsed JSON — we honor that by reading `request.body()`
  before any parsing occurs.
- **We never log secrets.** `RAZORPAY_KEY_SECRET` and `RAZORPAY_WEBHOOK_SECRET` never
  appear in any log statement.
- **We log payment metadata (ID, order ID, amount, status, error code) but not customer
  PII** (email, phone) at the info level, to limit what's exposed if logs ever leak.
- **Idempotency is enforced twice**: once at the application level (a `SELECT` before
  inserting) and once at the database level (a `UNIQUE` constraint on
  `(provider, event_id)`), so a race between two concurrent webhook deliveries for the
  same event can't produce duplicate rows.
- **Internal errors never leak stack traces to the caller.** A `500` response is generic;
  the real exception is logged server-side only.

## What This Phase Teaches

By the end of Phase 1 you should understand:

- **REST endpoint** — a URL + HTTP method combination your server responds to (e.g.
  `POST /api/v1/webhooks/razorpay`).
- **Webhook** — instead of you polling Razorpay for updates, Razorpay proactively `POST`s
  event data to a URL you control, when something happens on their end.
- **Webhook signature** — proof that a webhook request genuinely came from Razorpay (and
  wasn't forged by an attacker who guessed your endpoint URL). Computed as
  `HMAC-SHA256(raw_request_body, your_webhook_secret)` and sent in the
  `X-Razorpay-Signature` header; you recompute it yourself and compare.
- **Event** — a single notification of something that happened (e.g. "this payment
  failed"). Has a type (`payment.failed`) and a payload (the details).
- **Event ID** — a unique identifier Razorpay assigns to each webhook delivery, distinct
  from the Payment ID or Order ID. Used to detect redelivery of the same event.
- **Idempotency** — designing a system so that processing the same input twice has the
  same effect as processing it once. Necessary because webhook providers retry delivery
  (network failures, timeouts) and may send the same event more than once.
- **FastAPI route** — a Python function decorated to handle a specific endpoint,
  declaring its expected inputs (headers, body) and output shape.
- **Service layer** — business logic pulled out of route handlers into separate,
  independently testable functions/modules, so routes stay thin and logic isn't
  duplicated if a second entry point (e.g. a CLI command) needs it later.
- **Database persistence** — writing data to PostgreSQL via SQLAlchemy's ORM, so it
  survives past the lifetime of a single request/process.
- **Migration** — a versioned, incremental change to your database schema (here:
  "create the `webhook_events` table"), managed by Alembic so schema changes are
  tracked, reproducible, and reversible, rather than made by hand against a live DB.

## Roadmap

**Phase 2 (preview only — not built yet):** will likely introduce the `orders`/`payments`
domain tables beyond raw event storage, and start deriving structured payment records
from the events we're now capturing — still no AI, ML, or automated actions. Say
**"Proceed to Phase 2"** when you're ready and we'll scope it precisely before writing
any code.
