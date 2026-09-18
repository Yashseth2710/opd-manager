# OPD Manager

**The modern operating system for outpatient clinics.**

OPD Manager is a multi-tenant SaaS platform for running an outpatient department end to end — patient registration, appointments, doctor schedules, the OPD queue, consultations, prescriptions, billing, payments, and the analytics that tie it together.

The idea behind it is simple:

> One patient. One complete timeline. One connected OPD workflow.

## Why

Most small clinics still run on a mix of paper registers, spreadsheets, phone calls and a separate billing system. Patients wait longer than they should, records get duplicated, history is hard to pull up mid-consultation, and nobody has a clear picture of how the clinic is actually performing.

OPD Manager puts that whole workflow in one place.

## The workflow

```
Registration → Appointment → Check-in → Queue → Consultation
     → Diagnosis → Prescription → Billing → Payment → Follow-up
```

## Stack

**Frontend** — Next.js, TypeScript, Tailwind, shadcn/ui, TanStack Query & Table, React Hook Form, Zod, Recharts

**Backend** — FastAPI, Pydantic, SQLAlchemy 2.x, Alembic

**Data** — Neon PostgreSQL, Upstash Redis, Vercel Blob

**Hosting** — Vercel, one project serving both halves

## Getting started

The database and cache are hosted, so there is nothing to install and run
locally besides the two applications. You will need Python 3.12, Node 22 or
newer, a [Neon](https://neon.tech) Postgres branch and an
[Upstash](https://upstash.com) Redis database, both on the free tier.

```
cp backend/.env.example backend/.env      # then fill in the four connection values
cd backend && pip install -r requirements-dev.txt && alembic upgrade head
cd ../frontend && npm install
```

Run each half in its own terminal:

```
./start-backend.ps1     # http://127.0.0.1:8000
./start-frontend.ps1    # http://localhost:3000
```

The web app proxies `/api/v1` to the API in development, so open
`http://localhost:3000` and register a clinic. `/status` reports whether the
database and cache are answering.

Email is optional. With `BREVO_API_KEY` and `RESEND_API_KEY` both left blank,
password reset, confirmation and invitation links are written to the API's log
instead of being sent, and new accounts are created already confirmed so the
application stays usable.

### Tests

The API suite drops every table it touches, so it refuses to run unless
`ENVIRONMENT=test` and it is pointed at a database kept for the purpose.

```
cd backend && pytest
```

The browser suite drives the running application, so it needs both halves up
and an API with no email provider configured — it sets up its own clinics, and
a confirmation step it cannot read would stop it at the first screen. It also
invites a doctor to one of them and follows the link the API writes to its
log, so the API's output has to go to a file the suite is told about.

```
cd backend && python -m uvicorn app.main:app --port 8000 > api.log 2>&1
cd frontend && npx playwright install chromium   # once
E2E_API_LOG=../backend/api.log npm run e2e
```

## Status

Early development. Architecture and conventions are documented in [`docs/`](docs/); implementation follows the build order described there.

## A note on the data

Everything in this repository — seeds, fixtures, tests, screenshots — uses synthetic data. No real patient information is used anywhere, and this build has not been assessed against any healthcare regulation. It is not certified for clinical use.

## Licence

MIT © Yash Seth
