"use client";

import { useEffect, useId, useRef } from "react";
import { RANGES, type Range } from "@/lib/reports";

const CHIP =
  "rounded-full border px-3.5 py-1.5 text-[14px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]";

const FIELD =
  "rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-1.5 text-[14px] outline-none focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)]";

export const LONGEST_DAYS = 366;

/** What is wrong with a pair of chosen dates, in the words the server uses. */
export function wrongWith(from: string, to: string): string | null {
  if (!from || !to) return "Choose both a first day and a last day.";
  if (to < from) return "The last day comes before the first one.";
  const apart =
    (new Date(`${to}T00:00:00`).getTime() - new Date(`${from}T00:00:00`).getTime()) /
      86_400_000 +
    1;
  if (apart > LONGEST_DAYS) return "That is more than a year. Ask for a shorter stretch.";
  return null;
}

export function RangePicker({
  range,
  from,
  to,
  today,
  onRange,
  onDates,
}: {
  range: Range;
  from: string;
  to: string;
  today: string;
  onRange: (range: Range) => void;
  onDates: (from: string, to: string) => void;
}) {
  const firstId = useId();
  const lastId = useId();
  const wrong = range === "custom" ? wrongWith(from, to) : null;

  /**
   * What the two boxes hold right now.
   *
   * The address is where the chosen dates live, and writing to it is not
   * instant. Changing one box and then the other quickly enough sent the
   * second change with the first box's old value, and the first change was
   * lost. Each box is read from here instead, which is written the moment
   * anything is typed.
   */
  const held = useRef({ from, to });
  useEffect(() => {
    held.current = { from, to };
  }, [from, to]);

  const chooseDay = (which: "from" | "to") => (value: string) => {
    const next = { ...held.current, [which]: value };
    held.current = next;
    onDates(next.from, next.to);
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2" role="group" aria-label="How far back to look">
        {RANGES.map((each) => {
          const chosen = each.value === range;
          return (
            <button
              key={each.value}
              type="button"
              aria-pressed={chosen}
              onClick={() => onRange(each.value)}
              className={`${CHIP} ${
                chosen
                  ? "border-[var(--color-marigold-400)] bg-[var(--accent-wash)] font-medium"
                  : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
              }`}
            >
              {each.label}
            </button>
          );
        })}
      </div>

      {range === "custom" && (
        <div className="flex flex-wrap items-end gap-3">
          <div className="flex flex-col gap-1">
            <label htmlFor={firstId} className="text-[13px] font-medium">
              From
            </label>
            <input
              id={firstId}
              type="date"
              value={from}
              max={today}
              onChange={(event) => chooseDay("from")(event.target.value)}
              className={FIELD}
            />
          </div>
          <div className="flex flex-col gap-1">
            <label htmlFor={lastId} className="text-[13px] font-medium">
              To
            </label>
            <input
              id={lastId}
              type="date"
              value={to}
              max={today}
              onChange={(event) => chooseDay("to")(event.target.value)}
              className={FIELD}
            />
          </div>
          {wrong && (
            <p role="alert" className="text-[14px] text-[var(--color-state-noshow)]">
              {wrong}
            </p>
          )}
        </div>
      )}
    </div>
  );
}
