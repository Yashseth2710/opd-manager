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
| 413 | Upload larger than the limit |
| 415 | Upload of a kind of file that is not accepted |
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
APPT_*        NOT_FOUND, SLOT_UNAVAILABLE, PATIENT_BUSY, OUTSIDE_WORKING_HOURS,
              DOCTOR_ON_LEAVE, PAST_DATE, INVALID_TRANSITION
QUEUE_*       NOT_FOUND, ALREADY_CHECKED_IN, HAS_APPOINTMENT, NOT_TODAY,
              INVALID_TRANSITION
CONSULT_*     NOT_FOUND, ALREADY_COMPLETED, NOT_OWNER, NOT_IN_ROOM,
              EDITED_ELSEWHERE, STILL_DRAFT
RX_*          NOT_FOUND, ALREADY_REPLACED, NOT_PRESCRIBER
VITALS_*      NOT_FOUND, ALREADY_TAKEN, LOCKED
LAB_*         NOT_FOUND, VISIT_CLOSED, ALREADY_ORDERED, NOT_ORDERER, LOCKED
DOC_*         NOT_FOUND, ALREADY_UPLOADED, NOT_UPLOADER
BILLING_*     INVOICE_NOT_FOUND, ALREADY_PAID, ALREADY_BILLED, INVALID_TOTAL,
              PAYMENT_EXCEEDS_BALANCE, REFUND_EXCEEDS_PAID, INVOICE_VOIDED,
              LOCKED, REFUNDED, HAS_PAYMENTS
PAYMENT_*     LINK_NOT_FOUND, LINK_CLOSED, LINK_NOTHING_OWED,
              CHECKOUT_REJECTED
PAYMENTS_*    NOT_CONFIGURED, GATEWAY_FAILED
FILE_*        TOO_LARGE, UNSUPPORTED_TYPE, UPLOAD_FAILED, UPLOAD_INTERRUPTED,
              MISSING
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
              GET    /patients/{id}/appointments
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

appointments  GET    /appointments?date=&doctor_id=
              POST   /appointments
              GET    /appointments/{id}
              PATCH  /appointments/{id}
              POST   /appointments/{id}/confirm
              POST   /appointments/{id}/cancel
              POST   /appointments/{id}/no-show
              POST   /appointments/{id}/check-in

queue         GET    /queue?doctor_id=
              POST   /queue/walk-in
              GET    /queue/{id}
              PATCH  /queue/{id}                     priority
              DELETE /queue/{id}                     undo a check-in
              POST   /queue/{id}/call
              POST   /queue/{id}/start
              POST   /queue/{id}/complete
              POST   /queue/{id}/skip
              POST   /queue/{id}/recall
              POST   /queue/{id}/no-show

consultations GET    /consultations
              POST   /consultations
              GET    /consultations/{id}
              PATCH  /consultations/{id}
              POST   /consultations/{id}/complete
              POST   /consultations/{id}/addenda
              GET    /consultation-templates
              POST   /consultation-templates

prescriptions GET    /prescriptions?patient_id=
              GET    /prescriptions/{id}
              GET    /prescriptions/{id}/pdf
              POST   /prescriptions/{id}/corrections
              GET    /medicines?q=

vitals        GET    /vitals?patient_id=  | ?queue_entry_id=
              POST   /vitals
              GET    /vitals/{id}
              PUT    /vitals/{id}
              DELETE /vitals/{id}

labs          GET    /lab-tests
              GET    /lab-orders?patient_id= | ?consultation_id= | ?show= | ?mine=
              POST   /lab-orders
              GET    /lab-orders/{id}
              DELETE /lab-orders/{id}
              POST   /lab-orders/{id}/cancel
              PUT    /lab-orders/{id}/result
              DELETE /lab-orders/{id}/result
              POST   /lab-orders/{id}/review

