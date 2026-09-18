# Data model

PostgreSQL 18 on Neon. SQLAlchemy 2.x models, Alembic migrations. Every schema change goes through a migration — no exceptions, including in development.

## Conventions

Applied to every table unless noted.

| Column | Type | Notes |
|---|---|---|
| `id` | `UUID` | UUIDv7, primary key, exposed in URLs |
| `organization_id` | `UUID` | On every tenant-owned table, `NOT NULL`, indexed |
| `created_at` | `TIMESTAMPTZ` | Server default `now()` |
| `updated_at` | `TIMESTAMPTZ` | Updated on write |
| `created_by` | `UUID` | User who created the row, where meaningful |

Naming: tables plural and snake_case, foreign keys `<singular>_id`, booleans `is_*`, timestamps `*_at`. Enums are Postgres enum types, not free text.

**Nothing important is deleted.** Patients are archived, doctors and staff deactivated, appointments cancelled, invoices voided. Medical and financial history is retained. `DELETE` appears only for genuinely disposable rows — expired tokens, read notifications past retention.

Money is `NUMERIC(12,2)`. Dates that represent a wall-clock concept (a doctor's working hours) are `TIME`; instants are `TIMESTAMPTZ`.

## Entity map

```
organizations ──┬── users ──── user_roles ──── roles ──── role_permissions ──── permissions
                │
                ├── doctors ──┬── doctor_schedules
                │             ├── doctor_leaves
                │             └── consultation_templates
                │
                ├── staff
                │
                ├── patients ─┬── patient_allergies
                │             ├── patient_documents
                │             └── patient_contacts
                │
                ├── appointments ──┬── appointment_status_history
                │                  └── opd_queue_entries
                │
                ├── consultations ─┬── vitals
                │                  ├── consultation_diagnoses ──── diagnoses
                │                  ├── prescriptions ──── prescription_items
                │                  ├── lab_orders ──── lab_results
                │                  └── follow_ups
                │
                ├── invoices ──┬── invoice_items
                │              └── payments
                │
                ├── notifications
                ├── notification_preferences
                ├── audit_logs
                ├── tenant_counters
                └── organization_subscriptions ──── subscription_plans
                                                 └── usage_records
```

`subscription_plans`, `permissions` and `diagnoses` are platform-level — shared across clinics and carrying no `organization_id`.

## Tenancy and identity

### organizations

The tenant. One row per clinic.

`name`, `slug` (unique), `logo_url`, `address`, `phone`, `email`, `website`, `timezone` (IANA, default `Asia/Kolkata`), `currency` (ISO 4217, default `INR`), `status` (`active` / `suspended` / `pending`), `onboarding_completed_at`.

Settings that grow over time — invoice prefix, token prefix, default consultation duration, tax rate — live in a `settings` JSONB column rather than accumulating columns. Anything queried or constrained gets promoted to a real column.

### users

Authentication identity. Email is unique **per organisation**, not globally, so the same person can hold accounts at two clinics.

`email`, `password_hash` (Argon2id), `first_name`, `last_name`, `phone`, `status`, `email_verified_at`, `last_login_at`, `failed_login_count`, `locked_until`.

```
UNIQUE (organization_id, lower(email))
```

Platform super admins have `organization_id = NULL`, which is the one deliberate exception to the tenancy rule and is checked for explicitly everywhere it matters.

### roles, permissions, user_roles

`permissions` is a fixed platform catalogue keyed by `resource:action` — `patient:create`, `billing:read`. `roles` are per-organisation so a clinic can adjust what its generic staff role can do, seeded from platform defaults on creation.

The full matrix is in [security.md](security.md).

### tenant_counters

Backs the human-readable display codes.

```
PRIMARY KEY (organization_id, counter)
counter ∈ patient | invoice | prescription | lab_order
```

Incremented with a single `UPDATE ... RETURNING`, which is atomic and row-locked. Queue tokens are not kept here: they start again every day for every doctor, and are counted from the queue itself.

## Clinical records

### patients

`patient_number` (`PT-000001`), `first_name`, `last_name`, `preferred_name`, `phone`, `alternate_phone`, `email`, `date_of_birth`, `gender`, `blood_group`, `address` (JSONB), `emergency_contact` (JSONB), `notes`, `status` (`active` / `archived`), `archived_at`, `registered_by`.

Phone numbers are stored as digits with an optional country prefix. Two records that differ only in punctuation are two records as far as duplicate detection is concerned.

Age is derived from `date_of_birth`, never stored — a stored age is wrong within a year.

```
UNIQUE (organization_id, patient_number)
INDEX  (organization_id, phone)
INDEX  (organization_id, status, last_name)
GIN    trigram index on name for fuzzy search
```

Duplicate detection runs on write and is advisory: exact phone match, exact email match, or fuzzy name plus matching date of birth. It surfaces candidates and never merges automatically. Merging patient records is a destructive clinical operation and is deliberately out of the initial build.

### patient_allergies

`patient_id`, `substance`, `reaction`, `severity` (`mild` / `moderate` / `severe`), `recorded_by`.

Held against the person rather than a visit, because an allergy is a standing fact and the moment it matters is the moment nobody has time to read back through old notes. One substance per patient; recording it twice is refused rather than silently duplicated.

### doctors

`user_id`, `title`, `first_name`, `last_name`, `speciality`, `qualifications`, `registration_number`, `years_of_experience`, `phone`, `email`, `room`, `languages` (JSONB), `bio`, `consultation_fee`, `follow_up_fee`, `slot_duration_minutes`, `status` (`active` / `inactive`), `deactivated_at`.

A doctor is a record of the clinic rather than of an account. `user_id` is nullable, because a visiting consultant needs a profile, a fee and a rota long before anyone gives them a login, and some never get one.

`consultation_fee`, `follow_up_fee` and `slot_duration_minutes` are nullable, and null means the clinic's figure applies. Storing a copy of the default instead would freeze it at the moment the profile was written, so raising the clinic fee would quietly stop reaching anyone. Zero is a real fee and survives — clinics see staff families for nothing.

```
UNIQUE (organization_id, user_id)                WHERE user_id IS NOT NULL
UNIQUE (organization_id, lower(registration_number)) WHERE registration_number IS NOT NULL
INDEX  (organization_id, status, last_name)
GIN    trigram index on name for fuzzy search
```

One account is one doctor, or a second profile could be linked to the same login and every consultation would have two plausible authors. A council registration number identifies one clinician, so two rows carrying the same one is a duplicate profile — and a prescription printed against the wrong one is a real-world problem.

### appointments

`patient_id`, `doctor_id`, `scheduled_start`, `scheduled_end`, `appointment_type` (`consultation` / `follow_up`), `reason`, `notes`, `source` (`desk` / `phone`), `status`, `cancelled_reason`, `cancelled_at`, `cancelled_by_id`, `booked_by_id`.

The start and end are instants, worked out from the clinic's date and wall-clock time when the slot was booked; the wall-clock view is derived again on the way out. The end always comes from the slot rather than the request.

Status: `scheduled` → `confirmed` → `checked_in` → `waiting` → `in_consultation` → `completed`, with `cancelled` and `no_show` as terminal exits. Transitions are validated in the service layer; `appointment_status_history` records every change with actor and timestamp.

Double booking is prevented in the database, not just in application code, for the doctor and for the patient:

```sql
EXCLUDE USING gist (
  doctor_id WITH =,
  tstzrange(scheduled_start, scheduled_end) WITH &&
) WHERE (status NOT IN ('cancelled', 'no_show'))

EXCLUDE USING gist (
  patient_id WITH =,
  tstzrange(scheduled_start, scheduled_end) WITH &&
) WHERE (status NOT IN ('cancelled', 'no_show'))
```

An exclusion constraint holds under concurrency. Two receptionists clicking "Book" on the same slot at the same moment is exactly the case an application-level check misses. Ranges are half-open, so one appointment ending at ten and the next starting at ten do not collide, and a cancelled or missed appointment gives its time back.

`appointment_status_history` is written on every change and never updated: `event` (`booked`, `confirmed`, `rescheduled`, `cancelled`, `no_show`, `edited`, and from the queue `checked_in`, `check_in_undone`, `started`, `seen`, `left`), `from_status`, `to_status`, a `detail` sentence such as "Moved from Mon 22 Sep, 9:00 am", `actor_id`, and `actor_name` copied at the time so the history stays readable after somebody leaves.

```
INDEX (organization_id, doctor_id, scheduled_start)
INDEX (organization_id, scheduled_start) WHERE status NOT IN ('cancelled','no_show','completed')
INDEX (organization_id, patient_id, scheduled_start)
```

### doctor_schedules, doctor_leaves

Schedules are recurring weekly rules: `day_of_week`, `start_time`, `end_time`, `slot_duration_minutes`, `break_start`, `break_end`. Times are `TIME`, interpreted in the clinic's timezone — a doctor who starts at nine starts at nine in March and in November, which a stored instant would not. `day_of_week` runs Monday to Sunday as 0 to 6, matching how a rota is written down.

Several rows for one day is the normal case rather than the exception: an OPD running nine to one and five to eight is two blocks, not one long block with a four-hour hole in it. Each block may set its own `slot_duration_minutes`, falling back to the doctor's and then the clinic's.

A whole week is replaced in one transaction rather than patched block by block, which is what makes the overlap check reliable — two people editing Tuesday from different desks could otherwise leave a doctor in two rooms at once. The table carries no timestamps for the same reason: a per-row `created_at` would only ever record the last replacement.

```
CHECK (end_time > start_time)
CHECK (day_of_week BETWEEN 0 AND 6)
CHECK ((break_start IS NULL) = (break_end IS NULL))
INDEX (organization_id, doctor_id, day_of_week)
```

`doctor_leaves` are dated exceptions with an optional time range, covering both a full day off and a two-hour gap. A time range spanning several days means those hours on each of them, which is how somebody describes leaving early all week.

```
CHECK (ends_on >= starts_on)
CHECK ((start_time IS NULL) = (end_time IS NULL))
INDEX (organization_id, doctor_id, starts_on, ends_on)
```

Availability is computed, not stored. Materialising slots would mean regenerating them whenever a schedule changes, and stale slot tables are a classic source of double bookings.

### opd_queue_entries

Created at check-in, or for a walk-in with no appointment. `appointment_id` (null for a walk-in), `patient_id`, `doctor_id`, `token_number`, `token_date` (the clinic's date), `priority` (`normal` / `urgent`), `status`, `reason` (a walk-in's), `checked_in_at`, `called_at`, `started_at`, `completed_at`, `checked_in_by_id`.

Status: `waiting` → `called` → `in_consultation` → `completed`, with `skipped` and `no_show` as exits. `skipped` returns to `waiting` on recall, keeping its number. A doctor can also bring a waiting patient straight in. Each step moves the appointment along with it (`waiting`, `in_consultation`, `completed`, or `no_show` for somebody who left) and writes a line to its history.

```
UNIQUE (organization_id, doctor_id, token_date, token_number)
UNIQUE (appointment_id)                           WHERE appointment_id IS NOT NULL
UNIQUE (organization_id, patient_id, token_date)  WHERE still in the building
UNIQUE (organization_id, doctor_id, token_date)   WHERE status = 'called'
UNIQUE (organization_id, doctor_id, token_date)   WHERE status = 'in_consultation'
INDEX  (organization_id, doctor_id, token_date, status)
```

The partial unique indexes stop two desks putting one patient in two lines, and a doctor having two patients called or two in the room. "Still in the building" means waiting, called, in consultation or skipped. They are keyed on the day, so a place nobody closed last night does not hold up the morning.

The token is the next number after the highest one the doctor has handed out that day, taken while holding a lock on the doctor's row, so two desks checking in for the same doctor take turns. Undoing a check-in removes the row, which never meant anything, and writes the undo to the appointment's history.

Estimated wait is worked out from the doctor's recent consultation times and the patient's position. It is a display value and is never persisted.

### consultations

One per completed visit, tied to one appointment.

`appointment_id`, `patient_id`, `doctor_id`, `chief_complaint`, `symptoms`, `examination`, `treatment_plan`, `notes`, `status` (`draft` / `completed`), `started_at`, `completed_at`.

Drafts autosave so a doctor does not lose ten minutes of typing to a closed tab.

### vitals

`consultation_id`, `systolic_bp`, `diastolic_bp`, `pulse`, `temperature_c`, `respiratory_rate`, `spo2`, `weight_kg`, `height_cm`, `recorded_by`, `recorded_at`.

BMI is derived. Every field is nullable — a clinic taking only blood pressure and weight is normal, and forcing a full vitals panel produces fabricated numbers.

### diagnoses, consultation_diagnoses

`diagnoses` is a searchable platform catalogue with an optional ICD-10 code. `consultation_diagnoses` joins it to a consultation, allows several per visit, marks one primary, and permits free-text entries for anything not in the catalogue.

The doctor selects the diagnosis. The system never infers one.

### prescriptions, prescription_items

`prescriptions`: `consultation_id`, `patient_id`, `doctor_id`, `prescription_number`, `instructions`, `follow_up_date`, `pdf_blob_url`, `issued_at`.

`prescription_items`: `medicine_name`, `strength`, `dosage` (`1-0-1`), `frequency`, `duration_days`, `route`, `instructions`, `sort_order`.

Medicine names are stored as text alongside a nullable reference to a catalogue entry. A doctor must be able to prescribe something the catalogue does not know about.

Once issued, a prescription is immutable. A correction is a new prescription referencing the original.

### lab_orders, lab_results

Order: `test_name`, `category`, `priority`, `instructions`, `status` (`pending` / `completed` / `reviewed`).
Result: `value`, `unit`, `reference_range`, `remarks`, `resulted_at`, `reviewed_by`.

Deliberately simple. Real lab integration is a different product.

### patient_documents

Metadata only — files live in Vercel Blob.

`patient_id`, `file_name` (sanitised), `original_name`, `content_type` (sniffed server-side), `size_bytes`, `blob_url`, `category`, `uploaded_by`.

The client-supplied MIME type is recorded but never trusted; the content type is determined from the file's magic bytes. Blob URLs are unguessable and access is brokered through the API, which checks tenancy and permission before redirecting.

## Billing

### invoices

`invoice_number` (`INV-000124`), `patient_id`, `appointment_id`, `consultation_id`, `subtotal`, `discount_amount`, `tax_amount`, `total`, `amount_paid`, `balance`, `status`, `notes`, `issued_at`, `voided_at`.

Status: `draft` → `pending` → `partially_paid` → `paid`, plus `void` and `refunded`.

The invariant, enforced by a check constraint rather than trusted to application code:

```
total = subtotal - discount_amount + tax_amount
balance = total - amount_paid
```

### invoice_items

`description`, `item_type` (`consultation` / `lab` / `procedure` / `medicine` / `other`), `quantity`, `unit_price`, `amount`, `sort_order`.

### payments

`invoice_id`, `amount`, `method`, `reference_number`, `notes`, `received_by`, `received_at`.

Partial payments are the normal case. `invoices.amount_paid` is maintained by the service inside the same transaction as the payment insert, so the two cannot drift. Payments are append-only; a correction is a negative adjustment, not an edit.

## Platform

### audit_logs

`organization_id`, `actor_id`, `actor_name` (denormalised — the log must still read correctly after a user is deactivated), `action`, `resource_type`, `resource_id`, `resource_label`, `changes` (JSONB), `ip_address`, `user_agent`, `created_at`.

Append-only. No `UPDATE` or `DELETE` path exists in the application, and the database role used by the API is granted `INSERT` and `SELECT` only.

```
INDEX (organization_id, created_at DESC)
INDEX (organization_id, resource_type, resource_id)
```

### subscription_plans, organization_subscriptions, usage_records

Plans carry limits as JSONB — `max_doctors`, `max_staff`, `max_patients`, `max_appointments_per_month`, `max_storage_mb` — plus a feature flag set. Limits are data, so adding a plan does not mean touching application code.

`usage_records` holds monthly counters per organisation, incremented on write and read by the entitlement check. Every limit check goes through one module; plan names never appear in feature code.

### notifications, notification_preferences

`user_id`, `type`, `title`, `body`, `link`, `channel`, `read_at`, `sent_at`.

The channel column exists from the start so email, SMS and WhatsApp can be added without a migration. The initial build delivers in-app only.

## Indexing

Beyond the primary keys and the indexes listed above:

- Every foreign key is indexed. Postgres does not do this automatically, and the omission shows up as slow cascade checks.
- Composite indexes lead with `organization_id`, because every tenant query filters on it first.
- Partial indexes for the hot paths — today's active queue, open invoices, upcoming appointments — stay small and are the ones under constant read pressure.
- Trigram indexes on patient name and doctor name for fuzzy search.

## Migrations

- One migration per logical change, with a meaningful name.
- Every migration has a working `downgrade`.
- Data migrations are separate from schema migrations.
- Adding a `NOT NULL` column to a populated table is three steps: add nullable, backfill, then constrain.
- Alembic connects to Neon's direct endpoint, not the pooled one.
