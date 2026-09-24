"use client";

import { useState } from "react";
import { money } from "@/lib/clinic";
import type { DayLine, HourLine } from "@/lib/reports";

const PATIENTS = "var(--color-marigold-400)";
const MISSED = "var(--color-state-noshow)";
const MONEY = "var(--color-state-completed)";

/** Enough of a column to see, even on the day one person came. */
const FLOOR = 3;

function readable(day: string): string {
  return new Date(`${day}T00:00:00`).toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
}

function tallest(values: number[]): number {
  return Math.max(1, ...values);
}

/**
 * The stretch a day at a time. Hovering or tabbing to a column reads that
 * day out above the chart; leaving it puts the whole stretch back.
 */
export function DayChart({
  days,
  showing,
  currency,
}: {
  days: DayLine[];
  showing: "patients" | "money";
  currency: string;
}) {
  const [held, setHeld] = useState<number | null>(null);
  const counting = showing === "patients";
  const columns = days.map((day) => {
    const came = day.seen + day.no_shows;
    return {
      day,
      height: counting ? came : Number(day.collected),
      // The part of the column that never made it into a room.
      missed: counting && came > 0 ? (day.no_shows / came) * 100 : 0,
    };
  });
  const most = tallest(columns.map((column) => column.height));
  const day = held === null ? null : (columns[held]?.day ?? null);

  // Only so many dates fit under the columns. Past a fortnight every day
  // number turns into a grey smear, and past a couple of months there is no
  // room for numbers at all, so the axis names the ends and the middle.
  const dense = days.length > 45;
  const every = days.length <= 14 ? 1 : 5;
  // A year of columns cannot each carry a gap: the gaps alone would be wider
  // than the chart, and every column would come out a nothing wide.
  const gap = dense ? "1px" : "3px";

  return (
    <figure className="flex flex-col gap-3 px-5 py-4">
      <figcaption
        aria-live="polite"
        className="flex min-h-[38px] flex-wrap items-baseline gap-x-3 gap-y-0.5"
      >
        {day ? (
          <>
            <span className="text-[15px] font-medium">{readable(day.date)}</span>
            <span className="text-[14px] text-[var(--text-muted)]">
              {counting ? (
                <>
                  <span className="tabular">{day.seen}</span> seen
                  {day.walk_ins > 0 && (
                    <>
                      , <span className="tabular">{day.walk_ins}</span> walked in
                    </>
                  )}
                  {day.no_shows > 0 && (
                    <>
                      , <span className="tabular">{day.no_shows}</span> did not stay
                    </>
                  )}
                </>
              ) : (
                <span className="font-mono tabular">{money(day.collected, currency)}</span>
              )}
            </span>
          </>
        ) : (
          <span className="text-[14px] text-[var(--text-muted)]">
            {counting
              ? "Patients seen each day, with the ones who did not stay on top."
              : "Taken each day, less anything given back."}
          </span>
        )}
      </figcaption>

      <ul
        className="flex h-40 items-end"
        style={{ gap }}
        onMouseLeave={() => setHeld(null)}
        role="list"
      >
        {columns.map(({ day: each, height, missed }, index) => {
          const lit = held === index;
          return (
            <li key={each.date} className="flex h-full min-w-px flex-1 items-end">
              <button
                type="button"
                aria-label={
                  counting
                    ? `${readable(each.date)}: ${each.seen} seen, ${each.no_shows} did not stay`
                    : `${readable(each.date)}: ${money(each.collected, currency)}`
                }
                onMouseEnter={() => setHeld(index)}
                onFocus={() => setHeld(index)}
                onBlur={() => setHeld(null)}
                // Full height so there is something to point at above a short
                // column, but the ring goes on the column itself: a ring round
                // the whole strip would outline empty space.
                className="group flex h-full w-full cursor-default flex-col justify-end outline-none"
              >
                <span
                  className="block w-full overflow-hidden rounded-t-[3px] transition-[height,opacity] duration-[160ms] ease-[cubic-bezier(0.32,0.72,0,1)] group-hover:opacity-100 group-focus-visible:outline-2 group-focus-visible:outline-offset-2 group-focus-visible:outline-[var(--focus-ring)]"
                  style={{
                    height:
                      height > 0
                        ? `${Math.max(FLOOR, (height / most) * 100)}%`
                        : // A day nothing happened on draws a hairline, not a
                          // stub that reads as one patient.
                          "1px",
                    background:
                      height > 0 ? (counting ? PATIENTS : MONEY) : "var(--border-strong)",
                    opacity: held === null || lit ? 1 : 0.45,
                  }}
                >
                  {missed > 0 && (
                    <span
                      className="block w-full"
                      style={{ height: `${missed}%`, background: MISSED }}
                    />
                  )}
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      {dense ? (
        <p className="flex justify-between text-[11px] text-[var(--text-subtle)] tabular">
          {[days.at(0), days.at(Math.floor(days.length / 2)), days.at(-1)].map(
            (each) =>
              each && (
                <span key={each.date}>
                  {new Date(`${each.date}T00:00:00`).toLocaleDateString("en-IN", {
                    month: "short",
                    year: "2-digit",
                  })}
                </span>
              ),
          )}
        </p>
      ) : (
        <ul
          className="flex gap-[3px] text-[11px] text-[var(--text-subtle)] tabular"
          role="list"
        >
          {days.map((each, index) => (
            <li key={each.date} className="min-w-0 flex-1 truncate text-center">
              {index % every === 0 || index === days.length - 1
                ? new Date(`${each.date}T00:00:00`).getDate()
                : ""}
            </li>
          ))}
        </ul>
      )}
    </figure>
  );
}

/** When people actually turn up, by the clinic's clock. */
export function HourChart({ hours }: { hours: HourLine[] }) {
  const most = tallest(hours.map((hour) => hour.seen));
  return (
    <ul className="flex flex-col gap-1.5 px-5 py-4" role="list">
      {hours.map((hour) => (
        <li key={hour.hour} className="flex items-center gap-3">
          <span className="w-16 shrink-0 text-right text-[13px] text-[var(--text-muted)] tabular">
            {clockFace(hour.hour)}
          </span>
          <span className="h-4 min-w-0 flex-1 rounded-[3px] bg-[var(--surface-sunken)]">
            <span
              className="block h-full rounded-[3px]"
              style={{
                width: `${Math.max(2, (hour.seen / most) * 100)}%`,
                background: PATIENTS,
              }}
            />
          </span>
          <span className="w-8 shrink-0 text-[13px] tabular">{hour.seen}</span>
        </li>
      ))}
    </ul>
  );
}

function clockFace(hour: number): string {
  const suffix = hour < 12 ? "am" : "pm";
  const shown = hour % 12 === 0 ? 12 : hour % 12;
  return `${shown} ${suffix}`;
}