documents     GET    /patients/{id}/documents?category= | ?consultation_id= | ?lab_order_id=
              POST   /patients/{id}/documents?name=&category=
              GET    /documents/{id}
              GET    /documents/{id}/file
              PATCH  /documents/{id}
              DELETE /documents/{id}

billing       GET    /invoices?show= | ?patient_id= | ?q= | ?from=&to=
              GET    /invoices/summary?date=
              GET    /invoices/unbilled?date=
              GET    /invoices/start?queue_entry_id= | ?patient_id=
              GET    /invoices/lines?q=
              POST   /invoices
              GET    /invoices/{id}
              PATCH  /invoices/{id}
              DELETE /invoices/{id}
              POST   /invoices/{id}/issue
              POST   /invoices/{id}/void
              GET    /invoices/{id}/pdf
              POST   /invoices/{id}/payments
              POST   /invoices/{id}/refunds
              POST   /invoices/{id}/payment-link
              DELETE /invoices/{id}/payment-link

paying        GET    /pay/{token}
              POST   /pay/{token}/confirm
              POST   /pay/webhook/razorpay

reports       GET    /reports/summary
              GET    /reports/day-book.csv

misc          GET    /search?q=
              GET    /notifications?show=&before=
              GET    /notifications/unread
              POST   /notifications/{id}/read
              POST   /notifications/read-all
              GET    /notifications/preferences
              PUT    /notifications/preferences
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

`GET /search?q=` is the search box in the rail, and answers with up to five of each kind of record at once: `patients`, `appointments`, `bills`, `doctors` and `staff`. A kind is searched only when the caller holds the permission its own pages need (`patient:read`, `appointment:read`, `billing:read`, `doctor:read`, `staff:manage`), and `searched` lists the kinds that were, so an empty answer can say where it looked. Patients match the way the register matches them, misspelt names included, and a patient's bills and bookings are found through the same match. Bookings are the ones still ahead, from the start of the clinic's day, and a doctor only ever gets their own. Runs of spaces are squeezed, a term shorter than two characters finds nothing, and one longer than 100 is `422`. The box waits 160ms after the last key before asking, and nothing it reads is written to the audit log.

`GET /doctors/specialities` is the one collection with no paging, because it returns the distinct specialities a single clinic offers and that is a list of a dozen at most. It exists so the filter on the list is built from what a clinic actually does rather than from a fixed set every clinic has to pick the wrong answer from. It takes the same `status` as `/doctors` and defaults to the same value, so the two always agree — a clinic whose only orthopaedist has been stood down is not offering orthopaedics, and a filter that can only come back empty is worse than no filter.

## Dates and money

Timestamps are ISO-8601 with offset, in and out:

```json
{ "scheduled_start": "2026-09-16T09:30:00+05:30" }
```

Date-only fields are `YYYY-MM-DD`. Times of day, for schedules, are `HH:MM` and interpreted in the clinic's timezone.

`PUT /doctors/{id}/schedule` takes the whole week every time and replaces it, and an empty list clears it. Patching one block at a time would let two people editing the same day leave a doctor in two rooms at once; replacing the set inside one transaction is what makes the overlap check the truth rather than a guess. Field errors come back positioned against the submitted list — `blocks.1.start_time` — so a client can put the message on the block that caused it.

`GET /doctors/{id}/availability` works the day out from the rota each time, subtracting breaks and leave. Nothing is stored: a materialised slot table goes stale the moment a schedule changes, and that is a well-worn route to a double booking. With no `date` it answers for today at the clinic, not today on the server. Each slot carries a `state` of `free`, `booked` or `past`, where past means it has ended by the clinic's clock.

`POST /appointments` takes the clinic's `date` and a `start_time`, never an instant, and the time has to be the start of one of that day's free slots. The server works out the instant in the clinic's timezone and takes the end from the slot, so a browser in another timezone cannot book the wrong hour and a client cannot choose its own length. Refusals say why in the desk's words: `APPT_OUTSIDE_WORKING_HOURS`, `APPT_DOCTOR_ON_LEAVE` and `APPT_PAST_DATE` are 422s with the sentence on the field it concerns; a slot somebody else holds is `409 APPT_SLOT_UNAVAILABLE`; the same patient already booked across that time with anybody is `409 APPT_PATIENT_BUSY`. Two bookings landing on one slot at the same moment are settled by the database, and the loser gets the same 409.

