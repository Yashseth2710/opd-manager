"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CalendarRange, CopyPlus, Loader2, Plus, X } from "lucide-react";
import { useRef, useState } from "react";
import { Problem } from "@/components/auth/form";
import { ApiFailure } from "@/lib/api";
import {
  DAYS,
  forInput,
  readableTime,
  saveSchedule,
  type BlockDraft,
  type ScheduleBlock,
} from "@/lib/doctors";

let counter = 0;
const nextKey = () => `block-${(counter += 1)}`;

function asDrafts(blocks: ScheduleBlock[]): BlockDraft[] {
  return blocks.map((block) => ({
    key: nextKey(),
    day_of_week: block.day_of_week,
    start_time: forInput(block.start_time),
    end_time: forInput(block.end_time),
    break_start: forInput(block.break_start) || null,
    break_end: forInput(block.break_end) || null,
    slot_duration_minutes: block.slot_duration_minutes,
  }));
}

function blankBlock(day: number, after: BlockDraft[]): BlockDraft {
  // A second block on a day is nearly always the evening clinic, so it
  // starts where an evening clinic starts rather than on top of the morning.
  const evening = after.some((block) => block.day_of_week === day);
  return {
    key: nextKey(),
    day_of_week: day,
    start_time: evening ? "17:00" : "09:00",
    end_time: evening ? "20:00" : "13:00",
    break_start: null,
    break_end: null,
    slot_duration_minutes: null,
  };
}

/**
 * The week a doctor sits, edited as a week.
 *
 * The whole rota is sent on every save rather than block by block. Two
 * people editing Tuesday from different desks would otherwise be able to
 * leave a doctor in two rooms at once, and replacing the set in one
 * transaction is what lets the server's overlap check be the truth.
 */
