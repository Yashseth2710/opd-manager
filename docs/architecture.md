# Architecture

How OPD Manager is put together, and why. This is the reference for the decisions that are expensive to change later.

## The shape of the system

```
                    Browser
                       │
                       ▼
              ┌────────────────┐
              │     Vercel     │
              │                │
              │  Next.js  ──▶  │  /           pages, server components
              │  FastAPI  ──▶  │  /api/v1/*   JSON API
              └────────┬───────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
  Neon Postgres  Upstash Redis   Vercel Blob
  system of      tokens, rate    documents,
  record         limits, queue   PDFs, logos
                 counters
```

One Vercel project. The Next.js app is the deployment root; the Python API ships alongside it as a serverless function.

## Repository layout

```
opd-manager/
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── (auth)/         login, register, password reset, verify
│   │   │   ├── (app)/          the authenticated shell
│   │   │   │   ├── dashboard/  patients/      appointments/
│   │   │   │   ├── queue/      consultations/ prescriptions/
│   │   │   │   ├── billing/    reports/       doctors/
│   │   │   │   └── staff/      notifications/ settings/
│   │   │   ├── (platform)/admin/   platform administration
│   │   │   ├── onboarding/     redirects to settings
│   │   │   └── layout.tsx      providers.tsx   globals.css
│   │   ├── components/
│   │   │   ├── ui/             library primitives, restyled to our tokens
│   │   │   ├── auth/           forms and the pieces they share
│   │   │   ├── layout/         the rail, the page frame, permission gates
│   │   │   ├── common/         empty states, skeletons, confirmations
│   │   │   └── <feature>/      dashboard, patients, appointments, queue
│   │   ├── services/           one module per resource; owns query keys
│   │   ├── lib/                api client, auth calls, utils, format/
│   │   ├── hooks/   schemas/   types/
│   │   └── proxy.ts            redirects by session, not authorisation
│   └── package.json   next.config.ts   tsconfig.json
│
├── backend/
│   ├── app/
│   │   ├── core/               config, security, permissions, exceptions,
│   │   │                       email, redis, rate limits
│   │   ├── db/                 session, base, mixins
│   │   ├── models/             SQLAlchemy models
│   │   ├── schemas/            Pydantic request and response models
│   │   ├── repositories/       queries, tenant-scoped
│   │   ├── services/           business rules
│   │   ├── api/
│   │   │   ├── deps.py         caller resolution and permission gates
│   │   │   └── v1/endpoints/   one module per resource
│   │   ├── middleware/   utils/
│   │   └── main.py
│   ├── alembic/versions/
│   ├── tests/                  api/  services/
│   └── requirements.txt   pyproject.toml   alembic.ini
│
├── scripts/checks/             the guards CI runs
├── docs/
└── vercel.json
```

Each half owns its own manifests and is installed and run on its own. Vercel
builds them as two services from one repository, and routes `/api/*` to the
Python service and everything else to Next.

The frontend and backend live in one repository because they ship as one
deployment and share a single set of environment variables. They do not share
code.

**Where a new file goes.** A screen is a route folder under `(app)`. Anything it
renders that is specific to that feature is a component in the matching
`components/<feature>/` folder; anything two features both need moves to
`components/common/`. Talking to the API is a function in `services/`, never a
`fetch` inside a component. On the backend, a route parses and delegates, a
service decides, a repository queries.

Directories carry a `.gitkeep` describing what belongs in them until they hold
real files. Git cannot track an empty folder, and a structure nobody can see is
a structure nobody follows.

### How FastAPI runs on Vercel

`api/index.py` is a thin file that imports the assembled app:

```python
from backend.main import app
```

Vercel's Python runtime serves ASGI applications directly, so no adapter is needed. `vercel.json` rewrites `/api/v1/*` to that function and leaves everything else to Next.js.

This means the backend runs as a **serverless function**, not a long-lived process. Three consequences shape every backend decision:

- **No in-process state.** No module-level caches, no background threads, no in-memory rate limiters. Anything that must survive between requests goes to Redis or Postgres.
- **Cold starts are real.** Import cost matters. Heavy imports stay inside the functions that need them.
- **Requests are short.** Anything slow — PDF generation for a large batch, report exports — is chunked or moved to a scheduled job.

## Data access

### Connections

