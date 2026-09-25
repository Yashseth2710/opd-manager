# Security model

What this system defends against, and how. Two things matter more than anything else here: a clinic must never see another clinic's data, and a user must never perform an action their role does not allow.

Both are enforced on the server. The frontend hides what a user cannot do as a courtesy, not as a control.

## Authentication

**Passwords** — Argon2id, per-password salt, parameters tuned so hashing costs roughly 250ms on the deployment target. Minimum 8 characters, checked against a list of common passwords. No composition rules; length beats forced punctuation.

**Tokens** — a 15-minute JWT access token and a 7-day opaque refresh token, both in `httpOnly`, `Secure`, `SameSite=Lax` cookies. JavaScript cannot read either, so an XSS bug does not hand over a session.

**Refresh rotation** — every refresh issues a new token and invalidates the old one. Presenting an already-used token invalidates the entire family and forces re-authentication, because the only way that happens is a stolen token being replayed.

**Lockout** — after 5 failed attempts an account locks for 15 minutes, counted per account and per IP. Login responses are identical for an unknown email and a wrong password, and both take the same time.

**Reset tokens** — single-use, 30-minute expiry, stored hashed. Requesting a reset for an address that does not exist returns the same response as one that does.

**Email** — the provider sits behind one interface and is chosen by whichever key is configured. With none set, links are written to the server log and accounts are created already confirmed, so the application stays usable rather than reporting deliveries that never happened. The response to a reset request is identical in every case and never carries the link: returning it would tell the caller which addresses have accounts.

## Authorisation

Permissions are strings shaped `resource:action`, checked by a FastAPI dependency:

```python
@router.post("/patients", dependencies=[Depends(require("patient:create"))])
```

The check reads the permission set from the verified access token. It is impossible to register a route that touches tenant data without going through a dependency that resolves the caller.

### Role and permission matrix

`✓` granted, `—` denied, `own` limited to the user's own records.

| Permission | Super admin | Clinic admin | Doctor | Receptionist | Staff |
|---|:--:|:--:|:--:|:--:|:--:|
| `patient:create` | — | ✓ | ✓ | ✓ | config |
| `patient:read` | — | ✓ | ✓ | ✓ | config |
| `patient:update` | — | ✓ | ✓ | ✓ | config |
| `patient:archive` | — | ✓ | — | — | — |
| `appointment:create` | — | ✓ | own | ✓ | config |
| `appointment:read` | — | ✓ | own | ✓ | config |
| `appointment:update` | — | ✓ | own | ✓ | config |
| `appointment:cancel` | — | ✓ | own | ✓ | — |
| `queue:checkin` | — | ✓ | — | ✓ | config |
| `queue:manage` | — | ✓ | own | ✓ | — |
| `consultation:create` | — | — | ✓ | — | — |
| `consultation:read` | — | ✓ | ✓ | — | — |
| `consultation:update` | — | — | own | — | — |
| `prescription:create` | — | — | ✓ | — | — |
| `prescription:read` | — | ✓ | ✓ | ✓ | — |
| `vitals:record` | — | ✓ | ✓ | ✓ | — |
| `vitals:read` | — | ✓ | ✓ | ✓ | ✓ |
| `lab:read` | — | ✓ | ✓ | ✓ | config |
| `lab:create` | — | — | ✓ | — | — |
| `lab:update` | — | ✓ | own | ✓ | config |
| `document:upload` | — | ✓ | ✓ | ✓ | config |
| `document:read` | — | ✓ | ✓ | ✓ | config |
| `billing:create` | — | ✓ | — | ✓ | config |
| `billing:read` | — | ✓ | — | ✓ | config |
| `billing:update` | — | ✓ | — | ✓ | — |
| `payment:record` | — | ✓ | — | ✓ | config |
| `reports:read` | — | ✓ | own | — | — |
| `doctor:manage` | — | ✓ | — | — | — |
| `staff:manage` | — | ✓ | — | — | — |
| `settings:manage` | — | ✓ | — | — | — |
| `subscription:manage` | — | ✓ | — | — | — |
| `audit:read` | — | ✓ | — | — | — |
| `platform:*` | ✓ | — | — | — | — |

The boundaries that get tested explicitly:

