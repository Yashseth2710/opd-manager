"use client";

import { ArrowDownRight, ArrowUpRight } from "lucide-react";
import { money } from "@/lib/clinic";
import { movement } from "@/lib/reports";

/** A section with its heading and, where it helps, a line saying what it is. */
export function Panel({
  id,
  title,
  blurb,
  action,
  children,
}: {
  id: string;
  title: string;
  blurb?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-labelledby={id}
      className="flex min-w-0 flex-col rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]"
    >
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 border-b border-[var(--border)] px-5 py-3">
        <h2 id={id} className="text-[15px] font-semibold">
          {title}
        </h2>
        {action}
        {blurb && (
          <p className="w-full text-[13px] leading-snug text-[var(--text-muted)]">{blurb}</p>
        )}
      </header>
      {children}
    </section>
  );
}

export function Quiet({ children }: { children: React.ReactNode }) {
  return <p className="px-5 py-6 text-[14px] text-[var(--text-muted)]">{children}</p>;
}

export type Headline = {
  label: string;
  value: string;
  /** Read as a quantity, so it is set in the mono face. */
  note?: React.ReactNode;
};

export function Headlines({ figures }: { figures: Headline[] }) {
  return (
    // Two across is right on a phone, but a lakh set in the mono face does
    // not fit half of a 320px screen, so the narrowest width gets one.
    <dl className="grid grid-cols-1 gap-px overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--border)] min-[360px]:grid-cols-2 sm:grid-cols-4">
      {figures.map((figure) => (
        <div key={figure.label} className="bg-[var(--surface)] px-5 py-4">
          <dt className="text-[13px] text-[var(--text-muted)]">{figure.label}</dt>
          <dd className="mt-1 font-mono text-[24px] leading-none font-semibold tabular">
            {figure.value}
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
 * How a figure sits against the stretch of the same length before it. Up is
 * not coloured green: more patients on a Tuesday is not a result, and a
 * clinic that reads its own dashboard as a scoreboard starts chasing it.
 */
export function Against({
  now,
  before,
  currency,
  words,
}: {
  now: number;
  before: number;
  currency?: string;
  words: string;
}) {
  const moved = movement(now, before);
  const said = currency ? money(String(before), currency) : String(before);
  return (
    <span className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5">
      {moved && (
        <span className="inline-flex items-center gap-0.5 font-medium text-[var(--text)]">
          {moved.up ? (
            <ArrowUpRight className="size-3.5" aria-hidden />
          ) : (
            <ArrowDownRight className="size-3.5" aria-hidden />
          )}
          {moved.words}
        </span>
      )}
      <span>
        {words} <span className="tabular">{said}</span>
      </span>
    </span>
  );
}

/** A proportion, drawn as a rule under the row it belongs to. */
export function Share({ of, tone }: { of: number; tone: string }) {
  return (
    <span aria-hidden className="mt-2 block h-1 rounded-full bg-[var(--surface-sunken)]">
      <span
        className="block h-full rounded-full transition-[width] duration-[220ms] ease-[cubic-bezier(0.32,0.72,0,1)]"
        style={{ width: `${Math.max(1, Math.round(of * 100))}%`, background: tone }}
      />
    </span>
  );
}