`PATCH /appointments/{id}` moves an appointment, corrects its details, or both. A move puts a confirmed appointment back to `scheduled`, because the patient agreed to the old time. `GET /appointments` lists one day at the clinic, cancelled ones included, and flags any open booking the doctor's week no longer fits in `conflict` — leave taken since, hours changed, stood down. Nothing is moved automatically.

`POST /appointments/{id}/check-in` puts a booked patient in their doctor's queue for today and answers with the place, token included. Only today's appointments can be checked in (`422 QUEUE_NOT_TODAY` otherwise), and only open ones. A patient holds one live place at a time across every doctor, so checking somebody in twice, from two desks at once or into a second doctor's line, is `409 QUEUE_ALREADY_CHECKED_IN` with the token they already have. `POST /queue/walk-in` does the same without an appointment, and refuses with `409 QUEUE_HAS_APPOINTMENT` when the patient is booked with that doctor later today, since that booking is the one to check in. Both refuse a doctor who is on leave, stood down or has no clinic that day.

Tokens count from 1 per doctor per clinic day. The line is arrival order with urgent places first. `GET /queue` returns one lane per doctor: who is in the room, who has been called, who is waiting with a `position` and a rough `expected_wait_minutes`, who missed their call, who is booked and still to arrive, and who is done. The expected wait uses the doctor's appointment length until three consultations have finished that day, then the average of the last ten. A doctor has at most one patient called and one in the room, held by the database. Every step is written onto the appointment and its history, so the day's book and the queue agree. `DELETE /queue/{id}` takes back a check-in made by mistake, only before the patient has been called, and puts the appointment back as it stood.

`POST /consultations` opens the notes for a place in the queue whose patient is with the doctor, or already seen. Asking again hands back the same notes with a 200 rather than a 201, so two tabs land on one draft; a patient still waiting or called is `409 CONSULT_NOT_IN_ROOM`. The complaint starts as the reason the desk wrote down. Only the doctor the place belongs to opens, writes and finishes notes, which leaves the clinic admin reading them and nobody else: a doctor asking for a colleague's notes gets `403 CONSULT_NOT_OWNER` with whose they are, and the desk has no route to them at all.

`PATCH /consultations/{id}` changes only the sections it carries and must name the `version` it was written against. A save from an older copy is `409 CONSULT_EDITED_ELSEWHERE` and changes nothing, so a second tab cannot quietly undo the first. Diagnoses are sent as the whole list; one is the main one, the first if none is marked. A follow-up falls after the visit and within a year of it. `POST /consultations/{id}/complete` locks the notes, needs something written in them, and finishes the patient in the queue and on the book if they are still shown in the room. Finished notes are `409 CONSULT_ALREADY_COMPLETED` to any change; `POST /consultations/{id}/addenda` adds a dated, signed paragraph underneath instead, and a draft is `409 CONSULT_STILL_DRAFT` to that.

A prescription is written through the notes: `PATCH /consultations/{id}` carries `medicines`, the whole list of lines, and `prescription_instructions`, the advice printed on it. Lines can be saved without a dose while the doctor is still writing; finishing the visit issues the prescription with the clinic's next `RX-` number, and a line still without a dose stops it with `422` and the field that needs it. Drafts are never listed or printed. `GET /prescriptions/{id}/pdf` answers with the page itself, `application/pdf`, made fresh each time. `POST /prescriptions/{id}/corrections` issues a replacement with a new number and a reason, and marks the original replaced; only the doctor who wrote it may, which is `403 RX_NOT_PRESCRIBER` for anyone else, and a prescription already replaced is `409 RX_ALREADY_REPLACED` naming the newer one. Issued prescriptions are readable across the clinic by anyone holding `prescription:read`, because the desk prints them.

