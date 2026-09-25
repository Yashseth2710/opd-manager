"use client";

import { Loader2, RotateCw } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { STATUS_WORDS, whole, type ClinicStatus } from "@/lib/platform";

const STATUS_TONE: Record<ClinicStatus, string> = {
  pending: "var(--color-state-scheduled)",
  active: "var(--color-state-completed)",
  suspended: "var(--color-state-noshow)",
};

export function StatusBadge({ status }: { status: ClinicStatus }) {
  const tone = STATUS_TONE[status];
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2 py-0.5 text-[12px] font-medium whitespace-nowrap"
      style={{
        color: tone,
        borderColor: `color-mix(in srgb, ${tone} 35%, transparent)`,
        backgroundColor: `color-mix(in srgb, ${tone} 9%, transparent)`,
      }}
    >
      <span aria-hidden className="size-1.5 rounded-full" style={{ backgroundColor: tone }} />
      {STATUS_WORDS[status]}
    </span>
  );
}

/**
 * How much of a plan's allowance a clinic has used. Past four fifths it
 * turns amber, and at the cap it turns red, which is when the clinic starts
 * being told no.
 */
export function Meter({
  label,
  used,
  limit,
  unit,
  fullNote = "Full. The clinic is being told no until this changes.",
}: {
  label: string;
  used: number;
  limit: number | null;
  unit?: string;
  fullNote?: string;
}) {
  const share = limit ? Math.min(used / limit, 1) : 0;
  const full = limit !== null && used >= limit;
  const tone = full
    ? "var(--color-state-noshow)"
    : share >= 0.8
      ? "var(--color-state-waiting)"
      : "var(--color-state-consulting)";
  const suffix = unit ? ` ${unit}` : "";

  return (
    <div>
      <div className="flex items-baseline justify-between gap-3 text-[14px]">
        <span className="text-[var(--text-muted)]">{label}</span>
        <span className="shrink-0 tabular">
          <span className="font-semibold">
            {whole(used)}
            {suffix}
          </span>
          <span className="text-[var(--text-subtle)]">
            {limit === null ? " of no limit" : ` of ${whole(limit)}${suffix}`}
          </span>
        </span>
      </div>
      {limit !== null && (
        <div
          role="meter"
          aria-label={label}
          aria-valuemin={0}
          aria-valuemax={limit}
          aria-valuenow={used}
          className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-[var(--surface-sunken)]"
        >
          <span
            className="block h-full rounded-full transition-[width] duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]"
            style={{
              width: `${Math.max(share * 100, used > 0 ? 2 : 0)}%`,
              backgroundColor: tone,
            }}
          />
        </div>
      )}
      {full && <p className="mt-1 text-[12px] text-[var(--color-state-noshow)]">{fullNote}</p>}
    </div>
  );
}

export function Loading({ what }: { what: string }) {
  return (
    <div className="flex min-h-[40vh] items-center justify-center gap-3 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">{what}</span>
    </div>
  );
}

export function Failed({ what, retry }: { what: string; retry: () => void }) {
  return (
    <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-12 text-center">
      <h2 className="text-[17px] font-semibold tracking-tight">{what} did not load</h2>
      <p className="mx-auto mt-1.5 max-w-[46ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
        The server could not be reached, or it refused. Nothing was changed.
      </p>
      <button
        type="button"
        onClick={retry}
        className="mt-5 inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-4 py-2 text-[14px] font-medium transition-colors hover:bg-[var(--surface-sunken)]"
      >
        <RotateCw className="size-4" />
        Try again
      </button>
    </div>
  );
}

export function Empty({
  heading,
  body,
  action,
}: {
  heading: string;
  body: string;
  action?: { label: string; href?: Route; onClick?: () => void };
}) {
  const style =
    "mt-5 inline-flex rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]";
  return (
    <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-14 text-center">
      <h2 className="text-[17px] font-semibold tracking-tight text-balance">{heading}</h2>
      <p className="mx-auto mt-1.5 max-w-[46ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
        {body}
      </p>
      {action?.href ? (
        <Link href={action.href} className={style}>
          {action.label}
        </Link>
      ) : action?.onClick ? (
        <button type="button" onClick={action.onClick} className={style}>
          {action.label}
        </button>
      ) : null}
    </div>
  );
}

export function shortDate(value: string): string {
  return new Date(value).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}
