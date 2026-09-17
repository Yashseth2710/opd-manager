"use client";

import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Clock } from "lucide-react";
import { useState } from "react";
import {
  countSlots,
  getAvailability,
  readableDate,
  readableTime,
  shiftDate,
  todayISO,
} from "@/lib/doctors";

/**
 * A day of the rota, worked out rather than stored.
 *
 * It answers the question a receptionist actually has — "can I put someone
 * in with her on Thursday?" — which a weekly table of hours does not, once
 * a break and a morning off are in the way.
 */
export function Availability({ doctorId }: { doctorId: string }) {
  const [date, setDate] = useState(todayISO);

  const day = useQuery({
    queryKey: ["availability", doctorId, date],
    queryFn: () => getAvailability(doctorId, date),
    retry: false,
  });

  const isToday = date === todayISO();

  return (
    <section className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-3.5">
        <h2 className="flex items-center gap-2 text-[15px] font-semibold tracking-tight">
          <Clock className="size-4 text-[var(--text-muted)]" />
          Free times
        </h2>

        <div className="flex items-center gap-1">
          <Step
            label="Previous day"
            onClick={() => setDate(shiftDate(date, -1))}
            icon={<ChevronLeft className="size-4" />}
          />
          <input
            type="date"
            aria-label="Show this day"
            value={date}
            onChange={(event) => setDate(event.target.value || todayISO())}
            className="rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-[13px] tabular transition-colors hover:border-[var(--color-paper-400)]"
          />
          <Step
            label="Next day"
            onClick={() => setDate(shiftDate(date, 1))}
            icon={<ChevronRight className="size-4" />}
          />
        </div>
      </header>

      <div className="px-5 py-4">
        <p className="mb-3 text-[13px] text-[var(--text-muted)]">
          {day.data ? `${day.data.day_name}, ` : ""}
          {readableDate(date)}
          {isToday && " · today"}
        </p>

        {day.isPending ? (
          <div aria-hidden className="flex flex-wrap gap-1.5">
            {Array.from({ length: 8 }, (_, index) => (
              <span
                key={index}
                className="h-8 w-20 animate-pulse rounded-[var(--radius-field)] bg-[var(--surface-sunken)]"
              />
            ))}
          </div>
        ) : day.isError ? (
          <p className="py-4 text-[14px] text-[var(--text-muted)]">
            That day did not load. Try again in a moment.
          </p>
        ) : day.data.slots.length === 0 ? (
          <p className="py-4 text-[14px] text-[var(--text-muted)]">
            {day.data.reason ?? "Nothing free."}
          </p>
        ) : (
          <>
            <ul className="flex flex-wrap gap-1.5">
              {day.data.slots.map((slot) => (
                <li
                  key={slot.start_time}
                  title={`${readableTime(slot.start_time)} to ${readableTime(slot.end_time)}`}
                  className="rounded-[var(--radius-field)] border border-[var(--border)] bg-[var(--surface-sunken)] px-2.5 py-1.5 text-[13px] tabular"
                >
                  {readableTime(slot.start_time)}
                </li>
              ))}
            </ul>
            <p className="mt-3 text-[13px] text-[var(--text-muted)]">
              {countSlots(day.data.slots)}
            </p>
          </>
        )}
      </div>
    </section>
  );
}

function Step({
  label,
  onClick,
  icon,
}: {
  label: string;
  onClick: () => void;
  icon: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label={label}
      className="rounded-[var(--radius-field)] p-1.5 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
    >
      {icon}
    </button>
  );
}
