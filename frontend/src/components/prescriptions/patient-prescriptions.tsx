"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { shortDate } from "@/lib/appointments";
import { listPrescriptions, localDay } from "@/lib/prescriptions";

const SHOWN = 8;

/** What this patient has been given, newest first, each a click from printing. */
export function PatientPrescriptions({ patientId }: { patientId: string }) {
  const found = useQuery({
    queryKey: ["prescriptions", { patient: patientId }],
    queryFn: () => listPrescriptions({ patient: patientId, limit: SHOWN }),
    retry: false,
  });

  return (
    <section
      aria-labelledby="prescriptions-title"
      className="min-w-0 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
    >
      <h2 id="prescriptions-title" className="text-[15px] font-semibold">
        Prescriptions
      </h2>
      {found.isPending ? (
        <p className="mt-3 inline-flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" /> Looking…
        </p>
      ) : found.isError ? (
        <p className="mt-3 text-[14px] text-[var(--text-muted)]">Prescriptions did not load.</p>
      ) : found.data.items.length === 0 ? (
        <p className="mt-2 text-[14px] leading-relaxed text-[var(--text-muted)]">
          Nothing prescribed yet.
        </p>
      ) : (
        <>
          <ol className="mt-3 flex flex-col gap-1">
            {found.data.items.map((rx) => (
              <li key={rx.id}>
                <Link
                  href={`/prescriptions/${rx.id}` as Route}
                  className="-mx-2 block rounded-[var(--radius-field)] px-2 py-1.5 transition-colors hover:bg-[var(--surface-sunken)]"
                >
                  <span className="flex items-baseline justify-between gap-2 text-[13px] text-[var(--text-muted)]">
                    <span className="font-mono tabular">{rx.number}</span>
                    <span className="tabular">
                      {rx.issued_at ? shortDate(localDay(rx.issued_at)) : ""}
                    </span>
                  </span>
                  <span
                    className={`block truncate text-[14px] font-medium ${
                      rx.status === "replaced" ? "text-[var(--text-muted)] line-through" : ""
                    }`}
                  >
                    {rx.medicines.length ? rx.medicines.join(", ") : "Advice only"}
                  </span>
                  {rx.status === "replaced" && (
                    <span className="block text-[12px] text-[var(--text-muted)]">Replaced</span>
                  )}
                </Link>
              </li>
            ))}
          </ol>
          {found.data.total > SHOWN && (
            <p className="mt-2 text-[13px] text-[var(--text-muted)] tabular">
              Showing the latest {SHOWN} of {found.data.total}.
            </p>
          )}
        </>
      )}
    </section>
  );
}
