"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowLeft, Loader2, NotebookPen } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { MedicineTable, PrintLink } from "@/components/prescriptions/card";
import { ApiFailure } from "@/lib/api";
import { shortDate, whenItHappened } from "@/lib/appointments";
import { currentSession } from "@/lib/auth";
import { getPrescription, localDay, type PrescriptionDetail } from "@/lib/prescriptions";

export default function PrescriptionPage() {
  return (
    <Permitted permission="prescription:read">
      <Prescription />
    </Permitted>
  );
}

function Prescription() {
  const id = String(useParams().id);
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const found = useQuery({
    queryKey: ["prescription", id],
    queryFn: () => getPrescription(id),
    retry: false,
  });

  if (found.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Opening the prescription…</span>
      </div>
    );
  }

  if (found.isError) {
    const error = found.error instanceof ApiFailure ? found.error : null;
    const missing = error?.code === "RX_NOT_FOUND" || error?.status === 422;
    return (
      <Page
        title={missing ? "No such prescription" : "The prescription did not load"}
        back={{ href: "/patients", label: "Back to patients" }}
      >
        <p className="max-w-[54ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
          {missing
            ? "This prescription does not exist at your clinic. It may have been opened from an old link, or not issued yet."
            : "Something went wrong reaching the server. Try again in a moment."}
        </p>
      </Page>
    );
  }

  const rx = found.data;
  const mayReadNotes = session.data?.permissions.includes("consultation:read") ?? false;

  return (
    <div className="mx-auto w-full max-w-4xl px-4 py-8 sm:px-6 lg:py-12">
      <Link
        href={`/patients/${rx.patient.id}` as Route}
        className="mb-5 inline-flex items-center gap-1.5 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
      >
        <ArrowLeft className="size-3.5" />
        {rx.patient.full_name}
      </Link>

      {rx.status === "replaced" && (
        <div
          role="alert"
          className="mb-5 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[var(--radius-field)] border border-[color-mix(in_srgb,var(--color-state-noshow)_45%,transparent)] bg-[color-mix(in_srgb,var(--color-state-noshow)_8%,transparent)] px-4 py-3 text-[14px]"
        >
          <AlertTriangle className="size-4 shrink-0 text-[var(--color-state-noshow)]" />
          <span className="min-w-0 flex-1">
            Replaced{rx.replaced_by ? ` by ${rx.replaced_by.number}` : ""}. Do not dispense from
            this copy.
          </span>
          {rx.replaced_by && (
            <Link
              href={`/prescriptions/${rx.replaced_by.id}` as Route}
              className="font-medium underline underline-offset-2"
            >
              Open {rx.replaced_by.number}
            </Link>
          )}
        </div>
      )}

      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-[24px] leading-tight font-semibold tracking-tight">
            Prescription{" "}
            <span className="font-mono text-[22px] font-normal tabular">{rx.number}</span>
          </h1>
          <p className="text-[14px] text-[var(--text-muted)]">
            {rx.issued_at ? `Issued ${whenItHappened(rx.issued_at)}` : ""}
            {rx.replaces && `, in place of ${rx.replaces.number}`}
            {rx.correction_reason && `: ${rx.correction_reason}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {mayReadNotes && (
            <Link
              href={`/consultations/${rx.consultation_id}` as Route}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
            >
              <NotebookPen className="size-4" />
              {rx.can_correct ? "Open the visit to correct it" : "Visit notes"}
            </Link>
          )}
          <PrintLink id={rx.id} number={rx.number} />
        </div>
      </div>

      <Paper rx={rx} />
    </div>
  );
}

/** The prescription laid out as it prints, so the desk can check it before printing. */
function Paper({ rx }: { rx: PrescriptionDetail }) {
  const facts = [
    rx.patient.age,
    rx.patient.gender
      ? ({ male: "Male", female: "Female", other: "Other" }[rx.patient.gender] ??
        rx.patient.gender)
      : null,
    rx.patient.patient_number,
  ].filter(Boolean);
  return (
    <article
      aria-label={`Prescription ${rx.number ?? ""}`}
      className="flex flex-col gap-6 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-6 sm:px-8"
    >
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-[var(--border)] pb-5">
        <div className="min-w-0">
          <p className="text-[18px] font-semibold">{rx.clinic.name}</p>
          {rx.clinic.address.map((line) => (
            <p key={line} className="text-[13px] text-[var(--text-muted)]">
              {line}
            </p>
          ))}
          {(rx.clinic.phone || rx.clinic.email) && (
            <p className="text-[13px] text-[var(--text-muted)]">
              {[rx.clinic.phone, rx.clinic.email].filter(Boolean).join(", ")}
            </p>
          )}
        </div>
        <div className="text-left sm:text-right">
          <p className="text-[15px] font-semibold">{rx.doctor.display_name}</p>
          {[rx.doctor.qualifications, rx.doctor.speciality].filter(Boolean).map((line) => (
            <p key={line} className="text-[13px] text-[var(--text-muted)]">
              {line}
            </p>
          ))}
          {rx.doctor.registration_number && (
            <p className="text-[13px] text-[var(--text-muted)]">
              Reg. no. {rx.doctor.registration_number}
            </p>
          )}
        </div>
      </header>

      <dl className="grid gap-4 sm:grid-cols-[2fr_1fr_1fr]">
        <div>
          <dt className="text-[12px] text-[var(--text-muted)]">Patient</dt>
          <dd className="font-semibold break-words">{rx.patient.full_name}</dd>
          <dd className="text-[13px] text-[var(--text-muted)] tabular">{facts.join(", ")}</dd>
        </div>
        <div>
          <dt className="text-[12px] text-[var(--text-muted)]">Date</dt>
          <dd className="font-semibold">
            {shortDate(rx.issued_at ? localDay(rx.issued_at) : rx.visit_date)}
          </dd>
        </div>
        <div>
          <dt className="text-[12px] text-[var(--text-muted)]">Prescription</dt>
          <dd className="font-mono tabular">{rx.number}</dd>
        </div>
      </dl>

      <div className="flex flex-col gap-2">
        <p className="text-[22px] leading-none font-semibold" aria-hidden>
          Rx
        </p>
        {rx.items.length ? (
          <MedicineTable items={rx.items} />
        ) : (
          <p className="text-[14px] text-[var(--text-muted)]">No medicines, advice only.</p>
        )}
      </div>

      {rx.instructions && (
        <div>
          <p className="text-[12px] text-[var(--text-muted)]">Advice</p>
          <p className="max-w-[75ch] text-[15px] leading-relaxed whitespace-pre-wrap">
            {rx.instructions}
          </p>
        </div>
      )}
      {rx.follow_up_date && (
        <p className="text-[15px]">
          Come back on <strong className="font-semibold">{shortDate(rx.follow_up_date)}</strong>
          .
        </p>
      )}
    </article>
  );
}
