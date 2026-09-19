"use client";

import { ChevronRight } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { readableTime } from "@/lib/doctors";
import { bookingHref } from "@/lib/appointments";
import type { Counts, DueBack } from "@/lib/dashboard";
import { readablePhone } from "@/lib/patients";

export type Figure = { label: string; value: number; note?: React.ReactNode };

/** The day's counts, read left to right like the top line of a register. */
export function Figures({ figures }: { figures: Figure[] }) {
  return (
    <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--border)] sm:grid-cols-4">
      {figures.map((figure) => (
        <div key={figure.label} className="bg-[var(--surface)] px-5 py-4">
          <dt className="text-[13px] text-[var(--text-muted)]">{figure.label}</dt>
          <dd className="mt-1 font-mono text-[28px] leading-none font-semibold tabular">
            <CountUp value={figure.value} />
          </dd>
          {figure.note && (
            <dd className="mt-2 text-[13px] leading-snug text-[var(--text-muted)]">
              {figure.note}
            </dd>
          )}
        </div>
      ))}
    </dl>
  );
}

/**
 * Counts up once when the page opens. Later refreshes show the new figure
 * straight away: a number that climbs every half minute would read as a
 * change when nothing has.
 */
function CountUp({ value }: { value: number }) {
  const [shown, setShown] = useState(value);
  const counted = useRef(false);

  useEffect(() => {
    if (counted.current) {
      setShown(value);
      return;
    }
    counted.current = true;
    if (value === 0 || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    const started = performance.now();
    let frame = requestAnimationFrame(function step(now) {
      const progress = Math.min(1, (now - started) / 250);
      setShown(Math.round(value * (1 - (1 - progress) ** 3)));
      if (progress < 1) frame = requestAnimationFrame(step);
    });
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return <>{shown}</>;
}

export function clinicFigures(counts: Counts): Figure[] {
  return [
    {
      label: "Booked today",
      value: counts.booked,
      note:
        counts.to_come === 0 ? (
          counts.booked ? (
            "Everyone booked has arrived"
          ) : (
            "No appointments"
          )
        ) : (
          <>
            {counts.to_come} still to come
            {counts.late > 0 && <Late>, {counts.late} late</Late>}
          </>
        ),
    },
    {
      label: "Waiting now",
      value: counts.waiting,
      note: `${counts.with_doctor} with a doctor`,
    },
    {
      label: "Seen",
      value: counts.seen,
      note: !counts.seen
        ? "Nobody yet"
        : counts.walk_ins
          ? `${counts.walk_ins} of them walked in`
          : "All by appointment",
    },
    {
      label: "Did not stay",
      value: counts.no_shows,
      note: counts.no_shows ? "Never came, or left unseen" : "Nobody so far",
    },
  ];
}

export function Late({ children }: { children: React.ReactNode }) {
  return (
    <span className="font-medium text-[var(--color-marigold-700)] dark:text-[var(--color-marigold-300)]">
      {children}
    </span>
  );
}

/** A section of the day with its heading, a count, and the page it opens onto. */
export function Panel({
  id,
  title,
  count,
  more,
  children,
}: {
  id: string;
  title: string;
  count?: number;
  more?: { href: Route; label: string };
  children: React.ReactNode;
}) {
  return (
    <section
      aria-labelledby={id}
      className="min-w-0 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]"
    >
      <header className="flex items-baseline justify-between gap-3 border-b border-[var(--border)] px-5 py-3">
        <h2 id={id} className="flex items-baseline gap-2 text-[15px] font-semibold">
          {title}
          {count !== undefined && count > 0 && (
            <span className="font-normal text-[var(--text-subtle)] tabular">{count}</span>
          )}
        </h2>
        {more && (
          <Link
            href={more.href}
            className="inline-flex shrink-0 items-center gap-0.5 text-[13px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
          >
            {more.label}
            <ChevronRight className="size-3.5" />
          </Link>
        )}
      </header>
      {children}
    </section>
  );
}

export function Quiet({ children }: { children: React.ReactNode }) {
  return <p className="px-5 py-4 text-[14px] text-[var(--text-muted)]">{children}</p>;
}

export function Shown({ shown, total }: { shown: number; total: number }) {
  if (total <= shown) return null;
  return (
    <p className="border-t border-[var(--border)] px-5 py-2 text-[13px] text-[var(--text-muted)] tabular">
      The first {shown} of {total}.
    </p>
  );
}

const STATES: Record<DueBack["state"], { label: string; tone: string }> = {
  not_booked: { label: "Not booked", tone: "var(--color-state-waiting)" },
  booked: { label: "Booked", tone: "var(--color-state-confirmed)" },
  here: { label: "Here now", tone: "var(--color-state-consulting)" },
  seen: { label: "Seen", tone: "var(--color-state-completed)" },
};

/**
 * Patients a doctor asked to come back today. The ones with nothing booked
 * come first: those are the calls worth making.
 */
export function DueBackList({
  items,
  date,
  mayBook,
  showDoctor,
}: {
  items: DueBack[];
  date: string;
  mayBook: boolean;
  showDoctor: boolean;
}) {
  return (
    <ul className="divide-y divide-[var(--border)]">
      {items.map((item) => {
        const state = STATES[item.state];
        return (
          <li
            key={`${item.patient.id}-${item.consultation_id}`}
            className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-5 py-2.5"
          >
            <div className="min-w-0 flex-1">
              <Link
                href={`/patients/${item.patient.id}` as Route}
                className="block truncate text-[15px] font-medium underline-offset-4 hover:underline"
              >
                {item.patient.full_name}
              </Link>
              <p className="truncate text-[13px] text-[var(--text-muted)]">
                {[
                  item.patient.phone ? readablePhone(item.patient.phone) : null,
                  showDoctor ? `for ${item.doctor.display_name}` : null,
                  `asked on ${new Date(`${item.asked_on}T00:00:00`).toLocaleDateString(
                    "en-IN",
                    {
                      day: "numeric",
                      month: "short",
                    },
                  )}`,
                ]
                  .filter(Boolean)
                  .join(", ")}
              </p>
            </div>
            <span
              className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-medium"
              style={{
                borderColor: `color-mix(in srgb, ${state.tone} 50%, transparent)`,
                background: `color-mix(in srgb, ${state.tone} 12%, transparent)`,
              }}
            >
              <span
                aria-hidden
                className="size-1.5 rounded-full"
                style={{ background: state.tone }}
              />
              {state.label}
              {item.booked_for && ` for ${readableTime(item.booked_for)}`}
            </span>
            {item.state === "not_booked" && mayBook && (
              <Link
                href={
                  bookingHref({
                    patient: item.patient.id,
                    doctor: item.doctor.id,
                    date,
                  }) as Route
                }
                className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-2.5 py-1 text-[13px] font-medium transition-colors hover:border-[var(--color-marigold-400)] hover:bg-[var(--accent-wash)]"
              >
                Book
              </Link>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function Skeleton() {
  return (
    <div aria-hidden className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--border)] sm:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="bg-[var(--surface)] px-5 py-4">
            <span className="block h-3.5 w-20 animate-pulse rounded bg-[var(--surface-sunken)]" />
            <span className="mt-2 block h-7 w-10 animate-pulse rounded bg-[var(--surface-sunken)]" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {Array.from({ length: 2 }, (_, index) => (
          <div
            key={index}
            className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
          >
            <span className="block h-4 w-32 animate-pulse rounded bg-[var(--surface-sunken)]" />
            {Array.from({ length: 3 }, (_, row) => (
              <span
                key={row}
                className="mt-4 block h-8 w-full animate-pulse rounded bg-[var(--surface-sunken)]"
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
