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

**Frontend** — Next.js, TypeScript, Tailwind, TanStack Query, Zod, Playwright

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
application stays usable. Notices somebody has asked to get by email go to the
same log, and still show in the app.

Online payment is optional too. Leave `RAZORPAY_KEY_ID` and
`RAZORPAY_KEY_SECRET` blank and the desk still takes cash, UPI and cards by
hand; the option to send a patient a link is simply not offered. Test keys come
from the [Razorpay](https://dashboard.razorpay.com) dashboard with no paperwork.
For the webhook, put the same value in `RAZORPAY_WEBHOOK_SECRET` and on the
webhook itself, pointed at `/api/v1/pay/webhook/razorpay` and subscribed to
`payment.captured` and `order.paid`. Without a public address to reach it on,
the patient's own browser still reports the payment and the bill still settles;
the webhook is what covers a patient who pays and closes the tab.

### Platform administration

Clinics register themselves, but a platform administrator can only be made
from the server. The account belongs to no clinic and cannot open any clinic's
records; it signs in at the same page and lands on `/admin`.

```
cd backend && python -m app.platform_admin --email you@example.org --first Asha --last Rao
```

The password is asked for twice, or read from `PLATFORM_ADMIN_PASSWORD` where
nobody is there to type it.

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
log, so the API's output has to go to a file the suite is told about. It makes
its own platform administrator with the command above, run from `backend/`
with `python` (or whatever `E2E_PYTHON` names), against the same database.

The online payment tests drive the real order call, both signature checks and
the webhook, but not Razorpay's own checkout window, which belongs to somebody
else. They run against the stand-in in `scripts/dev/fake_gateway.py`, so the
API and the suite both need pointing at it and both need the same key values.

```
python scripts/dev/fake_gateway.py --port 8081
cd backend && RAZORPAY_KEY_ID=rzp_test_local RAZORPAY_KEY_SECRET=local-secret \
  RAZORPAY_WEBHOOK_SECRET=local-webhook RAZORPAY_API_URL=http://127.0.0.1:8081 \
  python -m uvicorn app.main:app --port 8000 > api.log 2>&1
cd frontend && npx playwright install chromium   # once
E2E_API_LOG=../backend/api.log RAZORPAY_KEY_SECRET=local-secret \
  RAZORPAY_WEBHOOK_SECRET=local-webhook RAZORPAY_API_URL=http://127.0.0.1:8081 \
  npm run e2e
```

## Status

Running at [opdmanager.vercel.app](https://opdmanager.vercel.app), as a single Vercel project: the web app and the API are two services of it, with everything under `/api` sent to the API. Online payments are still on Razorpay's test keys. Architecture and conventions are documented in [`docs/`](docs/).

## Credits

The medicine list doctors pick from is India's National List of Essential Medicines 2022, published by the Ministry of Health and Family Welfare. Printed prescriptions are set in IBM Plex, used under the SIL Open Font License, which ships with the fonts in `backend/app/assets/fonts`.

## A note on the data

Everything in this repository — seeds, fixtures, tests, screenshots — uses synthetic data. No real patient information is used anywhere, and this build has not been assessed against any healthcare regulation. It is not certified for clinical use.

## Licence

MIT © Yash Seth
