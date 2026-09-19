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
                │                  ├── lab_orders ──── lab_result_values
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

The doctor's notes for one visit: one per place in the queue, and tied to the appointment when the patient had one.

`queue_entry_id`, `appointment_id`, `patient_id`, `doctor_id`, `chief_complaint`, `history`, `examination`, `advice`, `follow_up_date`, `status` (`draft` / `completed`), `version`, `started_at`, `completed_at`, `written_by_id`.

```
UNIQUE (queue_entry_id) WHERE queue_entry_id IS NOT NULL
CHECK  ((status = 'completed') = (completed_at IS NOT NULL))
```

Drafts save as the doctor types, so a closed tab does not cost ten minutes of typing. `version` counts saves, and a save has to name the one it was written against, so two tabs on the same draft cannot overwrite each other without either noticing. Finished notes are never edited.

### consultation_addenda

`consultation_id`, `body`, `written_by_id`, `created_at`.

What comes to light after the notes were finished: a result, a phone call. Added underneath, dated and signed, and never changed or removed, because a note somebody may already have acted on has to keep saying what it said.

### vitals

`queue_entry_id`, `patient_id`, `systolic_mmhg`, `diastolic_mmhg`, `pulse_bpm`, `temperature_c`, `spo2_percent`, `respiratory_rate`, `weight_kg`, `height_cm`, `glucose_mg_dl`, `glucose_timing` (`fasting` / `random` / `after_meal`), `note`, `taken_at`, `taken_on` (the clinic's date), `taken_by_id`, `changed_by_id`.

```
UNIQUE (queue_entry_id)
CHECK  (at least one reading)
CHECK  ((systolic_mmhg IS NULL) = (diastolic_mmhg IS NULL))
CHECK  (diastolic_mmhg < systolic_mmhg)
CHECK  ((glucose_mg_dl IS NULL) = (glucose_timing IS NULL))
CHECK  (each reading within a range no patient falls outside)
INDEX  (organization_id, patient_id, taken_at)
```

Taken for a place in the queue, usually at the desk while the patient waits, and one set per visit: taking them again corrects the first set. Every reading is optional, since a clinic taking only blood pressure and weight is normal and a required full panel produces made-up numbers. The range checks are wide on purpose, 50 to 300 for the upper pressure, 30 to 45 °C: they catch 120 typed as 1200, not an unusual patient.

Temperature is held in Celsius to two places, so a Fahrenheit reading typed to one place reads back exactly as it was typed. Whoever can take vital signs can correct them on the day, until the visit is finished; after that they are part of what the doctor saw and stay as they were. Undoing a check-in, which is how the desk takes back checking in the wrong person, removes them with the place.

BMI, and whether a reading is out of range, are worked out when read rather than stored. Pressure, pulse, breathing and BMI are judged against adult ranges and only for adults, since a child's normal depends on their age; BMI uses the cut-offs agreed for Indian adults (23 and 25 rather than 25 and 30). Temperature, oxygen and blood sugar are judged at any age, sugar against when it was taken.

### consultation_diagnoses

`consultation_id`, `label`, `is_primary`, `position`.

```
UNIQUE (consultation_id) WHERE is_primary
```

Several per visit, in the doctor's words, with one marked as the main reason for it. A searchable catalogue with ICD-10 codes can sit behind this later; the label stays as the doctor wrote it either way.

The doctor selects the diagnosis. The system never infers one.

### medicines

`name`, `presentation`, `source`. Not a tenant table: one published list shared by every clinic, loaded by a migration and never written by the application.

The list is India's National List of Essential Medicines 2022, read out of the published PDF and checked by hand against its own alphabetical index: 376 medicines in 793 presentations such as `Tablet 500 mg` or `Eye drops 0.3%`. Blood products, dialysis fluids, disinfectants and devices a clinic does not write on a prescription are left out, and drops and ointments say whether they are for the eye or the ear, which the list only shows by section. The file behind it is `backend/app/data/medicines-nlem-2022.json`.

```
UNIQUE (lower(name), coalesce(lower(presentation), ''))
GIN    (lower(name) gin_trgm_ops)
```

### prescriptions, prescription_items

`prescriptions`: `consultation_id`, `patient_id`, `doctor_id`, `prescription_number` (`RX-000001`), `status` (`draft` / `issued` / `replaced`), `instructions`, `follow_up_date`, `replaces_id`, `correction_reason`, `issued_at`, `issued_by_id`.

`prescription_items`: `medicine_name`, `presentation`, `dose` (`1-0-1`, `5 mL`), `timing` (`before_food` / `after_food` / `with_food` / `empty_stomach` / `bedtime` / `as_needed`), `duration_days`, `instructions`, `position`.

```
UNIQUE (consultation_id) WHERE status = 'draft'
UNIQUE (consultation_id) WHERE status = 'issued'
UNIQUE (organization_id, prescription_number) WHERE prescription_number IS NOT NULL
CHECK  ((status = 'draft') = (prescription_number IS NULL))
```

A prescription is written with the visit's notes as a draft and issued when the visit is finished, which is when it takes the clinic's next number. Medicine names are kept as the doctor wrote them rather than as a reference into the list: a doctor has to be able to prescribe a brand, or anything else the list does not carry, and what was printed must read back the same whatever happens to the list later.

Once issued, a prescription is never changed. A correction is a new prescription, with its own number, that replaces the original; the original stays, marked replaced, because a copy of it may already be with a pharmacy. The printed page is made on request rather than stored, since an issued prescription never changes and every copy comes out the same.

### lab_orders, lab_result_values

`lab_orders`: `consultation_id`, `patient_id`, `doctor_id`, `order_number` (`LAB-000001`), `test_code`, `test_name`, `category`, `urgent`, `instructions`, `status` (`ordered` / `resulted` / `reviewed` / `cancelled`), `ordered_at`, `ordered_by_id`, `cancelled_at`, `cancelled_by_id`, `cancel_reason`, `reported_on`, `lab_name`, `findings`, `resulted_at`, `resulted_by_id`, `changed_by_id`, `reviewed_at`, `reviewed_by_id`.

`lab_result_values`: `lab_order_id`, `position`, `name`, `value`, `unit`, `low`, `high`, `expected`.

```
UNIQUE (consultation_id, lower(test_name)) WHERE status <> 'cancelled'
UNIQUE (organization_id, order_number)
CHECK  ((status = 'cancelled') = (cancelled_at IS NOT NULL))
CHECK  ((status IN ('resulted', 'reviewed')) = (resulted_at IS NOT NULL))
CHECK  ((status = 'reviewed') = (reviewed_at IS NOT NULL))
CHECK  (low <= high)
INDEX  (organization_id, patient_id, ordered_at)
INDEX  (organization_id, status, ordered_at)
```

One order is one test on one visit, ordered while the notes are open and numbered as it is made, so the desk sees it at once. A test taken back before the visit is finished is deleted, since nothing was done with it; after that it is cancelled with a reason and kept. The report is typed in when it comes back, usually at the desk, and can be corrected until the doctor who ordered it marks it seen, after which it stays as it was.

Values are kept as written, because many are not numbers: `Negative`, `1:160`, `++`. The range is the one printed on that lab's report, kept as numbers so the value can be judged against it; a word is judged against the word it should be instead. As with vital signs, the judgement is made on read and never stored. `reported_on` is the date on the report, the day the values belong to, whenever they were typed in.

The common tests are a list shipped with the code, `backend/app/data/lab-tests.json`: forty-odd outpatient tests with the parts of each report and the adult ranges most Indian labs print, by sex where they differ. It is not a table, because it is short, the same for every clinic and changes only with the code. It fills in the lines of a report and their ranges, which the lab's own report overrides, and leaves ranges blank for children, whose normal depends on their age. A test the list does not carry is ordered by name and typed in line by line.

Deliberately simple. Receiving results straight from a lab's own system is a different product.

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
