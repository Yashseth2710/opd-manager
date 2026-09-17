"use client";

import { CornerDownRight, Users } from "lucide-react";
import Link from "next/link";
import type { Route } from "next";
import type { DuplicateCandidate } from "@/lib/patients";
import { describe, readablePhone } from "@/lib/patients";

/**
 * Shown when somebody already on the register looks like the person being
 * registered now.
 *
 * It offers the existing record first and registering anyway second, because
 * one person split across two records loses half their history, and the
 * cheapest moment to prevent that is before the second one exists.
 */
export function Duplicates({
  candidates,
  onRegisterAnyway,
  busy,
}: {
  candidates: DuplicateCandidate[];
  onRegisterAnyway?: () => void;
  busy?: boolean;
}) {
  if (candidates.length === 0) return null;

  return (
    <div className="mb-7 overflow-hidden rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--color-state-waiting)_45%,transparent)] bg-[var(--accent-wash)]">
      <div className="flex gap-3 px-5 py-4">
        <Users className="mt-0.5 size-4 shrink-0 text-[var(--color-marigold-600)]" />
        <div>
          <p className="text-[15px] font-semibold tracking-tight">
            {candidates.length === 1
              ? "Somebody like this is already registered"
              : `${candidates.length} people like this are already registered`}
          </p>
          <p className="mt-0.5 text-[14px] leading-relaxed text-[var(--text-muted)]">
            Open the existing record if it is the same person. Two records for one person means
            half their history is missing from each.
          </p>
        </div>
      </div>

      <ul className="divide-y divide-[color-mix(in_srgb,var(--color-state-waiting)_28%,transparent)] border-t border-[color-mix(in_srgb,var(--color-state-waiting)_28%,transparent)]">
        {candidates.map((candidate) => (
          <li key={candidate.id}>
            <Link
              href={`/patients/${candidate.id}` as Route}
              className="group flex items-center gap-4 px-5 py-3 transition-colors hover:bg-[color-mix(in_srgb,var(--color-state-waiting)_14%,transparent)]"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px] font-medium">
                  {candidate.full_name}
                  <span className="ml-2 font-mono text-[13px] font-normal text-[var(--text-muted)]">
                    {candidate.patient_number}
                  </span>
                  {candidate.status === "archived" && (
                    // Worth saying before they open it. An archived record is
                    // usually a reason to restore rather than start again.
                    <span className="ml-2 rounded-full bg-[var(--surface)] px-2 py-0.5 text-[12px] font-normal text-[var(--text-muted)]">
                      archived
                    </span>
                  )}
                </p>
                <p className="truncate text-[13px] text-[var(--text-muted)]">
                  {[candidate.reason, describe(candidate), readablePhone(candidate.phone)]
                    .filter(Boolean)
                    .join(" · ")}
                </p>
              </div>
              <CornerDownRight className="size-4 shrink-0 text-[var(--text-muted)] transition-transform group-hover:translate-x-0.5" />
            </Link>
          </li>
        ))}
      </ul>

      {onRegisterAnyway && (
        <div className="flex flex-wrap items-center gap-3 border-t border-[color-mix(in_srgb,var(--color-state-waiting)_28%,transparent)] px-5 py-3.5">
          <button
            type="button"
            onClick={onRegisterAnyway}
            disabled={busy}
            className="rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3.5 py-2 text-[14px] font-medium transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-50"
          >
            {busy ? "Registering…" : "This is somebody else — register them"}
          </button>
          <p className="text-[13px] text-[var(--text-muted)]">
            Families often share a phone number.
          </p>
        </div>
      )}
    </div>
  );
}
