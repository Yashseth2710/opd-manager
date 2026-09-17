"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertCircle, Eye, EyeOff, Loader2 } from "lucide-react";
import { useId, useState } from "react";
import { request } from "@/lib/api";

export function Heading({ title, blurb }: { title: string; blurb?: string }) {
  return (
    <div className="mb-7">
      <h1 className="text-[26px] leading-tight font-semibold tracking-tight text-balance">
        {title}
      </h1>
      {blurb && (
        <p className="mt-2 text-[15px] leading-relaxed text-[var(--text-muted)]">{blurb}</p>
      )}
    </div>
  );
}

type FieldProps = {
  label: string;
  name: string;
  type?: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  hint?: React.ReactNode;
  autoComplete?: string;
  required?: boolean;
  autoFocus?: boolean;
  placeholder?: string;
};

export function Field({
  label,
  name,
  type = "text",
  value,
  onChange,
  error,
  hint,
  autoComplete,
  required,
  autoFocus,
  placeholder,
}: FieldProps) {
  const id = useId();
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  const [revealed, setRevealed] = useState(false);
  const isPassword = type === "password";

  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-[14px] font-medium">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          name={name}
          type={isPassword && revealed ? "text" : type}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          autoComplete={autoComplete}
          required={required}
          autoFocus={autoFocus}
          placeholder={placeholder}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          className={`w-full rounded-[var(--radius-field)] border bg-[var(--surface)] px-3 py-2.5 text-[15px] transition-colors placeholder:text-[var(--text-subtle)] ${
            error
              ? "border-[var(--color-state-noshow)]"
              : "border-[var(--border-strong)] hover:border-[var(--color-paper-400)]"
          } ${isPassword ? "pr-11" : ""}`}
        />
        {isPassword && (
          <button
            type="button"
            onClick={() => setRevealed((shown) => !shown)}
            aria-label={revealed ? "Hide password" : "Show password"}
            className="absolute top-1/2 right-1 -translate-y-1/2 rounded-[4px] p-2 text-[var(--text-subtle)] transition-colors hover:text-[var(--text)]"
          >
            {revealed ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
          </button>
        )}
      </div>
      {error ? (
        <p id={`${id}-error`} className="mt-1.5 text-[13px] text-[var(--color-state-noshow)]">
          {error}
        </p>
      ) : hint ? (
        <div id={`${id}-hint`} className="mt-1.5 text-[13px] text-[var(--text-muted)]">
          {hint}
        </div>
      ) : null}
    </div>
  );
}

/** The one thing on the page wearing the accent. */
export function Submit({
  busy,
  children,
  busyLabel,
}: {
  busy: boolean;
  children: React.ReactNode;
  busyLabel: string;
}) {
  return (
    <button
      type="submit"
      disabled={busy}
      className="inline-flex w-full items-center justify-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2.5 text-[15px] font-semibold text-[var(--color-ink-900)] transition-[filter,transform] duration-150 ease-[var(--ease-out-quint)] hover:brightness-[1.06] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60 disabled:hover:brightness-100"
    >
      {busy && <Loader2 className="size-4 animate-spin" />}
      {busy ? busyLabel : children}
    </button>
  );
}

export function Problem({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="alert"
      className="mb-5 flex gap-2.5 rounded-[var(--radius-field)] border border-[color-mix(in_srgb,var(--color-state-noshow)_35%,transparent)] bg-[color-mix(in_srgb,var(--color-state-noshow)_8%,transparent)] px-3.5 py-3 text-[14px] leading-relaxed"
    >
      <AlertCircle className="mt-0.5 size-4 shrink-0 text-[var(--color-state-noshow)]" />
      <div>{children}</div>
    </div>
  );
}

export function Aside({ children }: { children: React.ReactNode }) {
  return <p className="mt-6 text-center text-[14px] text-[var(--text-muted)]">{children}</p>;
}

/**
 * Shown wherever the application would normally send an email but has no
 * provider configured.
 *
 * It reports a property of the installation, never anything about the
 * address just typed, and it renders before the form is submitted. That is
 * what keeps it from becoming a way to discover which addresses have
 * accounts.
 */
export function DemoEmailNotice() {
  const { data } = useQuery({
    queryKey: ["email-configured"],
    queryFn: () => request<{ email_configured: boolean }>("/health"),
    staleTime: 5 * 60 * 1000,
  });

  if (data?.email_configured !== false) return null;

  return (
    <div className="mt-6 rounded-[var(--radius-field)] border border-dashed border-[var(--border-strong)] px-3.5 py-3 text-[13px] leading-relaxed text-[var(--text-muted)]">
      No email provider is set up here yet, so links are written to the server log instead of
      being sent.
    </div>
  );
}
