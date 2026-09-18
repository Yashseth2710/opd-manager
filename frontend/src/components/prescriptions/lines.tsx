"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, Plus, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import {
  DOSE_PATTERNS,
  MAX_LINES,
  suggestMedicines,
  TIMING_WORDS,
  type MedicineLine,
  type MedicineSuggestion,
  type Timing,
} from "@/lib/prescriptions";

/** A line on screen. The key only keeps React's rows straight. */
export type EditableLine = MedicineLine & { key: string };

let made = 0;
export function newKey(): string {
  made += 1;
  return `line-${Date.now().toString(36)}-${made}`;
}

export function editable(lines: MedicineLine[]): EditableLine[] {
  return lines.map((line) => ({ ...line, key: newKey() }));
}

export function blankLine(): EditableLine {
  return {
    key: newKey(),
    medicine_name: "",
    presentation: null,
    dose: null,
    timing: null,
    duration_days: null,
    instructions: null,
  };
}

const tidy = (value: string | null) => {
  const trimmed = (value ?? "").trim();
  return trimmed ? trimmed : null;
};

/**
 * What gets sent: lines with a medicine named, trimmed the way the server
 * keeps them. A row whose medicine has not been typed yet stays on screen
 * and nowhere else.
 */
export function sendable(lines: EditableLine[]): MedicineLine[] {
  return lines
    .filter((line) => line.medicine_name.trim())
    .map((line) => ({
      medicine_name: line.medicine_name.trim(),
      presentation: tidy(line.presentation),
      dose: tidy(line.dose),
      timing: line.timing,
      duration_days: line.duration_days,
      instructions: tidy(line.instructions),
    }));
}

/** The server numbers problems by the lines it was sent; this finds them on screen. */
export function problemsByRow(
  lines: EditableLine[],
  fields: Record<string, string>,
): Record<string, Record<string, string>> {
  const shown = lines.filter((line) => line.medicine_name.trim());
  const out: Record<string, Record<string, string>> = {};
  for (const [path, message] of Object.entries(fields)) {
    const match = /^medicines\.(\d+)\.(\w+)$/.exec(path);
    if (!match) continue;
    const line = shown[Number(match[1])];
    if (!line) continue;
    out[line.key] = { ...out[line.key], [match[2]!]: message };
  }
  return out;
}

const FIELD =
  "w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] outline-none transition-[border-color,box-shadow] placeholder:text-[var(--text-subtle)] focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)] disabled:opacity-70 aria-invalid:border-[var(--color-state-noshow)]";

export function PrescriptionLines({
  lines,
  onChange,
  problems = {},
  disabled = false,
}: {
  lines: EditableLine[];
  onChange: (lines: EditableLine[]) => void;
  problems?: Record<string, Record<string, string>>;
  disabled?: boolean;
}) {
  const [focusKey, setFocusKey] = useState<string | null>(null);
  const full = lines.length >= MAX_LINES;

  const update = (key: string, changes: Partial<MedicineLine>) =>
    onChange(lines.map((line) => (line.key === key ? { ...line, ...changes } : line)));

  const add = () => {
    const line = blankLine();
    setFocusKey(line.key);
    onChange([...lines, line]);
  };

  return (
    <div className="flex flex-col gap-3">
      {lines.length > 0 && (
        <ol className="flex flex-col gap-3" aria-label="Medicines">
          {lines.map((line, index) => (
            <LineEditor
              key={line.key}
              line={line}
              position={index + 1}
              problems={problems[line.key] ?? {}}
              disabled={disabled}
              autoFocus={focusKey === line.key}
              onChange={(changes) => update(line.key, changes)}
              onRemove={() => onChange(lines.filter((each) => each.key !== line.key))}
            />
          ))}
        </ol>
      )}
      {full ? (
        <p className="text-[13px] text-[var(--text-muted)]">
          That is {MAX_LINES} medicines, as many as one prescription takes.
        </p>
      ) : (
        <button
          type="button"
          onClick={add}
          disabled={disabled}
          className="inline-flex w-fit items-center gap-2 rounded-[var(--radius-field)] border border-dashed border-[var(--border-strong)] px-3.5 py-2 text-[14px] font-medium transition-colors hover:border-solid hover:bg-[var(--surface-sunken)] disabled:opacity-60"
        >
          <Plus className="size-4" />
          {lines.length ? "Add another medicine" : "Add a medicine"}
        </button>
      )}
    </div>
  );
}