Neon is reached through its **pooled** endpoint. A serverless function can be instantiated hundreds of times concurrently, and direct Postgres connections would exhaust the server's connection limit almost immediately. PgBouncer in front absorbs that.

Two details follow from pooling in transaction mode, and both are easy to get wrong:

- SQLAlchemy uses `NullPool`. Client-side pooling is pointless when the process dies after the request, and actively harmful when PgBouncer is already pooling.
- asyncpg is configured with `statement_cache_size=0`. Transaction-mode pooling does not guarantee the same backend across statements, so prepared statement caching breaks.

Alembic connects to the **direct** (unpooled) endpoint instead. Migrations need a stable session and DDL locks.

### Async throughout

FastAPI async routes, SQLAlchemy 2.x async session, asyncpg driver. Mixing sync database calls into async request handlers blocks the event loop, so the sync path is not used at all.

### Repositories and services

```
router  →  service  →  repository  →  database
```

- **Routers** parse input, resolve the caller, call one service, shape the response. No business logic, no queries.
- **Services** own the rules — what a valid appointment is, how an invoice total is derived, which queue transitions are legal. This is where the tests that matter point.
- **Repositories** own queries. Every repository over a tenant-owned table inherits from a base that applies the tenant filter automatically.

The point of the split is that tenant isolation and permission checks live in two known places rather than scattered across route handlers.

## Multi-tenancy

Every tenant-owned table carries `organization_id`, indexed, and usually as the leading column of a composite index.

Isolation is enforced in three layers:

1. **The token.** The caller's organisation is a claim in their access token, not a value they can pass in a request.
2. **The repository.** `TenantScopedRepository` injects `WHERE organization_id = :current_org` into every read and write. Building a query that skips it requires deliberately reaching for the unscoped base class, which exists only for platform administration and is named to make that obvious.
3. **Postgres row-level security.** Deferred to the security hardening pass, but the schema is designed for it from the start so it can be switched on without a rewrite.

A user who asks for another clinic's patient gets **404**, not 403. A 403 confirms the record exists, which leaks the existence of another clinic's data.

## Authentication

Stateless access tokens, stateful refresh tokens.

- **Access token** — JWT, 15 minutes, carries `sub`, `organization_id`, `role`, `permissions`. Verified with a signature check, so the common path touches no database.
- **Refresh token** — opaque, 7 days, stored hashed in Redis, rotated on every use. Reuse of an already-rotated token invalidates the whole family, which is what a stolen-token replay looks like.
- Both are `httpOnly`, `Secure`, `SameSite=Lax` cookies. Tokens never reach JavaScript, which takes XSS-driven token theft off the table.
- Passwords hashed with Argon2id.

Session state in Redis rather than JWT-only exists so that suspending a clinic or removing a staff member takes effect within the access token's lifetime rather than never.

## Identifiers

Two kinds, for two audiences.

**UUIDv7** is the primary key on every table. Time-ordered, so it indexes like a sequential key without leaking row counts the way an auto-increment integer does. This is what appears in URLs and API payloads.

**Display codes** are what humans read and say out loud: `PT-000001`, `INV-000124`, token `24`. They are per-clinic, so two clinics both having a `PT-000001` is expected and correct. They are generated by an atomic increment against a counters table:

```sql
UPDATE tenant_counters
   SET value = value + 1
 WHERE organization_id = :org AND counter = 'patient'
RETURNING value;
```

One statement, row-locked, safe under concurrency. Postgres sequences were rejected because they would mean one sequence per clinic per counter.

## Money

Never a float. `NUMERIC(12,2)` in Postgres, `Decimal` in Python, and **strings** on the wire — JSON numbers go through IEEE 754 doubles in JavaScript, and `0.1 + 0.2` is the wrong answer to give someone about their bill.

The frontend formats with `Intl.NumberFormat` and does no arithmetic on money. Totals come from the server.

Default currency is INR, but it is a column on the organisation, not a constant.

## Time

- Stored as `TIMESTAMPTZ`, always UTC.
- Each clinic has an IANA timezone (`Asia/Kolkata` by default).
- Conversion happens at the edges: the API accepts and returns ISO-8601 with offset; the UI renders in the clinic's timezone.
- Appointment slot arithmetic runs in clinic-local time, because "Monday 09:00–13:00" is a local concept and DST shifts would otherwise silently move a clinic's working hours.

