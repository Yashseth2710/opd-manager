"use client";

import { useQuery } from "@tanstack/react-query";
import { CalendarDays, Plus } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useState } from "react";
import { StatusBadge } from "@/components/appointments/status";
import {
  bookingHref,
  getPatientAppointments,
  shortDate,
  type Appointment,
} from "@/lib/appointments";
import { readableTime } from "@/lib/doctors";

/** Past visits shown before somebody asks for the rest. */
const FIRST_FEW = 4;

/**
 * What is coming up for this person and what has been, on their record,
 * because "when am I next in?" is asked at the desk as often as anything.
 */
export function PatientAppointments({
  patientId,
  mayBook,
}: {
  patientId: string;
  mayBook: boolean;
}) {
  const [everything, setEverything] = useState(false);
  const found = useQuery({
    queryKey: ["patient-appointments", patientId],
    queryFn: () => getPatientAppointments(patientId),
    retry: false,
  });

  const history = found.data?.history ?? [];
  const shown = everything ? history : history.slice(0, FIRST_FEW);

  return (
    <section className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
      <header className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-3.5">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          <CalendarDays className="size-4 text-[var(--text-muted)]" />
          Appointments
        </h2>
        {mayBook && (
          <Link
            href={bookingHref({ patient: patientId }) as Route}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[13px] transition-colors hover:bg-[var(--surface-sunken)]"
          >
            <Plus className="size-3.5" />
            Book
          </Link>
        )}
      </header>

      {found.isPending ? (
        <div aria-hidden className="flex flex-col gap-2 px-5 py-4">
          <span className="h-4 w-3/4 animate-pulse rounded bg-[var(--surface-sunken)]" />
          <span className="h-4 w-1/2 animate-pulse rounded bg-[var(--surface-sunken)]" />
        </div>
      ) : found.isError ? (
        <p className="px-5 py-4 text-[14px] text-[var(--text-muted)]">
          Appointments did not load. Try again in a moment.
        </p>
      ) : (
        <>
          <div className="px-5 pt-3.5 pb-1">
            <h3 className="text-[13px] font-medium text-[var(--text-muted)]">Coming up</h3>
          </div>
          {found.data.upcoming.length === 0 ? (
            <p className="px-5 pb-3.5 text-[14px] text-[var(--text-subtle)]">Nothing booked.</p>
          ) : (
            <ul>
              {found.data.upcoming.map((appointment) => (
                <Line key={appointment.id} appointment={appointment} />
              ))}
            </ul>
          )}

          {history.length > 0 && (
            <>
              <div className="border-t border-[var(--border)] px-5 pt-3.5 pb-1">
                <h3 className="text-[13px] font-medium text-[var(--text-muted)]">Before</h3>
              </div>
              <ul>
                {shown.map((appointment) => (
                  <Line key={appointment.id} appointment={appointment} />
                ))}
              </ul>
              {history.length > FIRST_FEW && (
                <button
                  type="button"
                  onClick={() => setEverything(!everything)}
                  className="w-full border-t border-[var(--border)] px-5 py-2.5 text-left text-[13px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
                >
                  {everything ? "Show fewer" : `Show all ${history.length}`}
                </button>
              )}
            </>
          )}
        </>
      )}
    </section>
  );
}

function Line({ appointment }: { appointment: Appointment }) {
  return (
    <li>
      <Link
        href={`/appointments/${appointment.id}` as Route}
        className="flex items-start justify-between gap-3 px-5 py-2.5 transition-colors hover:bg-[var(--surface-sunken)]"
      >
        <span className="min-w-0">
          <span className="block text-[14px] tabular">
            {shortDate(appointment.date)}, {readableTime(appointment.start_time)}
          </span>
          <span className="block truncate text-[13px] text-[var(--text-muted)]">
            {appointment.doctor.display_name}
          </span>
        </span>
        <StatusBadge status={appointment.status} />
      </Link>
    </li>
  );
}
