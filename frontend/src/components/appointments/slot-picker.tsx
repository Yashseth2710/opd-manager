"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";
import {
  countSlots,
  getAvailability,
  readableTime,
  shiftDate,
  todayISO,
  type Slot,
} from "@/lib/doctors";
import { longDate } from "@/lib/appointments";

/**
 * A doctor's day as buttons: free times can be picked, booked ones are
 * shown and cannot, and ones already over are left out.
 *
 * Built from the same day plan the server books against, so a time that
 * shows here as free is one the server will accept, unless somebody else
 * takes it first.
 */
export function SlotPicker({
  doctorId,
  date,
  onDate,
  value,
  onPick,
  current,
  error,
}: {
  doctorId: string;
  date: string;
  onDate: (date: string) => void;
  value: string | null;
  onPick: (start: string) => void;
  /** Where the appointment being moved sits now, shown rather than offered. */
  current?: { date: string; start_time: string; doctorId: string };
  error?: string;
}) {
  const day = useQuery({
    queryKey: ["availability", doctorId, date],
    queryFn: () => getAvailability(doctorId, date),
    retry: false,
    enabled: Boolean(doctorId && date),
  });

  const isCurrent = (slot: Slot) =>
    current?.doctorId === doctorId &&
    current.date === date &&
    current.start_time.slice(0, 5) === slot.start_time.slice(0, 5);

  const shown = (day.data?.slots ?? []).filter((slot) => slot.state !== "past");
  const earliest = todayISO();

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => onDate(shiftDate(date, -1))}
          disabled={date <= earliest}
          aria-label="Previous day"
          className="rounded-[var(--radius-field)] border border-[var(--border-strong)] p-2 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          <ChevronLeft className="size-4" />
        </button>
        <input
          type="date"
          name="date"
          aria-label="Day"
          value={date}
          min={earliest}
          onChange={(event) => event.target.value && onDate(event.target.value)}
          aria-invalid={Boolean(error)}
          className="rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] tabular transition-colors hover:border-[var(--color-paper-400)] aria-invalid:border-[var(--color-state-noshow)]"
        />
        <button
          type="button"
          onClick={() => onDate(shiftDate(date, 1))}
          aria-label="Next day"
          className="rounded-[var(--radius-field)] border border-[var(--border-strong)] p-2 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
        >
          <ChevronRight className="size-4" />
        </button>
        <span className="text-[14px] text-[var(--text-muted)]">{longDate(date)}</span>
      </div>

      <div className="mt-4" role="group" aria-label="Times">
        {day.isPending ? (
          <div aria-hidden className="flex flex-wrap gap-2">
            {Array.from({ length: 10 }, (_, index) => (
              <span
                key={index}
                className="h-10 w-[5.5rem] animate-pulse rounded-[var(--radius-field)] bg-[var(--surface-sunken)]"
              />
            ))}
          </div>
        ) : day.isError ? (
          <p className="py-3 text-[14px] text-[var(--text-muted)]">
            The times for this day did not load.{" "}
            <button
              type="button"
              onClick={() => void day.refetch()}
              className="underline underline-offset-2"
            >
              Try again
            </button>
          </p>
        ) : shown.length === 0 ? (
          <p className="py-3 text-[14px] text-[var(--text-muted)]">
            {day.data.reason ??
              (day.data.slots.length ? "This clinic is over for the day." : "Nothing free.")}
          </p>
        ) : (
          <>
            <ul className="flex flex-wrap gap-2">
              {shown.map((slot) => {
                const here = isCurrent(slot);
                const taken = slot.state === "booked" && !here;
                const picked = value?.slice(0, 5) === slot.start_time.slice(0, 5);
                return (
                  <li key={slot.start_time}>
                    <button
                      type="button"
                      disabled={taken || here}
                      aria-pressed={picked}
                      onClick={() => onPick(slot.start_time.slice(0, 5))}
                      title={
                        here
                          ? "Where it is now"
                          : taken
                            ? "Already booked"
                            : `${readableTime(slot.start_time)} to ${readableTime(slot.end_time)}`
                      }
                      className={`flex h-10 min-w-[5.5rem] flex-col items-center justify-center rounded-[var(--radius-field)] border px-3 text-[14px] tabular transition-[background-color,border-color,color] duration-100 ${
                        picked
                          ? "border-[var(--color-ink-700)] bg-[var(--primary)] font-semibold text-[var(--primary-fg)]"
                          : here
                            ? "cursor-default border-dashed border-[var(--color-marigold-400)] bg-[var(--accent-wash)] text-[var(--text)]"
                            : taken
                              ? "cursor-not-allowed border-[var(--border)] bg-[var(--surface-sunken)] text-[var(--text-subtle)] line-through"
                              : "border-[var(--border-strong)] bg-[var(--surface)] hover:border-[var(--color-ink-400)] hover:bg-[var(--surface-sunken)]"
                      }`}
                    >
                      {readableTime(slot.start_time)}
                      {here && (
                        <span className="text-[11px] leading-none no-underline">now</span>
                      )}
                    </button>
                  </li>
                );
              })}
            </ul>
            <p className="mt-3 text-[13px] text-[var(--text-muted)]">{countSlots(shown)}</p>
          </>
        )}
      </div>

      {error && (
        <p role="alert" className="mt-2 text-[13px] text-[var(--color-state-noshow)]">
          {error}
        </p>
      )}
    </div>
  );
}