- A receptionist cannot create a consultation or a prescription. Clinical documentation belongs to the clinician who is accountable for it.
- The desk types lab reports in, since that is where the paper arrives, but only the doctor who ordered a test marks its report as seen, and after that nobody changes it.
- A doctor cannot archive a patient, manage staff, or change clinic settings.
- Billing belongs to the desk and the clinic admin. A doctor has no route to bills, and the queue leaves them off for anyone who cannot read them. Money goes back only through the clinic admin, and a bill is voided only once nothing taken on it is still held.
- A file on the record is changed or removed only by whoever put it there or the clinic admin. Reading it needs `document:read`; the staff role has that and nothing more.
- A doctor reads and edits their own consultations. Another doctor's clinical notes are readable by the clinic admin, not laterally.
- A clinic admin has no platform permissions. A super admin has no clinical permissions.

`config` means the clinic admin decides for their own staff role.

### Super admin boundaries

Super admins administer the platform, not clinics. They can list organisations, see counts, suspend and reactivate, move a clinic between plans, change what a plan allows, and read platform metrics. They cannot read patients, consultations, prescriptions or clinical documents through any route.

That is held in three places rather than one. A platform account is made only from the server's command line, carries no organisation, and is given `platform:manage` and nothing else, so every clinic route refuses it before a query runs. The platform's routes check both the permission and the missing organisation, so a clinic role could not reach them even if one were somehow given the permission. And the queries behind the platform screens live in one repository that selects clinics, plans and counts, never a row a patient is on. The command refuses an address any account already uses, so signing in never has to choose between the platform and somebody's clinic.

Suspending a clinic is read from the clinic's row on every request, not from the token, so it takes effect on the next request rather than when the last token runs out. Every session its people hold is ended too, and signing in is refused until it is reactivated. Whatever the platform does to a clinic is written into that clinic's own audit log, with the reason and the name of whoever did it.

Support access to a clinic's data is not implemented. If it is added later it needs consent, a time limit, and an audit entry the clinic can see — so it is out of the initial build rather than approximated badly.

## Tenant isolation

The most important control in the system.

**The organisation comes from the token.** It is a signed claim, never a header, query parameter or body field. A request cannot ask to be treated as belonging to another clinic.

**Repositories scope automatically.** `TenantScopedRepository` applies `WHERE organization_id = :current_org` to every read, and stamps it on every write. Writing an unscoped query requires reaching for a differently-named base class reserved for platform administration.

**Cross-tenant reads return 404.** A 403 is an admission that the record exists. Given an ID, an attacker could map another clinic's patient volume from the difference between 403 and 404.

**The one unscoped lookup is the payment link**, because the patient opening it carries no token to take a clinic from. The row is found by the hash of the token and the clinic is read off the row; every query after that is scoped to it as usual. A token reaches exactly one bill at one clinic, and no part of the request can widen that.

**Row-level security** is planned for the hardening pass as defence in depth. The schema carries `organization_id` on every tenant table from the start so enabling it is configuration rather than redesign.

### Required tests

These ship with the tenancy work, not after it:

```
Clinic A user → GET /patients/{clinic B patient}     → 404
Clinic A user → PATCH /patients/{clinic B patient}   → 404
Clinic A user → POST /appointments {clinic B doctor} → 422
Receptionist  → POST /consultations                  → 403
Receptionist  → POST /prescriptions                  → 403
Doctor        → GET /platform/organizations          → 403
Doctor        → DELETE /staff/{id}                   → 403
Clinic admin  → GET /platform/metrics                → 403
Suspended org user → any request                     → 403
Staff         → POST /invoices/{id}/payment-link     → 403
No session    → GET /pay/{made-up token}             → 404
Checkout report signed with the wrong key            → 400
Webhook with a signature over different bytes        → 400
```

Every new tenant-owned resource adds its own row to this list.

## Input validation

Zod on the client for immediate feedback, Pydantic on the server as the control. Client validation is a convenience and is assumed to be absent.

Validated on every request: types, required fields, string bounds, enum membership, date sanity, phone and email format, positive monetary amounts, UUID format, and pagination limits with a hard ceiling so nobody can request a million rows.

SQL injection is structurally excluded — everything goes through SQLAlchemy with bound parameters. Raw SQL requires review and parameter binding.

## File uploads

The riskiest surface in the application.

