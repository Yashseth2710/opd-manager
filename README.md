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

**Hosting** — Vercel, deployed as a single project

## Status

Early development. Architecture and conventions are documented in [`docs/`](docs/); implementation follows the build order described there.

## A note on the data

Everything in this repository — seeds, fixtures, tests, screenshots — uses synthetic data. No real patient information is used anywhere, and this build has not been assessed against any healthcare regulation. It is not certified for clinical use.

## Licence

MIT © Yash Seth
