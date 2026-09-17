"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plane, Plus, X } from "lucide-react";
import { useRef, useState } from "react";
import { ApiFailure } from "@/lib/api";
import { cancelLeave, describeLeave, recordLeave, todayISO, type Leave } from "@/lib/doctors";

const BLANK = {
  starts_on: "",
  ends_on: "",
  start_time: "",
  end_time: "",
  reason: "",
};

/**
 * Days a doctor is away, which availability subtracts from the rota.
 *
 * Leave that has already finished is not shown: it stays in the table, out
 * of the way of somebody looking for who is in next week.
 */
export function Leaves({
  doctorId,
  leaves,
  editable,
}: {
  doctorId: string;
  leaves: Leave[];
  editable: boolean;
}) {
  const queries = useQueryClient();
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState(BLANK);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const inFlight = useRef(false);

  const refresh = () => {
    void queries.invalidateQueries({ queryKey: ["doctor", doctorId] });
    void queries.invalidateQueries({ queryKey: ["availability", doctorId] });
  };

  const record = useMutation({
    mutationFn: () =>
      recordLeave(doctorId, {
        starts_on: draft.starts_on,
        ends_on: draft.ends_on || null,
        start_time: draft.start_time || null,
        end_time: draft.end_time || null,
        reason: draft.reason.trim() || null,
      }),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: () => {
      refresh();
      setDraft(BLANK);
      setAdding(false);
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.fields) {
        setFields(error.fields);
        setProblem(null);
      } else {
        setProblem(error instanceof Error ? error.message : "Something went wrong.");
      }
    },
  });

  const drop = useMutation({
    mutationFn: (leaveId: string) => cancelLeave(doctorId, leaveId),
    onSuccess: refresh,
  });

  return (
    <section className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
      <header className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-3.5">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          <Plane className="size-4 text-[var(--text-muted)]" />
          Away
        </h2>
        {editable && !adding && (
          <button
            type="button"
            onClick={() => {
              setDraft({ ...BLANK, starts_on: todayISO() });
              setFields({});
              setProblem(null);
              setAdding(true);
            }}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[13px] transition-colors hover:bg-[var(--surface-sunken)]"
          >
            <Plus className="size-3.5" />
            Add
          </button>
        )}
      </header>

      {adding && (
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (inFlight.current) return;
            inFlight.current = true;
            setProblem(null);
            setFields({});
            record.mutate();
          }}
          noValidate
          className="border-b border-[var(--border)] px-5 py-4"
        >
          {problem && (
            <p role="alert" className="mb-3 text-[13px] text-[var(--color-state-noshow)]">
              {problem}
            </p>
          )}

          <div className="grid gap-3 sm:grid-cols-2">
            <Box
              label="From"
              name="starts_on"
              type="date"
              value={draft.starts_on}
              onChange={(value) => setDraft({ ...draft, starts_on: value })}
              error={fields.starts_on}
            />
            <Box
              label="To"
              name="ends_on"
              type="date"
              value={draft.ends_on}
              onChange={(value) => setDraft({ ...draft, ends_on: value })}
              error={fields.ends_on}
              hint="Leave empty for a single day."
            />
            <Box
              label="From time"
              name="start_time"
              type="time"
              value={draft.start_time}
              onChange={(value) => setDraft({ ...draft, start_time: value })}
              error={fields.start_time}
              hint="Both times empty means whole days."
            />
            <Box
              label="To time"
              name="end_time"
              type="time"
              value={draft.end_time}
              onChange={(value) => setDraft({ ...draft, end_time: value })}
              error={fields.end_time}
            />
          </div>

          <div className="mt-3">
            <Box
              label="Reason"
              name="reason"
              value={draft.reason}
              onChange={(value) => setDraft({ ...draft, reason: value })}
              error={fields.reason}
              placeholder="Conference, family wedding"
            />
          </div>

          <div className="mt-4 flex items-center gap-3">
            <button
              type="submit"
              disabled={record.isPending || !draft.starts_on}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-3.5 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {record.isPending && <Loader2 className="size-3.5 animate-spin" />}
              {record.isPending ? "Saving" : "Save"}
            </button>
            <button
              type="button"
              onClick={() => setAdding(false)}
              className="text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
            >
              Cancel
            </button>
          </div>
        </form>
      )}

      {leaves.length === 0 ? (
        <p className="px-5 py-8 text-center text-[14px] text-[var(--text-muted)]">
          Nothing booked off.
        </p>
      ) : (
        <ul className="divide-y divide-[var(--border)]">
          {leaves.map((leave) => (
            <li key={leave.id} className="flex items-start gap-3 px-5 py-3">
              <div className="min-w-0 flex-1">
                <p className="text-[14px] tabular">{describeLeave(leave)}</p>
                {leave.reason && (
                  <p className="truncate text-[13px] text-[var(--text-muted)]">
                    {leave.reason}
                  </p>
                )}
              </div>
              {editable && (
                <button
                  type="button"
                  onClick={() => drop.mutate(leave.id)}
                  disabled={drop.isPending}
                  aria-label={`Cancel leave on ${leave.starts_on}`}
                  className="rounded-[4px] p-1.5 text-[var(--text-subtle)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--color-state-noshow)] disabled:opacity-50"
                >
                  <X className="size-3.5" />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Box({
  label,
  name,
  type = "text",
  value,
  onChange,
  error,
  hint,
  placeholder,
}: {
  label: string;
  name: string;
  type?: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  hint?: string;
  placeholder?: string;
}) {
  return (
    <div>
      <label htmlFor={`leave-${name}`} className="mb-1 block text-[13px] font-medium">
        {label}
      </label>
      <input
        id={`leave-${name}`}
        name={name}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        aria-invalid={error ? true : undefined}
        className={`w-full rounded-[var(--radius-field)] border bg-[var(--surface)] px-3 py-2 text-[14px] transition-colors placeholder:text-[var(--text-subtle)] ${
          error
            ? "border-[var(--color-state-noshow)]"
            : "border-[var(--border-strong)] hover:border-[var(--color-paper-400)]"
        }`}
      />
      {error ? (
        <p role="alert" className="mt-1 text-[12px] text-[var(--color-state-noshow)]">
          {error}
        </p>
      ) : (
        hint && <p className="mt-1 text-[12px] text-[var(--text-subtle)]">{hint}</p>
      )}
    </div>
  );
}