- Extension checked against an allowlist: `pdf`, `jpg`, `jpeg`, `jfif`, `png`, `webp`, and `heic` or `heif` only so they can be refused with a reason.
- Content type determined by reading magic bytes: a PDF, or a JPEG, PNG or WebP image. The client's `Content-Type` is recorded and ignored, and the file is always served back with the type its bytes gave and `nosniff`.
- HEIC is refused even though it is a real image. No browser but Safari can show it, and a record nobody at the desk can open is not a record.
- Size capped at 4 MB per file, because a Vercel function refuses a larger body before the API sees it. The body is read no further than the limit. The web app makes a large photo smaller before sending it; a PDF it cannot, so one over the limit is refused with what to do instead. Files count against the clinic's plan by their size, and one that would take it past its allowance is refused before it is stored.
- Stored filenames are generated. The original is kept as metadata and never used as a path.
- Upload requires `document:upload` **and** the target patient must resolve inside the caller's organisation. A visit or a lab order named alongside it must be that patient's.
- Files live in a private Vercel Blob store, which answers nobody without the store's token. The API fetches the file for a caller it has checked and sends it on; the store's address never reaches the browser, and no blob is listable.
- Only whoever uploaded a file, or the clinic admin, can rename, refile or remove it. Removing deletes the file from the store before the caller is told it is gone.
- SVG is not accepted. SVG is executable.

## Taking money online

The patient paying a bill has no account, so the link is the credential.

- The token is 32 random bytes, hashed with SHA-256 before it is stored. Only the hash is kept, so a dump of the table opens nothing. It is why the desk sees an address once, at the moment it is raised, and raises a fresh one rather than reading the old one back.
- A link reaches one bill, expires after three days, and can be called off from the desk. One open link per bill by unique index, so there is never a second address in circulation.
- What the link shows is the clinic, the bill number, the amount, and the name on the bill. No phone number, no address, nothing clinical. A forwarded link leaks no more than the paper bill it replaces.
- **Nothing the browser says is taken as payment.** The checkout's handshake is signed with the API secret, which refuses a forged one, but it only proves the report came from the checkout. The gateway is asked what it did with the payment before a rupee is recorded, and a payment that names an order other than this link's is refused.
- The webhook is verified with HMAC-SHA256 over the exact bytes Razorpay sent, against a secret shared only with their dashboard. The handler reads the raw body for that reason: verifying a parsed and re-encoded copy would accept a body that had been altered. With no webhook secret set, webhooks are refused rather than trusted.
- The gateway's payment id is the idempotency key, so the browser and the webhook reporting the same payment write one row between them, settled by a unique index rather than by timing.
- Card details never reach this application or the clinic. The checkout collects them on Razorpay's own page; what comes back is an identifier.
- Keys are split the way they are meant to be: the key id is public and goes to the browser, the secret and the webhook secret stay on the server and are never returned by any endpoint.

## Reports and the day book

Reports read across bills, visits and lab orders at once, which means the queries reach several tables rather than one. They do not go through the tenant-scoped repository base that makes forgetting the organisation impossible, so every query in `repositories/reports.py` filters on it by hand and the tests check that a second clinic's figures come back at nil. A doctor's report is narrowed to the doctor profile linked to their account, the same narrowing the day's queue uses; an account with no profile gets an empty report rather than the clinic's.

The day book is a CSV, and a CSV is a program as far as Excel and Sheets are concerned. A cell beginning with `=`, `+`, `-` or `@` is written with a leading apostrophe, so a patient registered as `=cmd|'/c calc'!A0` opens as text. The file is sent as an attachment with `Cache-Control: private, no-store`, and it carries only the clinic's own payments — names, bill numbers and amounts, no clinical detail.

The stretch asked for is capped at a year. Left open, a request for a decade would be a cheap way to make the database do expensive work from a single session.

## Search

The search box reaches five kinds of record from one route, so it is gated kind by kind rather than as a whole: each is searched only when the caller holds the permission that kind's own pages need, and never lists a record whose page would refuse them. Every query goes through a repository scoped to the caller's clinic, and a doctor's bookings are narrowed to their own list exactly as the appointments page narrows them. Typed text is escaped before it reaches `LIKE`, so `%` and `_` match only themselves.

The browser keeps the last few records somebody opened from the box, by name, so they are one keystroke away next time. Clinic computers are shared, so the list is kept per account, holds names and nothing clinical, and is cleared on signing out.

