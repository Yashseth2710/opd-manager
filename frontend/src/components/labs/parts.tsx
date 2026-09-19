"use client";

import { AlertCircle, ArrowDown, ArrowUp, Zap } from "lucide-react";
import { shortDate } from "@/lib/appointments";
import {
  FLAG_WORDS,
  rangeWords,
  STATUS_TONE,
  STATUS_WORDS,
  type Judgement,
  type LabStatus,
  type ReportedValue,
} from "@/lib/labs";

export function LabStatusChip({ status }: { status: LabStatus }) {
  const tone = STATUS_TONE[status];
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-medium whitespace-nowrap text-[var(--text)]"
      style={{
        borderColor: `color-mix(in srgb, ${tone} 50%, transparent)`,
        background: `color-mix(in srgb, ${tone} 12%, transparent)`,
      }}
    >
      <span aria-hidden className="size-1.5 rounded-full" style={{ background: tone }} />
      {STATUS_WORDS[status]}
    </span>
  );
}

export function Urgent() {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--color-state-urgent)_12%,transparent)] px-2 py-0.5 text-[12px] font-semibold text-[var(--color-state-urgent)]">
      <Zap aria-hidden className="size-3" />
      Urgent
    </span>
  );
}

/** An arrow for a number out of range, a mark for a word that should not be. */
export function Judged({ flag, spoken = false }: { flag: Judgement; spoken?: boolean }) {
  const Mark = flag === "high" ? ArrowUp : flag === "low" ? ArrowDown : AlertCircle;
  return (
    <span className="inline-flex items-center gap-0.5 text-[var(--color-state-noshow)]">
      <Mark aria-hidden className="size-3.5 shrink-0" strokeWidth={2.5} />
      <span className={spoken ? "text-[12px] font-medium" : "sr-only"}>{FLAG_WORDS[flag]}</span>
    </span>
  );
}

/** "2 outside range", said only when there is something to say. */
export function FlaggedCount({ count }: { count: number }) {
  if (count === 0) return null;
  return (
    <span className="inline-flex items-center gap-1 text-[12px] font-medium text-[var(--color-state-noshow)]">
      <AlertCircle aria-hidden className="size-3.5" />
      {count === 1 ? "1 outside range" : `${count} outside range`}
    </span>
  );
}

/**
 * The report's values in the order the lab printed them, each with its
 * range, and last time's figure beside it where the same test was done
 * before in the same units.
 */
export function ResultTable({ values }: { values: ReportedValue[] }) {
  if (values.length === 0) return null;
  const earlierDay = values.find((value) => value.earlier)?.earlier?.reported_on;
  return (
    // Positioned, so the words kept for screen readers scroll with the table
    // instead of widening the page.
    <div className="relative -mx-1 overflow-x-auto px-1">
      <table className="w-full border-collapse text-[14px]">
        <caption className="sr-only">Values on the report</caption>
        <thead>
          <tr className="text-left text-[12px] text-[var(--text-subtle)]">
            <th scope="col" className="py-1.5 pr-3 font-medium">
              Test
            </th>
            <th scope="col" className="py-1.5 pr-3 font-medium">
              Result
            </th>
            <th scope="col" className="py-1.5 pr-3 font-medium">
              Normal
            </th>
            {earlierDay && (
              <th scope="col" className="py-1.5 font-medium whitespace-nowrap">
                Last time
                <span className="block font-normal">{shortDate(earlierDay)}</span>
              </th>
            )}
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--border)]">
          {values.map((value) => (
            <tr key={value.name} className="align-baseline">
              <th scope="row" className="py-2 pr-3 text-left font-normal">
                {value.name}
              </th>
              <td className="py-2 pr-3 whitespace-nowrap tabular">
                <span
                  className={`inline-flex items-baseline gap-1 ${
                    value.flag
                      ? "font-semibold text-[var(--color-state-noshow)]"
                      : "font-medium"
                  }`}
                >
                  {value.value}
                  {value.unit && (
                    <span className="text-[12px] font-normal text-[var(--text-muted)]">
                      {value.unit}
                    </span>
                  )}
                  {value.flag && <Judged flag={value.flag} spoken />}
                </span>
              </td>
              <td className="py-2 pr-3 text-[13px] whitespace-nowrap text-[var(--text-muted)] tabular">
                {rangeWords(value) || <span aria-label="No range given">–</span>}
              </td>
              {earlierDay && (
                <td className="py-2 text-[13px] whitespace-nowrap tabular">
                  {value.earlier ? (
                    <span
                      className={`inline-flex items-baseline gap-0.5 ${
                        value.earlier.flag ? "text-[var(--color-state-noshow)]" : ""
                      }`}
                    >
                      {value.earlier.value}
                      {value.earlier.flag && <Judged flag={value.earlier.flag} />}
                    </span>
                  ) : (
                    <span className="text-[var(--text-subtle)]" aria-label="Not measured">
                      –
                    </span>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