`GET /medicines?q=` offers what this clinic has prescribed before, most used first, then the published list, with tablets and capsules ahead of syrups and injections. It needs two characters, and a near miss still finds the medicine.

`POST /lab-orders` orders one test for a visit whose notes are still open, by the doctor writing them: another doctor's visit is `403 LAB_NOT_ORDERER`, a finished one `409 LAB_VISIT_CLOSED`. It takes a `test_code` from `GET /lab-tests`, or a `test_name` as typed; a typed name the list knows, `cbc` or `hemogram`, is the listed test. Each order takes the clinic's next `LAB-` number and, unless `instructions` is sent, the list's preparation, such as fasting. The same test twice on one visit is `409 LAB_ALREADY_ORDERED`, and thirty is the most one visit takes. `DELETE /lab-orders/{id}` takes a test back while the visit is open and nothing has come back; after that it is `POST /lab-orders/{id}/cancel` with a reason, by the doctor who ordered it or by whoever records results.

`PUT /lab-orders/{id}/result` is the whole report: the date printed on it, the lab, what it says in words, and each value with its unit and the range the lab printed. Sending it again corrects it, until the ordering doctor marks it seen with `POST /lab-orders/{id}/review`; after that it is `409 LAB_LOCKED`. `DELETE /lab-orders/{id}/result` takes a report typed against the wrong order back off. The report cannot be dated after today or before the test was ordered. Each value comes back with a `flag`, worked out on read: `high` or `low` for a number outside its range, with a value written as `<0.5` read as somewhere below half, and `abnormal` for a word that is not the one it should be, where `Nil`, `Negative` and `Not detected` count as the same. `GET /lab-orders/{id}` also carries the lines a report of that test usually has, with the ranges for the patient's sex filled in for adults and left to the lab's report for children, and each value's figure on the patient's last report of the same test, where it was measured in the same units.

Lab work is part of the patient's record, so anyone holding `lab:read` reads every patient's. A doctor acts only on their own orders: typing a report into a colleague's is `404 LAB_NOT_FOUND`, and marking it seen `403 LAB_NOT_ORDERER`. `GET /lab-orders?show=waiting` is oldest first with urgent ones ahead, since the oldest is the one that is late; one visit's tests come in the order they were asked for, anything else newest first. `counts` gives each status for the tabs, and `mine=true` narrows a doctor's list to their own orders.

`POST /patients/{id}/documents` takes the file as the whole request body, with its name, `category` and optionally `title`, `dated`, `consultation_id` or `lab_order_id` in the query, so the size is checked while the file is still arriving rather than after a form has been unpacked. Four megabytes is the most it takes, `413 FILE_TOO_LARGE` past that, because a Vercel function refuses a body much over 4.5 MB before the API sees it; the web app makes a large photo smaller before sending it. What the file is comes from its first bytes: a PDF, or a JPEG, PNG or WebP image, and anything else is `415 FILE_UNSUPPORTED_TYPE`, including an iPhone photo still in HEIC, which only Safari can show. The same file twice on one record is `409 DOC_ALREADY_UPLOADED`, and `candidates` carries the one already there. A file sent with `lab_order_id` is that test's report as the lab printed it, filed as a lab report and on the visit the test was ordered at; `PATCH /documents/{id}` with a `lab_order_id` puts a file already on the record with a test the same way. `GET /documents/{id}/file` sends the file itself, `?download=true` as an attachment, fetched from the store for a caller allowed to see it: the store's address never reaches the browser. Only whoever uploaded a file, or the clinic admin, can change or remove it, `403 DOC_NOT_UPLOADER` for anyone else, and removing it deletes the file from the store before the answer comes back.