A recurring class of bug in scheduling software is comparing a local wall-clock time to a UTC instant. The models keep working hours as local time-of-day and materialise real instants only when a slot is booked.

## Caching and Redis

Redis earns its place in three narrow cases and is not used as a general cache:

| Use | Why |
|---|---|
| Refresh token families | Needs revocation, so it cannot be stateless |
| Rate limiting | Needs a counter shared across function instances |
| Idempotency keys | Prevents duplicate invoices and payments on retry |

Everything else is served from Postgres with proper indexes, or cached client-side by TanStack Query. Adding a cache layer in front of a query that has not been proven slow is how stale data bugs get written.

## The queue feels live without WebSockets

Serverless functions cannot hold persistent connections, so V1 polls:

- TanStack Query refetches the active queue every 5 seconds while the tab is focused
- Polling pauses when the tab is hidden and resumes on focus, except on the waiting-room screen, which nobody watches from a keyboard
- Every action asks for the line again as soon as it lands, since one step reorders everybody behind it
- The queue read is three queries whatever the size of the day, so the poll stays cheap

In practice a five-second lag on a waiting room screen is imperceptible. If it stops being enough, the queue read is already isolated behind one endpoint and one hook, so swapping in a realtime transport is a contained change.

## Scheduled work

Vercel Cron on the Hobby plan allows **two jobs, running at most once a day**. That is not enough for appointment reminders, which need to fire in the hour before a slot.

The plan:

- **Vercel Cron, daily** — overnight maintenance: expiring stale check-ins, rolling up yesterday's analytics, cleaning orphaned blobs.
- **GitHub Actions on a schedule** — calls a protected endpoint every 15 minutes to dispatch due reminders. Free for public repositories, and reminders are not so time-critical that Actions' scheduling jitter matters.
- The endpoint is authenticated with a shared secret and is idempotent, so a double-fire sends nothing twice.

This is a free-tier workaround and is written down as one. On a paid plan it collapses back to a single Vercel cron.

## Frontend data flow

- **Server Components** render shells, navigation and anything static.
- **TanStack Query** owns all server state — every list, detail view and mutation. No server data in React state or context.
- **React Hook Form + Zod** for forms; the same Zod schema validates the form and types the payload.
- Query keys are structured by feature and scoped by clinic, so switching context cannot show stale data from another clinic.

Pydantic mirrors every Zod schema on the backend. Client validation is for speed of feedback; the server's validation is the one that counts.

## Errors

One envelope, everywhere:

```json
{
  "success": false,
  "error": {
    "code": "PATIENT_NOT_FOUND",
    "message": "Patient could not be found."
  }
}
```

Codes are a closed set, defined in one module and mapped to user-facing copy on the frontend. Unhandled exceptions become `INTERNAL_ERROR` with a request ID and nothing else — no stack traces, no SQL, no table names.

## Build order

Dependencies first, and each step leaves the app working:

```
foundation → auth → onboarding → tenancy & roles → shell → dashboard
   → patients → doctors & staff → appointments → queue → consultation
   → prescriptions → labs & documents → billing → follow-ups
   → reports → hardening → subscriptions → platform admin
   → assisted documentation → polish → performance → tests → deploy → docs
```

Analytics cannot be built before there is data to analyse, billing needs appointments, prescriptions need consultations. The order is not a preference.

## Decisions worth recording

| Decision | Alternative rejected | Why |
|---|---|---|
| One repository, one Vercel project | Separate frontend and backend deployments | One set of env vars, one preview URL per PR, no CORS |
| JWT access + Redis refresh | Pure server sessions | A Redis round trip on every request is real latency on serverless |
| 404 for cross-tenant reads | 403 | 403 confirms the record exists |
| UUIDv7 keys, separate display codes | Sequential integers everywhere | Enumerable IDs leak volume and invite scraping |
| Polling for the queue | WebSockets | Serverless cannot hold connections; five seconds is imperceptible |
| Decimal as string over the wire | JSON numbers | JavaScript cannot represent `0.1 + 0.2` correctly |
| Application-level tenant filtering first, RLS later | RLS from day one | RLS through a transaction pooler needs care; the schema is designed to accept it |
| No Celery | Celery + a worker | Nothing here needs a long-running queue, and a worker breaks the free deployment |
