# API conventions

Every endpoint under `/api/v1/`. The version is in the path so a breaking change can ship alongside the old shape rather than forcing every client to move at once.

## Responses

Success wraps the payload:

```json
{ "success": true, "data": { ... } }
```

Lists carry pagination alongside:

```json
{
  "success": true,
  "data": [ ... ],
  "meta": { "page": 1, "per_page": 25, "total": 348, "total_pages": 14 }
}
```

Failure is always the same shape:

```json
{
  "success": false,
  "error": {
    "code": "PATIENT_NOT_FOUND",
    "message": "Patient could not be found."
  }
}
```

Validation failures add per-field detail:

```json
{
  "success": false,
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Some fields need attention.",
    "fields": {
      "phone": "Enter a valid 10-digit phone number.",
      "date_of_birth": "Date of birth cannot be in the future."
    }
  }
}
```

The frontend maps `code` to its own copy. `message` is a readable fallback, not the source of truth for what the user sees.

## Status codes

| Code | Used for |
|---|---|
| 200 | Successful read or update |
| 201 | Resource created |
| 204 | Successful delete or archive with no body |
| 400 | Malformed request |
| 401 | Missing or expired credentials |
| 403 | Authenticated, but not permitted |
| 404 | Not found, **or** exists in another clinic |
| 409 | Conflict — double booking, duplicate number |
| 422 | Validation failed |
| 429 | Rate limited |
| 500 | Unhandled fault |

403 and 404 carry weight. A permission failure inside the caller's own clinic is 403. Anything belonging to another clinic is 404, because 403 would confirm it exists.

## Error codes

Grouped by prefix, defined in one module, never invented at a call site.

```
AUTH_*        INVALID_CREDENTIALS, TOKEN_EXPIRED, ACCOUNT_LOCKED,
              EMAIL_NOT_VERIFIED, SESSION_EXPIRED
PERM_*        INSUFFICIENT_PERMISSIONS, ROLE_REQUIRED
PATIENT_*     NOT_FOUND, DUPLICATE_SUSPECTED, ARCHIVED
DOCTOR_*      NOT_FOUND, INACTIVE
              REGISTRATION_NUMBER_TAKEN, ACCOUNT_ALREADY_LINKED
APPT_*        NOT_FOUND, SLOT_UNAVAILABLE, OUTSIDE_WORKING_HOURS,
              DOCTOR_ON_LEAVE, PAST_DATE, INVALID_TRANSITION
QUEUE_*       NOT_FOUND, ALREADY_CHECKED_IN, INVALID_TRANSITION
CONSULT_*     NOT_FOUND, ALREADY_COMPLETED, NOT_OWNER
BILLING_*     INVOICE_NOT_FOUND, ALREADY_PAID, INVALID_TOTAL,
              PAYMENT_EXCEEDS_BALANCE, INVOICE_VOIDED
FILE_*        TOO_LARGE, UNSUPPORTED_TYPE, UPLOAD_FAILED
PLAN_*        LIMIT_REACHED, FEATURE_NOT_AVAILABLE
VALIDATION_ERROR, RATE_LIMITED, INTERNAL_ERROR
```

## Naming

Plural nouns, no verbs in paths, hyphens for multi-word segments, `snake_case` in JSON bodies to match Python.

`/clinic` is the one singular exception. A caller only ever has one, and it is decided by their session rather than named in the path, so `/organizations/current` would be a longer way of saying the same thing. The two invitation routes carry no session at all: whoever follows the link has no account yet, and the token stands in for one.

```
GET    /api/v1/patients
POST   /api/v1/patients
GET    /api/v1/patients/{id}
PATCH  /api/v1/patients/{id}
POST   /api/v1/patients/{id}/archive
GET    /api/v1/patients/{id}/timeline
```

Actions that are not CRUD become a sub-resource: `POST /appointments/{id}/check-in`, `POST /queue/{id}/call`, `POST /invoices/{id}/void`. `PATCH` for partial updates; `PUT` is not used.

## Surface