`GET /invoices/start` is what a new bill begins from. For a visit it offers the doctor's fee, or their follow-up fee when the visit was booked as a follow-up or, for a walk-in, when the same doctor saw the patient within the clinic's follow-up window; the clinic's fee stands in for a doctor with none of their own. It lists the tests ordered at the visit, and names the bill already raised for it if there is one. `GET /invoices/lines` offers what the clinic has charged for before, most often first, at the price it last charged.

`POST /invoices` takes the lines, a discount with its reason, and a note, and keeps the bill as a draft unless `issue` is sent. The server works out every sum; a discount larger than the bill, or a bill over a crore, is `422 BILLING_INVALID_TOTAL`. A visit billed twice is `409 BILLING_ALREADY_BILLED`, and `candidates` carries the bill already there. A draft is changed with `PATCH` and thrown away with `DELETE`; once issued it is `409 BILLING_LOCKED` to both, and is put right by `POST /invoices/{id}/void` with a reason and a new bill. A void is refused with `409 BILLING_HAS_PAYMENTS` while money taken on the bill has not been given back.

`POST /invoices/{id}/payments` takes part of what is owed or all of it, and issues a draft first if it has to. More than the balance is `422 BILLING_PAYMENT_EXCEEDS_BALANCE`, with the balance in the sentence; a paid bill is `409 BILLING_ALREADY_PAID`. `POST /invoices/{id}/refunds` gives money back with a reason, never more than was taken, and only the clinic admin makes it. After a refund the bill takes no more payments, `409 BILLING_REFUNDED`.

`GET /invoices/summary` is the day's takings at the clinic by how they were paid, net of refunds, with the bills issued that day and what is still owed across every day. `GET /invoices/unbilled` lists patients seen that day with no live bill. `GET /invoices/{id}/pdf` is the bill as printed, which doubles as the receipt; a draft has none. Doctors and the staff role have no part in billing, and the queue leaves a visit's bill off for anyone who cannot read bills.

`GET /reports/summary` is the same figures over a stretch of days rather than one. `range` takes `today`, `week`, `month`, `this_month`, `last_month`, or `custom` with `from` and `to`; days are the clinic's own, not the server's, and a stretch longer than a year is `422` on `to`. It answers with the days one by one, including the ones nothing happened on, the takings by method, each doctor's line, the hours people arrive at, the tests ordered most, and what the bills were for. `before` is the stretch of the same length immediately before, so a figure can be read against something. `outstanding` deliberately ignores the dates: money owed since March is still owed in September.

The day's takings on the billing page and the figures here are worked out by one function, so a Tuesday read from either place reports the same numbers. `GET /reports/day-book.csv` is the payments behind them, one to a line, as a file for a spreadsheet: a cell that begins with `=`, `+`, `-` or `@` is written with a leading apostrophe, because a patient called `=cmd` is a patient and not a formula.

Every route that changes something writes an entry into the audit log in the same transaction as the change, so an entry exists exactly when the change does and a refused request leaves none. A retry that the idempotency key turns into a no-op writes nothing either. `GET /audit-logs` reads it newest first, 50 to a page and never more than 100, narrowed by `area` (`patients`, `appointments`, `clinical`, `billing`, `people`, `clinic`, `sign_in`), `actor_id`, `resource_id`, `from` and `to` in the clinic's own days, and `q` against the person's name and the record's. `resource_id` is the id of the page the record opens on, which for an allergy, a document, vital signs or a visit is the patient. It needs `audit:read`, which only the clinic admin holds. Each entry carries the actor by name, since the name must still read correctly after an account is suspended, and `changes` is either `{"field": [before, after]}` for an edit or a few facts about the action. An online payment has no actor id and reads as the patient.

