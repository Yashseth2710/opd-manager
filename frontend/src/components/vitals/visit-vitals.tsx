"use client";

import { useQuery } from "@tanstack/react-query";
import { HeartPulse, Loader2 } from "lucide-react";
import { useState } from "react";
import { VitalsForm } from "@/components/vitals/form";
import { ReadingsLine } from "@/components/vitals/readings";
import { whenItHappened } from "@/lib/appointments";
import { BMI_WORDS, vitalsForVisit } from "@/lib/vitals";

/**
 * The readings taken for this visit, where the doctor reads them before
 * anything else. Taking or correcting them opens in place.
 */
export function VisitVitals({
  entryId,
  patientName,
  mayRecord,
  open: visitOpen,
}: {
  entryId: string;
  patientName: string;
  mayRecord: boolean;
  /** Whether the visit is still going, which is when new readings make sense. */
  open: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [said, setSaid] = useState<string | null>(null);
  const found = useQuery({
    queryKey: ["vitals", "visit", entryId],
    queryFn: () => vitalsForVisit(entryId),
    select: (page) => page.items[0] ?? null,
    retry: false,
  });
  const vitals = found.data ?? null;
  // The visit being finished on this screen closes the readings too, before
  // the answer loaded while it was open is asked for again.
  const mayChange = mayRecord && visitOpen && (vitals ? vitals.can_change : true);

  return (
    <section
      aria-label="Vitals"
      className="border-t border-[var(--border)] px-5 py-2.5 text-[14px]"
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="inline-flex items-center gap-1.5 font-semibold">
          <HeartPulse className="size-4 text-[var(--text-subtle)]" />
          Vitals
        </span>
        {found.isPending ? (
          <span className="inline-flex items-center gap-1.5 text-[13px] text-[var(--text-muted)]">
            <Loader2 className="size-3.5 animate-spin" />
            Checking
          </span>
        ) : found.isError ? (
          <span className="text-[13px] text-[var(--color-state-noshow)]">
            Did not load.{" "}
            <button
              type="button"
              onClick={() => void found.refetch()}
              className="font-medium underline underline-offset-2"
            >
              Try again
            </button>
          </span>
        ) : vitals ? (
          <>
            <ReadingsLine vitals={vitals} spoken className="text-[14px]" />
            {vitals.bmi_band && (
              <span className="text-[13px] text-[var(--text-muted)]">
                ({BMI_WORDS[vitals.bmi_band]})
              </span>
            )}
          </>
        ) : (
          <span className="text-[13px] text-[var(--text-muted)]">
            None taken for this visit.
          </span>
        )}
        {mayChange && !editing && !found.isPending && !found.isError && (
          <button
            type="button"
            onClick={() => {
              setSaid(null);
              setEditing(true);
            }}
            className="ml-auto inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1 text-[13px] font-medium transition-colors hover:bg-[var(--surface-sunken)]"
          >
            {vitals ? "Correct" : "Take vitals"}
          </button>
        )}
      </div>
      {vitals && (
        <p className="mt-1 text-[12px] text-[var(--text-subtle)]">
          {whenItHappened(vitals.taken_at)}
          {vitals.taken_by ? `, by ${vitals.taken_by}` : ""}
          {vitals.changed_by ? `, corrected by ${vitals.changed_by}` : ""}
          {vitals.note ? `. ${vitals.note}` : ""}
        </p>
      )}
      {said && (
        <p role="status" className="mt-1 text-[13px] text-[var(--text-muted)]">
          {said}
        </p>
      )}
      {editing && (
        <div className="mt-3 mb-1">
          <VitalsForm
            entryId={entryId}
            patientName={patientName}
            onClose={() => setEditing(false)}
            onSaved={(text) => {
              setEditing(false);
              setSaid(text);
            }}
          />
        </div>
      )}
    </section>
  );
}
