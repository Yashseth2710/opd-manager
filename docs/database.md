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
counter ∈ patient | invoice | prescription | lab_order | queue_token
```

Incremented with a single `UPDATE ... RETURNING`, which is atomic and row-locked. `queue_token` additionally resets daily, keyed on the clinic's local date rather than UTC.

## Clinical records

### patients

`patient_number` (`PT-000001`), `first_name`, `last_name`, `preferred_name`, `phone`, `alternate_phone`, `email`, `date_of_birth`, `gender`, `blood_group`, `address` (JSONB), `emergency_contact` (JSONB), `notes`, `status` (`active` / `archived`).

Age is derived from `date_of_birth`, never stored — a stored age is wrong within a year.

```
UNIQUE (organization_id, patient_number)
INDEX  (organization_id, phone)
INDEX  (organization_id, status, last_name)
GIN    trigram index on name for fuzzy search
```

Duplicate detection runs on write and is advisory: exact phone match, exact email match, or fuzzy name plus matching date of birth. It surfaces candidates and never merges automatically. Merging patient records is a destructive clinical operation and is deliberately out of the initial build.

### appointments

`patient_id`, `doctor_id`, `scheduled_start`, `scheduled_end`, `appointment_type`, `reason`, `notes`, `source`, `status`, `cancelled_reason`, `cancelled_by`.

Status: `scheduled` → `confirmed` → `checked_in` → `waiting` → `in_consultation` → `completed`, with `cancelled` and `no_show` as terminal exits. Transitions are validated in the service layer; `appointment_status_history` records every change with actor and timestamp.

Double booking is prevented in the database, not just in application code:

```sql
EXCLUDE USING gist (
  doctor_id WITH =,
  tstzrange(scheduled_start, scheduled_end) WITH &&
) WHERE (status NOT IN ('cancelled', 'no_show'))
```

An exclusion constraint holds under concurrency. Two receptionists clicking "Book" on the same slot at the same moment is exactly the case an application-level check misses.

```
INDEX (organization_id, doctor_id, scheduled_start)
INDEX (organization_id, scheduled_start) WHERE status NOT IN ('cancelled','completed')
INDEX (organization_id, patient_id, scheduled_start DESC)
```

### doctor_schedules, doctor_leaves

Schedules are recurring weekly rules: `day_of_week`, `start_time`, `end_time`, `slot_duration_minutes`, `break_start`, `break_end`. Times are `TIME`, interpreted in the clinic's timezone.

`doctor_leaves` are dated exceptions with an optional time range, covering both a full day off and a two-hour gap.

Availability is computed, not stored. Materialising slots would mean regenerating them whenever a schedule changes, and stale slot tables are a classic source of double bookings.

### opd_queue_entries

Created at check-in. `appointment_id`, `patient_id`, `doctor_id`, `token_number`, `token_date`, `priority`, `status`, `checked_in_at`, `called_at`, `completed_at`.

Status: `waiting` → `called` → `in_consultation` → `completed`, with `skipped` and `no_show` as exits. `skipped` can return to `waiting` on recall.

```
UNIQUE (organization_id, doctor_id, token_date, token_number)
INDEX  (organization_id, doctor_id, token_date, status)
```

Estimated wait is derived from the clinic's rolling average consultation time and queue position. It is a display value and is never persisted.

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