Notices are always somebody's own. `GET /notifications` is the caller's, newest first, twenty at a time, with `before` set to the last id of one page to fetch the next; `more` says whether there is one. `GET /notifications/unread` is one number, for the bell to ask for every half minute. Another person's notice reads as `404`, whatever the caller's role, and `read-all` only ever touches the caller's own. A doctor hears about bookings, moves and cancellations in their list and about results for tests they ordered; whoever reads bills hears about money paid from a link; the clinic admin hears about voided bills and staff joining; anybody hears about their own role changing and their own account being locked. Nobody hears about what they did themselves, and a suspended account hears nothing.

`GET /notifications/preferences` lists only the kinds that can ever reach the caller, each with whether it is also emailed, and `email_available` says whether the clinic has a mail provider at all. `PUT` with `{kind, email}` changes one; a kind that cannot reach the caller is `422`. Email is off until each person turns it on, and goes out only after the change it is about has been saved.

Reports need `reports:read`, which the clinic admin and doctors hold and the desk does not. A doctor's report is their own work — their patients, the bills raised against them, the tests they ordered — narrowed the same way their day and their queue are, and an account with no profile linked reads as `unlinked` with nothing in it.

A caller with the doctor role sees only the appointments of the doctor profile linked to their account. Anything else reads as 404, a booking into another doctor's list is refused on `doctor_id`, and an account with no profile linked sees an empty day with `unlinked: true`. The queue is narrowed the same way, and checking patients in is left to the desk. `GET /consultations` is too: a doctor's list is their own notes whatever filter they send.

Money is a **string**:

```json
{ "subtotal": "1600.00", "tax_amount": "80.00", "total": "1680.00", "currency": "INR" }
```

JSON numbers become doubles in JavaScript, and a rounding error in a bill is not an acceptable class of bug. The server's figures are the ones kept. While a bill is being typed the web app shows a running total, worked in whole paise with the same half-up rounding on tax, so what it shows is what comes back.

## Idempotency

Endpoints that move money accept an `Idempotency-Key` header, 8 to 64 letters, digits, dashes or underscores. The key is kept on the row it made, under a unique index, rather than in a cache that could forget it: the same key again answers with the bill the first request made, `200` rather than `201`, or leaves a payment already taken as it was. Two requests with one key arriving together are settled by the index.

Applies to raising a bill, taking a payment and giving money back. Check-in and walk-ins need no key: a patient can only hold one live place in the queue, which the database enforces, so a retried check-in is refused with the token the first one was given rather than handing out a second.

Online payments are keyed differently, because the key cannot come from the desk. Razorpay's own payment id is the key, prefixed `rzp-`, on the same unique index. The patient's browser and Razorpay's webhook both report the same payment, so both arrive carrying the same key and only one of them writes a row.

## Paying without an account

`/pay/*` is the only part of the surface that answers a caller with no session, because the patient paying a bill has never had one and never will. The link stands in for a session: an unguessable token, hashed in the table the way every other emailed link is, good for one bill, for as long as that bill is open, and revocable from the desk.

What it hands back is deliberately thin — the clinic, the bill number, the amount, and the name on the bill. No phone number, no address, nothing clinical. Somebody who finds a forwarded link learns only what they would learn from the paper bill it replaces.

`POST /pay/{token}/confirm` carries what the checkout reports. It is signed with the API secret, which is how a made-up one is refused, but the signature only proves the report came from the checkout — the gateway is asked what actually happened before a rupee is recorded. `POST /pay/webhook/razorpay` says the same thing independently and is admitted only with Razorpay's signature over the exact bytes they sent, which is why that handler reads the raw body. Whichever arrives first records the money.

Money that arrives with nowhere to go — the desk took cash while the patient was paying — is not discarded. It is written down against the link as an excess for the desk to give back, because it is real money the clinic is holding.

## Authentication

Cookies, sent automatically. No `Authorization` header, so nothing needs to live in JavaScript.

On a 401 the client attempts one silent refresh, retries the original request once, and on a second failure routes to login with a message explaining the session ended.

## Documentation

FastAPI generates OpenAPI from the Pydantic models, so the schema cannot drift from the implementation. The interactive docs are available in development and preview, and disabled in production.
