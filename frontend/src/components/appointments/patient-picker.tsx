"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Loader2, Search, UserPlus, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { initials, listPatients, readablePhone, type PatientSummary } from "@/lib/patients";

/** Enough to tell two people apart by, not the whole register. */
const SHOWN = 6;

/**
 * Finds the person being booked, by any of the things somebody at the desk
 * might have in front of them: a name as it was heard, a phone number read
 * off a screen, a number from an old card.
 */
export function PatientPicker({
  chosen,
  onChoose,
  error,
}: {
  chosen: PatientSummary | null;
  onChoose: (patient: PatientSummary | null) => void;
  error?: string;
}) {
  const [typed, setTyped] = useState("");
  const [asked, setAsked] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setAsked(typed.trim()), 250);
    return () => clearTimeout(timer);
  }, [typed]);

  const found = useQuery({
    queryKey: ["patients", "picker", asked],
    queryFn: () => listPatients({ q: asked, per_page: SHOWN }),
    enabled: asked.length > 0 && !chosen,
    retry: false,
  });

  if (chosen) {
    return (
      <div className="flex items-center gap-3 rounded-[var(--radius-panel)] border border-[var(--border-strong)] bg-[var(--surface)] px-4 py-3">
        <Avatar name={chosen.full_name} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[15px] font-medium">{chosen.full_name}</p>
          <p className="flex flex-wrap gap-x-3 text-[13px] text-[var(--text-muted)]">
            <span className="font-mono text-[12px] text-[var(--text-subtle)]">
              {chosen.patient_number}
            </span>
            {chosen.phone && <span className="tabular">{readablePhone(chosen.phone)}</span>}
            {chosen.age && <span>{chosen.age}</span>}
          </p>
          {chosen.allergy_count > 0 && (
            <p className="mt-1 inline-flex items-center gap-1 text-[12px] text-[var(--color-state-noshow)]">
              <AlertTriangle className="size-3" />
              {chosen.allergy_count === 1
                ? "1 allergy on record"
                : `${chosen.allergy_count} allergies on record`}
            </p>
          )}
        </div>
        <button
          type="button"
          onClick={() => {
            onChoose(null);
            setTyped("");
          }}
          className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[13px] transition-colors hover:bg-[var(--surface-sunken)]"
        >
          Change
        </button>
      </div>
    );
  }

  const results = found.data?.items ?? [];

  return (
    <div>
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[var(--text-subtle)]" />
        <input
          type="search"
          name="patient_id"
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          aria-label="Find the patient"
          aria-invalid={Boolean(error)}
          placeholder="Name, phone or PT number"
          autoComplete="off"
          className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] py-2.5 pr-9 pl-9 text-[15px] transition-colors placeholder:text-[var(--text-subtle)] hover:border-[var(--color-paper-400)] aria-invalid:border-[var(--color-state-noshow)]"
        />
        {found.isFetching ? (
          <Loader2 className="absolute top-1/2 right-3 size-4 -translate-y-1/2 animate-spin text-[var(--text-subtle)]" />
        ) : (
          typed && (
            <button
              type="button"
              onClick={() => setTyped("")}
              aria-label="Clear"
              className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded-[4px] p-1.5 text-[var(--text-subtle)] transition-colors hover:text-[var(--text)]"
            >
              <X className="size-3.5" />
            </button>
          )
        )}
      </div>

      {asked && found.isSuccess && (
        <div className="mt-2">
          {results.length === 0 ? (
            <p className="px-1 py-2 text-[14px] text-[var(--text-muted)]">
              Nobody registered matches “{asked}”.
            </p>
          ) : (
            <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
              {results.map((patient) => (
                <li key={patient.id}>
                  <button
                    type="button"
                    onClick={() => onChoose(patient)}
                    className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-[var(--surface-sunken)] focus-visible:bg-[var(--surface-sunken)]"
                  >
                    <Avatar name={patient.full_name} small />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[15px]">{patient.full_name}</span>
                      <span className="flex flex-wrap gap-x-3 text-[13px] text-[var(--text-muted)]">
                        <span className="font-mono text-[12px] text-[var(--text-subtle)]">
                          {patient.patient_number}
                        </span>
                        {patient.phone && (
                          <span className="tabular">{readablePhone(patient.phone)}</span>
                        )}
                        {patient.age && <span>{patient.age}</span>}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {found.isError && (
        <p className="mt-2 px-1 text-[14px] text-[var(--text-muted)]">
          The search did not go through. Try again in a moment.
        </p>
      )}

      <Link
        href="/patients/new"
        className="mt-3 inline-flex items-center gap-1.5 text-[14px] text-[var(--text-muted)] underline-offset-2 transition-colors hover:text-[var(--text)] hover:underline"
      >
        <UserPlus className="size-3.5" />
        Not registered yet? Register them first
      </Link>

      {error && (
        <p role="alert" className="mt-2 text-[13px] text-[var(--color-state-noshow)]">
          {error}
        </p>
      )}
    </div>
  );
}

function Avatar({ name, small = false }: { name: string; small?: boolean }) {
  return (
    <span
      aria-hidden
      className={`grid shrink-0 place-items-center rounded-full bg-[var(--accent-wash)] font-semibold text-[var(--color-marigold-700)] ${
        small ? "size-8 text-[12px]" : "size-10 text-[14px]"
      }`}
    >
      {initials(name)}
    </span>
  );
}