## Rate limiting

Redis-backed, since serverless instances share nothing in memory.

| Endpoint | Limit |
|---|---|
| Login | 5 per 15 min per IP and per account |
| Password reset request | 3 per hour per address |
| Registration | 3 per hour per IP |
| Search | 30 per minute per user |
| File upload | 60 per hour per user |
| Opening or paying a bill from a link | 120 per hour per IP |
| General API | 300 per minute per user |

Exceeding a limit returns `429` with `Retry-After`.

## Secrets and configuration

- Nothing secret is committed. `.env` is ignored; `.env.example` carries keys with empty values.
- Secrets live in Vercel environment variables, separated by environment.
- Only `NEXT_PUBLIC_`-prefixed variables reach the browser, and nothing sensitive is ever given that prefix.
- Preview deployments use a separate database with synthetic data. Production data is never reachable from a preview.
- The repository is public, so any secret that lands in history is permanently compromised — rotation is the response, not a force push.

## Headers and transport

HTTPS everywhere, HSTS, and a Content-Security-Policy without `unsafe-eval`. `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: strict-origin-when-cross-origin`, and a restrictive `Permissions-Policy`.

Cookies are `SameSite=Lax`, which stops cross-site form posts from carrying credentials. State-changing requests additionally require an `Origin` matching the deployment.

## Error handling and logging

Users see a mapped message and a request ID. They never see a stack trace, a SQL fragment, a table name, a file path or a library version. Sentry receives the detail.

**Never logged** — passwords, tokens, cookies, reset codes, API keys, or the content of a medical record. A patient's identifier is loggable; their diagnosis is not.

Analytics events record that a consultation was completed, never what it contained.

## Audit trail

Append-only. Recorded for patients, their allergies and documents; appointments and check-ins; consultations, prescriptions, vital signs and lab orders; bills, payments, refunds and payment links; doctors, their hours and leave; staff, invitations and role changes; clinic details and settings; and sign-in failures and lockouts. Reading a record is not recorded.

Each entry holds actor, action, resource, what changed, timestamp, IP and user agent. Actor name is denormalised so the log stays readable after an account is suspended. An entry is written in the same transaction as the change it describes, so a change that fails leaves no entry behind and an entry never describes a change that did not happen.

The application has no path that updates or deletes an entry, and the database refuses to as well: a trigger on `audit_logs` rejects every `UPDATE`, and every `DELETE` except the one that cascades from the clinic itself being removed. The trigger holds whichever role connects, which a grant on the API's role would not.

A failed sign-in ends in an error, which rolls the request back, so the attempt and the lockout are written in a transaction of their own. They are recorded only against an account that exists, in that account's clinic; an address with no account behind it writes nothing, so the log cannot be used to learn which addresses are real. The IP address is the first hop in `X-Forwarded-For`, which the caller can set, and is kept as a lead rather than as proof.

Payment links are working credentials and are never written into the log; the entry for one records the amount and where it was emailed.

## Notifications

A notice belongs to one account and is read only by it. The list, the count and marking read are all filtered to the caller's own account and clinic, and someone else's notice reads as `404`. Recipients are worked out from the change itself and then filtered again to active accounts at the same clinic, so a suspended account or one elsewhere receives nothing whatever the rule produced.

Email is off by default and turned on per person, per kind. An emailed notice carries what the notice says, which can include a patient's name and the name of a test, which is why nobody receives one without asking. It is sent only after the transaction commits, so a request that fails sends nothing, and a provider that is down costs the email and not the request.

## What this build does not claim

This is a portfolio MVP running on free infrastructure with synthetic data.

Online payment runs on Razorpay's test keys. No real money moves, and nothing here has been through the verification a live account needs. Card details never touch this application, which keeps it out of PCI scope, but that is a consequence of using a hosted checkout rather than a claim about anything this build has been assessed for.

It has not been assessed against the DPDP Act, HIPAA, GDPR or any other regime. There is no encryption at rest beyond what Neon provides by default, no key management, no documented retention or deletion policy, no backup and restore procedure, no disaster recovery plan, no penetration test, and no signed processing agreements with any subprocessor.

Real patient data does not belong in this deployment. Putting it here would be a legal problem before it was a technical one.
