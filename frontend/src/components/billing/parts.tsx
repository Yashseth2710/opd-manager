"use client";

import { useId } from "react";
import { money } from "@/lib/clinic";
import { STATUS_TONE, STATUS_WORDS, type InvoiceStatus } from "@/lib/billing";

export const QUIET_BUTTON =
  "inline-flex items-center justify-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-60";

export const PRIMARY_BUTTON =
  "inline-flex items-center justify-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2 text-[14px] font-semibold text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-60";

export const ACCENT_BUTTON =
  "inline-flex items-center justify-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--accent-fg)] transition hover:brightness-105 disabled:opacity-60";

export const DANGER_BUTTON =
  "inline-flex items-center justify-center gap-2 rounded-[var(--radius-field)] bg-[var(--color-state-noshow)] px-3.5 py-2 text-[14px] font-semibold text-white transition hover:brightness-110 disabled:opacity-60";

export const FIELD =
  "w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] outline-none placeholder:text-[var(--text-subtle)] focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)] aria-invalid:border-[var(--color-state-noshow)]";

export function BillStatus({ status }: { status: InvoiceStatus }) {
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

/** An amount in the clinic's currency, set in figures that line up. */
export function Amount({
  value,
  currency = "INR",
  className = "",
}: {
  value: string;
  currency?: string;
  className?: string;
}) {
  return <span className={`font-mono tabular ${className}`}>{money(value, currency)}</span>;
}

export function Problem({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return (
    <p role="alert" className="text-[14px] text-[var(--color-state-noshow)]">
      {children}
    </p>
  );
}

/** A line of text with its label, and what is wrong with it said beneath. */
export function TextField({
  label,
  name,
  value,
  onChange,
  error,
  placeholder,
  maxLength = 200,
  autoFocus,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
  placeholder?: string;
  maxLength?: number;
  autoFocus?: boolean;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1.5 text-[13px] font-medium">
      <label htmlFor={id}>{label}</label>
      <input
        id={id}
        name={name}
        value={value}
        maxLength={maxLength}
        autoFocus={autoFocus}
        aria-invalid={Boolean(error)}
        aria-describedby={error ? `${id}-error` : undefined}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className={`${FIELD} font-normal`}
      />
      {error && (
        <span id={`${id}-error`} className="font-normal text-[var(--color-state-noshow)]">
          {error}
        </span>
      )}
    </div>
  );
}
