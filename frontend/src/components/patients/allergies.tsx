"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Plus, TriangleAlert, X } from "lucide-react";
import { useState } from "react";
import { ApiFailure } from "@/lib/api";
import {
  recordAllergy,
  removeAllergy,
  SEVERITIES,
  type Allergy,
  type Severity,
} from "@/lib/patients";

const TONE: Record<Severity, string> = {
  severe: "var(--color-state-noshow)",
  moderate: "var(--color-state-waiting)",
  mild: "var(--text-muted)",
};

/**
 * Allergies sit on the record rather than on a visit, and severe ones are
 * given the only red on the page. The moment this list matters is the moment
 * nobody has time to read back through old notes.
 */
export function Allergies({
  patientId,
  allergies,
  editable,
}: {
  patientId: string;
  allergies: Allergy[];
  editable: boolean;
}) {
  const queries = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [substance, setSubstance] = useState("");
  const [reaction, setReaction] = useState("");
  const [severity, setSeverity] = useState<Severity>("moderate");
  const [problem, setProblem] = useState<string | null>(null);

  const refresh = () => queries.invalidateQueries({ queryKey: ["patient", patientId] });

  const add = useMutation({
    mutationFn: () => recordAllergy(patientId, { substance, reaction, severity }),
    onSuccess: async () => {
      // Waited for, so the list below has the new allergy on it by the time
      // the form closes rather than a moment later.
      await refresh();
      setSubstance("");
      setReaction("");
      setSeverity("moderate");
      setAdding(false);
      setProblem(null);
    },
    onError: (error) =>
      setProblem(
        error instanceof ApiFailure
          ? (error.fields?.substance ?? error.message)
          : "Could not save that.",
      ),
  });

  const drop = useMutation({
    mutationFn: (id: string) => removeAllergy(patientId, id),
    onSuccess: () => refresh(),
  });

  const worst = allergies.some((allergy) => allergy.severity === "severe");

  return (
    <section
      className={`rounded-[var(--radius-panel)] border bg-[var(--surface)] ${
        worst
          ? "border-[color-mix(in_srgb,var(--color-state-noshow)_45%,transparent)]"
          : "border-[var(--border)]"
      }`}
    >
      <header className="flex items-center justify-between gap-3 px-5 py-4">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          {worst && <TriangleAlert className="size-4 text-[var(--color-state-noshow)]" />}
          Allergies
        </h2>
        {editable && !adding && (
          <button
            type="button"
            onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] px-2 py-1 text-[13px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
          >
            <Plus className="size-3.5" />
            Add
          </button>
        )}
      </header>

      {allergies.length === 0 && !adding ? (
        <p className="px-5 pb-4 text-[14px] text-[var(--text-muted)]">
          None recorded. That is not the same as none known — ask at the next visit.
        </p>
      ) : (
        <ul className="divide-y divide-[var(--border)] border-t border-[var(--border)]">
          {allergies.map((allergy) => (
            <li key={allergy.id} className="flex items-center gap-3 px-5 py-3">
              <span
                aria-hidden
                className="size-1.5 shrink-0 rounded-full"
                style={{ background: TONE[allergy.severity] }}
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-[15px]">
                  {allergy.substance}
                  <span
                    className="ml-2 text-[13px] capitalize"
                    style={{ color: TONE[allergy.severity] }}
                  >
                    {allergy.severity}
                  </span>
                </p>
                {allergy.reaction && (
                  <p className="truncate text-[13px] text-[var(--text-muted)]">
                    {allergy.reaction}
                  </p>
                )}
              </div>
              {editable && (
                <button
                  type="button"
                  onClick={() => drop.mutate(allergy.id)}
                  disabled={drop.isPending}
                  aria-label={`Remove ${allergy.substance}`}
                  className="rounded-[var(--radius-field)] p-1.5 text-[var(--text-subtle)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)] disabled:opacity-50"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}

      {adding && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (substance.trim()) add.mutate();
          }}
          className="flex flex-col gap-3 border-t border-[var(--border)] px-5 py-4"
        >
          {problem && (
            <p role="alert" className="text-[13px] text-[var(--color-state-noshow)]">
              {problem}
            </p>
          )}
          <input
            value={substance}
            onChange={(event) => setSubstance(event.target.value)}
            placeholder="Substance, such as penicillin"
            aria-label="Substance"
            autoFocus
            required
            maxLength={120}
            className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] placeholder:text-[var(--text-subtle)]"
          />
          <input
            value={reaction}
            onChange={(event) => setReaction(event.target.value)}
            placeholder="What happens, such as rash or swelling"
            aria-label="Reaction"
            maxLength={200}
            className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] placeholder:text-[var(--text-subtle)]"
          />
          <div className="flex flex-wrap items-center gap-2">
            {SEVERITIES.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setSeverity(option)}
                aria-pressed={severity === option}
                className={`rounded-full border px-3 py-1 text-[13px] capitalize transition-colors ${
                  severity === option
                    ? "border-transparent bg-[var(--primary)] text-[var(--primary-fg)]"
                    : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
                }`}
              >
                {option}
              </button>
            ))}
            <div className="ml-auto flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  setAdding(false);
                  setProblem(null);
                }}
                className="rounded-[var(--radius-field)] px-2.5 py-1.5 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={add.isPending || !substance.trim()}
                className="rounded-[var(--radius-field)] bg-[var(--primary)] px-3.5 py-1.5 text-[14px] font-medium text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-50"
              >
                {add.isPending ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </form>
      )}
    </section>
  );
}