```
auth          POST   /auth/register
              POST   /auth/login
              POST   /auth/logout
              POST   /auth/refresh
              GET    /auth/me
              POST   /auth/forgot-password
              POST   /auth/reset-password
              POST   /auth/verify-email

clinic        GET    /clinic
              PATCH  /clinic
              GET    /clinic/settings
              PATCH  /clinic/settings
              POST   /clinic/complete-setup
              GET    /clinic/roles

staff         GET    /staff
              PATCH  /staff/{id}/role
              POST   /staff/{id}/suspend
              POST   /staff/{id}/restore
              GET    /staff/invitations
              POST   /staff/invitations
              DELETE /staff/invitations/{id}
              GET    /invitations/{token}
              POST   /invitations/accept

patients      GET    /patients
              POST   /patients
              POST   /patients/check-duplicates
              GET    /patients/{id}
              PATCH  /patients/{id}
              POST   /patients/{id}/archive
              POST   /patients/{id}/restore
              POST   /patients/{id}/allergies
              DELETE /patients/{id}/allergies/{allergy_id}
              GET    /patients/{id}/timeline
              GET    /patients/{id}/documents
              POST   /patients/{id}/documents

doctors       GET    /doctors
              GET    /doctors/specialities?status=
              POST   /doctors
              GET    /doctors/{id}
              PATCH  /doctors/{id}
              POST   /doctors/{id}/deactivate
              POST   /doctors/{id}/restore
              GET    /doctors/{id}/schedule
              PUT    /doctors/{id}/schedule
              GET    /doctors/{id}/availability?date=
              POST   /doctors/{id}/leaves
              DELETE /doctors/{id}/leaves/{leave_id}

staff         GET    /staff
              POST   /staff
              PATCH  /staff/{id}

appointments  GET    /appointments
              POST   /appointments
              GET    /appointments/{id}
              PATCH  /appointments/{id}
              POST   /appointments/{id}/confirm
              POST   /appointments/{id}/cancel
              POST   /appointments/{id}/check-in
              POST   /appointments/{id}/no-show

queue         GET    /queue
              POST   /queue/walk-in
              POST   /queue/{id}/call
              POST   /queue/{id}/skip
              POST   /queue/{id}/recall
              POST   /queue/{id}/complete

consultations GET    /consultations
              POST   /consultations
              GET    /consultations/{id}
              PATCH  /consultations/{id}
              POST   /consultations/{id}/complete
              GET    /consultation-templates
              POST   /consultation-templates

prescriptions POST   /prescriptions
              GET    /prescriptions/{id}
              GET    /prescriptions/{id}/pdf

labs          POST   /lab-orders
              GET    /lab-orders
              PATCH  /lab-orders/{id}
              POST   /lab-orders/{id}/result

billing       GET    /invoices
              POST   /invoices
              GET    /invoices/{id}
              PATCH  /invoices/{id}
              POST   /invoices/{id}/void
              GET    /invoices/{id}/pdf
              POST   /invoices/{id}/payments

reports       GET    /reports/revenue
              GET    /reports/patients
              GET    /reports/appointments
              GET    /reports/doctors
              GET    /reports/{name}/export

misc          GET    /search?q=
              GET    /notifications
              POST   /notifications/read-all
              GET    /audit-logs
              GET    /dashboard/summary
              GET    /subscription
              GET    /health

platform      GET    /platform/metrics
              GET    /platform/organizations
              POST   /platform/organizations/{id}/suspend
              GET    /platform/plans
```

## Lists

Standard query parameters across every collection:

```
?page=1&per_page=25&sort=-created_at&q=sharma&status=active
```

`per_page` defaults to 25 and is capped at 100. The response carries `total` and `pages` alongside the page itself, so a client can render "26–50 of 312" without a second request. `sort` takes a field name with an optional `-` for descending, validated against an allowlist so it cannot be used to probe the schema. Filters are endpoint-specific and documented in the OpenAPI schema.

`/patients` and `/doctors` are the exceptions that take no `sort`. Its order is decided by whether there is a search term: results come back closest-match first, and an unsearched list comes back most recently registered first. A `sort` that overrode either would only ever make the list less useful.

`/doctors` orders by status, then surname. A clinic has tens of doctors rather than thousands, so the useful question is who is practising and where they are in the list, not which of them was added most recently.

Search is debounced at 300ms client-side and always executed server-side. No endpoint returns an unbounded collection.

`GET /doctors/specialities` is the one collection with no paging, because it returns the distinct specialities a single clinic offers and that is a list of a dozen at most. It exists so the filter on the list is built from what a clinic actually does rather than from a fixed set every clinic has to pick the wrong answer from. It takes the same `status` as `/doctors` and defaults to the same value, so the two always agree — a clinic whose only orthopaedist has been stood down is not offering orthopaedics, and a filter that can only come back empty is worse than no filter.

## Dates and money

Timestamps are ISO-8601 with offset, in and out:

```json
{ "scheduled_start": "2026-09-16T09:30:00+05:30" }
```

Date-only fields are `YYYY-MM-DD`. Times of day, for schedules, are `HH:MM` and interpreted in the clinic's timezone.

`PUT /doctors/{id}/schedule` takes the whole week every time and replaces it, and an empty list clears it. Patching one block at a time would let two people editing the same day leave a doctor in two rooms at once; replacing the set inside one transaction is what makes the overlap check the truth rather than a guess. Field errors come back positioned against the submitted list — `blocks.1.start_time` — so a client can put the message on the block that caused it.

`GET /doctors/{id}/availability` works the day out from the rota each time, subtracting breaks and leave. Nothing is stored: a materialised slot table goes stale the moment a schedule changes, and that is a well-worn route to a double booking. With no `date` it answers for today at the clinic, not today on the server.

Money is a **string**:

```json
{ "subtotal": "1600.00", "tax_amount": "80.00", "total": "1680.00", "currency": "INR" }
```

JSON numbers become doubles in JavaScript, and a rounding error in a bill is not an acceptable class of bug. The client formats and never computes.

## Idempotency

Endpoints that create money or a queue position accept an `Idempotency-Key` header. The key is held in Redis for 24 hours against the response. A retry after a timeout returns the original result instead of creating a second invoice.

Applies to invoice creation, payment recording, check-in and walk-in registration.

## Authentication

Cookies, sent automatically. No `Authorization` header, so nothing needs to live in JavaScript.

On a 401 the client attempts one silent refresh, retries the original request once, and on a second failure routes to login with a message explaining the session ended.

## Documentation

FastAPI generates OpenAPI from the Pydantic models, so the schema cannot drift from the implementation. The interactive docs are available in development and preview, and disabled in production.