export function Schedule({
  doctorId,
  blocks,
  editable,
  slotMinutes,
}: {
  doctorId: string;
  blocks: ScheduleBlock[];
  editable: boolean;
  slotMinutes: number;
}) {
  const queries = useQueryClient();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<BlockDraft[]>([]);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const inFlight = useRef(false);

  const save = useMutation({
    mutationFn: () =>
      saveSchedule(
        doctorId,
        // Sorted so the indexes the server reports problems against line up
        // with the order they are shown in.
        [...draft]
          .sort(
            (one, two) =>
              one.day_of_week - two.day_of_week || one.start_time.localeCompare(two.start_time),
          )
          .map(({ key: _key, ...block }) => ({
            ...block,
            break_start: block.break_start || null,
            break_end: block.break_end || null,
          })),
      ),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: ["doctor", doctorId] });
      void queries.invalidateQueries({ queryKey: ["doctors"] });
      void queries.invalidateQueries({ queryKey: ["availability", doctorId] });
      setEditing(false);
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

  const start = () => {
    setDraft(asDrafts(blocks));
    setFields({});
    setProblem(null);
    setEditing(true);
  };

  const change = (key: string, changes: Partial<BlockDraft>) => {
    setDraft((current) =>
      current.map((block) => (block.key === key ? { ...block, ...changes } : block)),
    );
    setFields({});
  };

  const ordered = [...draft].sort(
    (one, two) =>
      one.day_of_week - two.day_of_week || one.start_time.localeCompare(two.start_time),
  );
  const problemFor = (block: BlockDraft) => {
    const index = ordered.indexOf(block);
    const found = Object.entries(fields).find(([key]) => key.startsWith(`blocks.${index}.`));
    return found?.[1];
  };

  if (!editing) {
    return (
      <section className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
        <header className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-3.5">
          <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
            <CalendarRange className="size-4 text-[var(--text-muted)]" />
            Weekly hours
          </h2>
          {editable && (
            <button
              type="button"
              onClick={start}
              className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[13px] transition-colors hover:bg-[var(--surface-sunken)]"
            >
              {blocks.length ? "Edit hours" : "Set hours"}
            </button>
          )}
        </header>

        {blocks.length === 0 ? (
          <p className="px-5 py-8 text-center text-[14px] text-[var(--text-muted)]">
            No hours set yet, so nobody can be booked in with them.
          </p>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {DAYS.map((day, index) => {
              const onThisDay = blocks.filter((block) => block.day_of_week === index);
              if (onThisDay.length === 0) return null;
              return (
                // Stacked on a phone rather than wrapped, so a day with two
                // blocks reads the same way as a day with one.
                <li key={day} className="flex flex-col gap-x-5 gap-y-1 px-5 py-3 sm:flex-row">
                  <span className="w-24 shrink-0 text-[14px] font-medium">{day}</span>
                  <div className="flex min-w-0 flex-col gap-1">
                    {onThisDay.map((block) => (
                      <p key={block.id} className="text-[14px] tabular">
                        {readableTime(block.start_time)} – {readableTime(block.end_time)}
                        {block.break_start && (
                          <span className="text-[var(--text-muted)]">
                            {" "}
                            (break {readableTime(block.break_start)}–
                            {readableTime(block.break_end)})
                          </span>
                        )}
                        {block.slot_duration_minutes && (
                          <span className="text-[var(--text-muted)]">
                            {" "}
                            · {block.slot_duration_minutes} min
                          </span>
                        )}
                      </p>
                    ))}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>
    );
  }

  const copyDown = () => {
    const monday = draft.filter((block) => block.day_of_week === 0);
    if (monday.length === 0) return;
    const weekdays = [1, 2, 3, 4].flatMap((day) =>
      monday.map((block) => ({ ...block, key: nextKey(), day_of_week: day })),
    );
    setDraft([
      ...draft.filter((block) => block.day_of_week === 0 || block.day_of_week > 4),
      ...weekdays,
    ]);
    setFields({});
  };

  return (
    <section className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
      <header className="flex items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-3.5">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          <CalendarRange className="size-4 text-[var(--text-muted)]" />
          Weekly hours
        </h2>
        {draft.some((block) => block.day_of_week === 0) && (
          <button
            type="button"
            onClick={copyDown}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] px-2.5 py-1.5 text-[13px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
          >
            <CopyPlus className="size-3.5" />
            Monday across the week
          </button>
        )}
      </header>

      <div className="px-5 py-4">
        {problem && <Problem>{problem}</Problem>}

        <ul className="flex flex-col gap-3">
          {DAYS.map((day, index) => {
            const onThisDay = ordered.filter((block) => block.day_of_week === index);
            return (
              <li key={day} className="flex flex-col gap-2 sm:flex-row sm:items-start sm:gap-4">
                <span className="w-24 shrink-0 pt-2 text-[14px] font-medium">{day}</span>

                <div className="flex min-w-0 flex-1 flex-col gap-2">
                  {onThisDay.map((block) => (
                    <BlockRow
                      key={block.key}
                      block={block}
                      slotMinutes={slotMinutes}
                      problem={problemFor(block)}
                      onChange={(changes) => change(block.key, changes)}
                      onRemove={() =>
                        setDraft((current) =>
                          current.filter((other) => other.key !== block.key),
                        )
                      }
                    />
                  ))}

                  <button
                    type="button"
                    onClick={() =>
                      setDraft((current) => [...current, blankBlock(index, current)])
                    }
                    className="inline-flex w-fit items-center gap-1.5 rounded-[var(--radius-field)] px-2 py-1.5 text-[13px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
                  >
                    <Plus className="size-3.5" />
                    {onThisDay.length ? "Another block" : "Add hours"}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>

        <div className="mt-5 flex items-center gap-3 border-t border-[var(--border)] pt-4">
          <button
            type="button"
            onClick={() => {
              if (inFlight.current) return;
              inFlight.current = true;
              setProblem(null);
              save.mutate();
            }}
            disabled={save.isPending}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition-[filter,transform] duration-150 ease-[var(--ease-out-quint)] hover:brightness-[1.06] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60"
          >
            {save.isPending && <Loader2 className="size-4 animate-spin" />}
            {save.isPending ? "Saving" : "Save hours"}
          </button>
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="rounded-[var(--radius-field)] px-3 py-2 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
          >
            Cancel
          </button>
        </div>
      </div>
    </section>
  );
}

function BlockRow({
  block,
  slotMinutes,
  problem,
  onChange,
  onRemove,
}: {
  block: BlockDraft;
  slotMinutes: number;
  problem?: string;
  onChange: (changes: Partial<BlockDraft>) => void;
  onRemove: () => void;
}) {
  const hasBreak = Boolean(block.break_start);

  return (
    <div
      className={`rounded-[var(--radius-field)] border px-3 py-2.5 ${
        problem ? "border-[var(--color-state-noshow)]" : "border-[var(--border)]"
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        <Time
          label={`${DAYS[block.day_of_week]} start`}
          value={block.start_time}
          onChange={(value) => onChange({ start_time: value })}
        />
        <span className="text-[13px] text-[var(--text-subtle)]">to</span>
        <Time
          label={`${DAYS[block.day_of_week]} end`}
          value={block.end_time}
          onChange={(value) => onChange({ end_time: value })}
        />

        <input
          type="number"
          aria-label={`${DAYS[block.day_of_week]} appointment length`}
          value={block.slot_duration_minutes ?? ""}
          onChange={(event) =>
            onChange({
              slot_duration_minutes: event.target.value ? Number(event.target.value) : null,
            })
          }
          placeholder={String(slotMinutes)}
          className="w-16 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1.5 text-[14px] tabular transition-colors hover:border-[var(--color-paper-400)]"
        />
        <span className="text-[13px] text-[var(--text-subtle)]">min</span>

        <button
          type="button"
          onClick={() =>
            onChange(
              hasBreak
                ? { break_start: null, break_end: null }
                : { break_start: "13:00", break_end: "14:00" },
            )
          }
          className="rounded-[var(--radius-field)] px-2 py-1.5 text-[13px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
        >
          {hasBreak ? "No break" : "Add a break"}
        </button>

        <button
          type="button"
          onClick={onRemove}
          aria-label={`Remove these ${DAYS[block.day_of_week]} hours`}
          className="ml-auto rounded-[4px] p-1.5 text-[var(--text-subtle)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--color-state-noshow)]"
        >
          <X className="size-3.5" />
        </button>
      </div>

      {hasBreak && (
        <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-[var(--border)] pt-2">
          <span className="text-[13px] text-[var(--text-muted)]">Break</span>
          <Time
            label={`${DAYS[block.day_of_week]} break start`}
            value={block.break_start ?? ""}
            onChange={(value) => onChange({ break_start: value })}
          />
          <span className="text-[13px] text-[var(--text-subtle)]">to</span>
          <Time
            label={`${DAYS[block.day_of_week]} break end`}
            value={block.break_end ?? ""}
            onChange={(value) => onChange({ break_end: value })}
          />
        </div>
      )}

      {problem && (
        <p role="alert" className="mt-2 text-[13px] text-[var(--color-state-noshow)]">
          {problem}
        </p>
      )}
    </div>
  );
}

function Time({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <input
      type="time"
      aria-label={label}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1.5 text-[14px] tabular transition-colors hover:border-[var(--color-paper-400)]"
    />
  );
}