function LineEditor({
  line,
  position,
  problems,
  disabled,
  autoFocus,
  onChange,
  onRemove,
}: {
  line: EditableLine;
  position: number;
  problems: Record<string, string>;
  disabled: boolean;
  autoFocus: boolean;
  onChange: (changes: Partial<MedicineLine>) => void;
  onRemove: () => void;
}) {
  const id = useId();
  const named = line.medicine_name.trim() || `Medicine ${position}`;
  return (
    <li className="rounded-[var(--radius-field)] border border-[var(--border)] bg-[var(--surface)] p-3.5">
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="mt-2 w-5 shrink-0 text-right font-mono text-[13px] text-[var(--text-subtle)] tabular"
        >
          {position}
        </span>
        <div className="grid min-w-0 flex-1 gap-3 sm:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
          <MedicinePicker
            label={`Medicine ${position}`}
            value={line.medicine_name}
            disabled={disabled}
            autoFocus={autoFocus}
            error={problems.medicine_name}
            onType={(medicine_name) => onChange({ medicine_name })}
            onPick={(picked) =>
              onChange({ medicine_name: picked.name, presentation: picked.presentation })
            }
          />
          <div className="flex flex-col gap-1">
            <label htmlFor={`${id}-form`} className="text-[12px] text-[var(--text-muted)]">
              Form and strength
            </label>
            <input
              id={`${id}-form`}
              value={line.presentation ?? ""}
              maxLength={200}
              disabled={disabled}
              onChange={(event) => onChange({ presentation: event.target.value })}
              className={FIELD}
            />
          </div>
          <div className="flex flex-col gap-1 sm:col-span-2">
            <label htmlFor={`${id}-dose`} className="text-[12px] text-[var(--text-muted)]">
              Dose
            </label>
            <div className="flex flex-wrap items-center gap-2">
              <input
                id={`${id}-dose`}
                value={line.dose ?? ""}
                maxLength={40}
                disabled={disabled}
                aria-invalid={Boolean(problems.dose)}
                aria-describedby={problems.dose ? `${id}-dose-error` : undefined}
                onChange={(event) => onChange({ dose: event.target.value })}
                className={`${FIELD} max-w-[10rem] font-mono tabular`}
              />
              <div className="flex flex-wrap gap-1.5" role="group" aria-label="Common doses">
                {DOSE_PATTERNS.map((pattern) => (
                  <button
                    key={pattern}
                    type="button"
                    disabled={disabled}
                    aria-pressed={line.dose === pattern}
                    onClick={() => onChange({ dose: pattern })}
                    className={`rounded-full border px-2.5 py-1 font-mono text-[13px] tabular transition-colors ${
                      line.dose === pattern
                        ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-fg)]"
                        : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
                    }`}
                  >
                    {pattern}
                  </button>
                ))}
              </div>
            </div>
            {problems.dose && (
              <p
                id={`${id}-dose-error`}
                className="text-[13px] text-[var(--color-state-noshow)]"
              >
                {problems.dose}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-3 sm:col-span-2">
            <label className="flex min-w-[9rem] flex-1 flex-col gap-1">
              <span className="text-[12px] text-[var(--text-muted)]">When</span>
              <select
                value={line.timing ?? ""}
                disabled={disabled}
                onChange={(event) =>
                  onChange({ timing: (event.target.value || null) as Timing | null })
                }
                className={`${FIELD} py-[0.44rem]`}
              >
                <option value="">Not said</option>
                {(Object.keys(TIMING_WORDS) as Timing[]).map((timing) => (
                  <option key={timing} value={timing}>
                    {TIMING_WORDS[timing]}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex w-28 flex-col gap-1">
              <span className="text-[12px] text-[var(--text-muted)]">For how many days</span>
              <input
                type="number"
                inputMode="numeric"
                min={1}
                max={365}
                value={line.duration_days ?? ""}
                disabled={disabled}
                aria-invalid={Boolean(problems.duration_days)}
                onChange={(event) => {
                  const days = Number.parseInt(event.target.value, 10);
                  onChange({
                    duration_days: Number.isNaN(days) ? null : Math.min(365, Math.max(1, days)),
                  });
                }}
                className={`${FIELD} tabular`}
              />
            </label>
            <label className="flex min-w-[12rem] flex-[2] flex-col gap-1">
              <span className="text-[12px] text-[var(--text-muted)]">Note for the patient</span>
              <input
                value={line.instructions ?? ""}
                maxLength={200}
                disabled={disabled}
                placeholder="Anything the patient should know"
                onChange={(event) => onChange({ instructions: event.target.value })}
                className={FIELD}
              />
            </label>
          </div>
        </div>
        <button
          type="button"
          onClick={onRemove}
          disabled={disabled}
          aria-label={`Remove ${named}`}
          className="grid size-8 shrink-0 place-items-center rounded-[6px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
        >
          <X className="size-4" />
        </button>
      </div>
    </li>
  );
}

/**
 * The medicine's name, typed freely, with what the clinic has written
 * before and the published list offered underneath as it is typed.
 */
function MedicinePicker({
  label,
  value,
  disabled,
  autoFocus,
  error,
  onType,
  onPick,
}: {
  label: string;
  value: string;
  disabled: boolean;
  autoFocus: boolean;
  error?: string;
  onType: (value: string) => void;
  onPick: (picked: MedicineSuggestion) => void;
}) {
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [asked, setAsked] = useState("");

  // Asks once the typing pauses, not on every key.
  useEffect(() => {
    const typed = value.trim();
    const timer = setTimeout(() => setAsked(typed), 180);
    return () => clearTimeout(timer);
  }, [value]);

  useEffect(() => {
    if (autoFocus) input.current?.focus();
  }, [autoFocus]);

  const suggestions = useQuery({
    queryKey: ["medicines", asked.toLowerCase()],
    queryFn: () => suggestMedicines(asked),
    enabled: open && asked.length >= 2,
    staleTime: 60_000,
    retry: false,
  });
  const options = suggestions.data ?? [];
  const showing = open && asked.length >= 2;

  const pick = (option: MedicineSuggestion) => {
    onPick(option);
    setOpen(false);
  };

  return (
    <div className="relative flex flex-col gap-1">
      <label htmlFor={`${id}-name`} className="text-[12px] text-[var(--text-muted)]">
        {label}
      </label>
      <input
        ref={input}
        id={`${id}-name`}
        role="combobox"
        aria-expanded={showing && options.length > 0}
        aria-controls={`${id}-options`}
        aria-autocomplete="list"
        aria-activedescendant={
          showing && options[active] ? `${id}-option-${active}` : undefined
        }
        aria-invalid={Boolean(error)}
        autoComplete="off"
        value={value}
        maxLength={200}
        disabled={disabled}
        placeholder="Start typing a medicine"
        onChange={(event) => {
          onType(event.target.value);
          setOpen(true);
          setActive(0);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 120)}
        onKeyDown={(event) => {
          if (!showing || options.length === 0) return;
          if (event.key === "ArrowDown") {
            event.preventDefault();
            setActive((at) => (at + 1) % options.length);
          } else if (event.key === "ArrowUp") {
            event.preventDefault();
            setActive((at) => (at - 1 + options.length) % options.length);
          } else if (event.key === "Enter") {
            event.preventDefault();
            const chosen = options[active];
            if (chosen) pick(chosen);
          } else if (event.key === "Escape") {
            setOpen(false);
          }
        }}
        className={`${FIELD} font-medium`}
      />
      {error && <p className="text-[13px] text-[var(--color-state-noshow)]">{error}</p>}
      {showing && (suggestions.isFetching || options.length > 0) && (
        <ul
          id={`${id}-options`}
          role="listbox"
          aria-label={`Medicines matching ${asked}`}
          className="absolute top-full right-0 left-0 z-20 mt-1 max-h-72 overflow-auto rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface-raised)] py-1 shadow-[0_12px_32px_-12px_rgb(8_15_26/0.35)]"
        >
          {options.length === 0 ? (
            <li className="flex items-center gap-2 px-3 py-2 text-[13px] text-[var(--text-muted)]">
              <Loader2 className="size-3.5 animate-spin" /> Looking…
            </li>
          ) : (
            options.map((option, index) => (
              <li
                key={`${option.name}|${option.presentation ?? ""}|${option.source}`}
                id={`${id}-option-${index}`}
                role="option"
                aria-selected={index === active}
                onMouseDown={(event) => {
                  event.preventDefault();
                  pick(option);
                }}
                // Moving, not entering: a list that opens under a resting pointer
                // must not quietly change which medicine Enter picks.
                onMouseMove={() => {
                  if (active !== index) setActive(index);
                }}
                className={`flex cursor-pointer items-baseline justify-between gap-3 px-3 py-1.5 text-[14px] ${
                  index === active ? "bg-[var(--accent-wash)]" : ""
                }`}
              >
                <span className="min-w-0">
                  <span className="font-medium">{option.name}</span>
                  {option.presentation && (
                    <span className="ml-2 text-[13px] text-[var(--text-muted)]">
                      {option.presentation}
                    </span>
                  )}
                </span>
                {option.source === "clinic" && (
                  <span className="shrink-0 text-[12px] text-[var(--text-muted)] tabular">
                    {option.times_prescribed === 1
                      ? "used once"
                      : `used ${option.times_prescribed} times`}
                  </span>
                )}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  );
}
