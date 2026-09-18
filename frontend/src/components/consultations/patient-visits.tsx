"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { shortDate } from "@/lib/appointments";
import { listConsultations } from "@/lib/consultations";

const SHOWN = 8;

/**
 * The patient's visits that have notes, newest first. A doctor sees the
 * visits they wrote up themselves; the clinic admin sees everyone's.
 */
export function PatientVisits({ patientId, ownOnly }: { patientId: string; ownOnly: boolean }) {
  const visits = useQuery({
    queryKey: ["consultations", { patient: patientId, limit: SHOWN }],
    queryFn: () => listConsultations({ patient: patientId, limit: SHOWN }),
    retry: false,
  });

  return (
    <section
      aria-labelledby="visits-title"
      className="min-w-0 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
    >
      <h2 id="visits-title" className="text-[15px] font-semibold">
        {ownOnly ? "Your notes" : "Visit notes"}
      </h2>
      {visits.isPending ? (
        <p className="mt-3 inline-flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" /> Looking…
        </p>
      ) : visits.isError ? (
        <p className="mt-3 text-[14px] text-[var(--text-muted)]">Visit notes did not load.</p>
      ) : visits.data.items.length === 0 ? (
        <p className="mt-2 text-[14px] leading-relaxed text-[var(--text-muted)]">
          {ownOnly
            ? "You have not written notes for this patient yet."
            : "No visit has been written up for this patient yet."}
        </p>
      ) : (
        <>
          <ol className="mt-3 flex flex-col gap-1">
            {visits.data.items.map((visit) => (
              <li key={visit.id}>
                <Link
                  href={`/consultations/${visit.id}` as Route}
                  className="-mx-2 block rounded-[var(--radius-field)] px-2 py-1.5 transition-colors hover:bg-[var(--surface-sunken)]"
                >
                  <span className="block text-[13px] text-[var(--text-muted)] tabular">
                    {shortDate(visit.visit_date)}
                    {!ownOnly && `, ${visit.doctor.display_name}`}
                    {visit.status === "draft" && ", not finished"}
                  </span>
                  <span className="block truncate text-[14px] font-medium">
                    {visit.primary_diagnosis ?? visit.chief_complaint ?? "Nothing written yet"}
                  </span>
                </Link>
              </li>
            ))}
          </ol>
          {visits.data.total > SHOWN && (
            <p className="mt-2 text-[13px] text-[var(--text-muted)] tabular">
              Showing the latest {SHOWN} of {visits.data.total}.
            </p>
          )}
        </>
      )}
    </section>
  );
}
