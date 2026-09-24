"use client";

import { useMutation } from "@tanstack/react-query";
import { Info, Loader2, Plus, X } from "lucide-react";
import { useId, useState } from "react";
import { Judged } from "@/components/labs/parts";
import { ApiFailure } from "@/lib/api";
import {
  judge,
  MAX_VALUES,
  recordResult,
  type LabOrder,
  type LabResult,
  type ResultValue,
} from "@/lib/labs";

type Line = {
  key: string;
  /** Came with the test, so its name is shown rather than typed. */
  fixed: boolean;
  name: string;
  value: string;
  unit: string;
  low: string;
  high: string;
  expected: string;
};

let made = 0;
const newKey = () => `value-${++made}`;

const text = (value: string | number | null | undefined) =>
  value === null || value === undefined ? "" : String(value);

function toLine(line: Omit<ResultValue, "value">, value: string): Line {
  return {
    key: newKey(),
    fixed: true,
    name: line.name,
    value,
    unit: text(line.unit),
    low: text(line.low),
    high: text(line.high),
    expected: text(line.expected),
  };
}

/** What was typed in before, when putting a report right; otherwise the
 * lines this test's report usually has. */
function linesOf(order: LabOrder): Line[] {
  if (order.values.length) return order.values.map((line) => toLine(line, line.value));
  return order.template.map((line) => toLine(line, ""));
}

/** Why the list could not fill some ranges in for this patient. */
function whyBlank(order: LabOrder): string {
  const years = /^(\d+) y$/.exec(order.patient.age ?? "");
  const child = !years || Number(years[1]) < 18;
  const known = order.patient.gender === "male" || order.patient.gender === "female";
  if (child && !known)
    return "a child's normal depends on their age, and their sex is not recorded";
  if (child) return "a child's normal depends on their age";
  return "they depend on sex, which is not recorded for this patient";
}

const tidy = (value: string) => {
  const trimmed = value.trim();
  return trimmed ? trimmed : null;
};

const number = (value: string) => {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
};

// Test, result, unit, range, and the button that takes a line off.
const COLUMNS = "md:grid-cols-[minmax(0,1.3fr)_minmax(8rem,1fr)_5.5rem_9rem_2rem]";

const FIELD =
  "w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1.5 text-[15px] outline-none transition-[border-color,box-shadow] placeholder:text-[var(--text-subtle)] focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)] disabled:opacity-70 aria-invalid:border-[var(--color-state-noshow)]";

/**
 * The lab's report, typed in. Lines left empty are taken off rather than
 * refused, since labs differ in what a panel carries; the range comes filled
 * in where the list knows it, and is changed to the lab's own if that
 * differs.
 */
export function ResultForm({
  order,
  onSaved,
  onCancel,
}: {
  order: LabOrder;
  onSaved: (order: LabOrder) => void;
  onCancel?: () => void;
}) {
  const id = useId();
  const [lines, setLines] = useState<Line[]>(() => linesOf(order));
  const [reportedOn, setReportedOn] = useState(order.reported_on ?? order.clinic_today);
  const [labName, setLabName] = useState(order.lab_name ?? "");
  const [findings, setFindings] = useState(order.findings ?? "");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  // The line just added, which takes the cursor.
  const [added, setAdded] = useState<string | null>(null);

  const earliest = order.ordered_on;
  const today = order.clinic_today;
  // A listed test with no values, such as a scan or an ECG, is only words.
  // One the doctor typed in may be either, so it gets both.
  const wordsOnly =
    order.test_code !== null && order.template.length === 0 && order.values.length === 0;
  const listedWithValues = order.test_code !== null && !wordsOnly;

  // The lines that go, in the order they go, so the server's numbering of a
  // problem can be traced back to the line on screen.
  const sent = lines.filter((line) => line.value.trim());

  const save = useMutation({
    mutationFn: (result: LabResult) => recordResult(order.id, result),
    onSuccess: (saved) => {
      setFields({});
      setProblem(null);
      onSaved(saved);
    },
    onError: (error) => {
      if (error instanceof ApiFailure) {
        setFields(error.fields ?? {});
        setProblem(error.message);
      } else {
        setProblem("That did not go through. Try again in a moment.");
      }
    },
  });

  const submit = () => {
    const local: Record<string, string> = {};
    const values: ResultValue[] = sent.map((line, index) => {
      const low = number(line.low);
      const high = number(line.high);
      if (Number.isNaN(low))
        local[`values.${index}.low`] = "Type the bottom of the range as a number.";
      if (Number.isNaN(high))
        local[`values.${index}.high`] = "Type the top of the range as a number.";
      return {
        name: line.name.trim(),
        value: line.value.trim(),
        unit: tidy(line.unit),
        low: Number.isNaN(low) ? null : low,
        high: Number.isNaN(high) ? null : high,
        expected: tidy(line.expected),
      };
    });
    sent.forEach((line, index) => {
      if (!line.name.trim()) local[`values.${index}.name`] = "Say what this value is.";
    });
    if (!reportedOn) local.reported_on = "Pick the date printed on the report.";
    if (!values.length && !findings.trim())
      local.values = wordsOnly
        ? "Type in what the report says."
        : "Type in at least one value, or what the report says.";
    if (Object.keys(local).length) {
      setFields(local);
      setProblem(Object.values(local)[0] ?? null);
      return;
    }
    if (!save.isPending)
      save.mutate({
        reported_on: reportedOn,
        lab_name: tidy(labName),
        findings: tidy(findings),
        values,
      });
  };

  const change = (key: string, changes: Partial<Line>) => {
    setLines((current) =>
      current.map((line) => (line.key === key ? { ...line, ...changes } : line)),
    );
    setProblem(null);
  };

  const add = () => {
    const line: Line = {
      key: newKey(),
      fixed: false,
      name: "",
      value: "",
      unit: "",
      low: "",
      high: "",
      expected: "",
    };
    setAdded(line.key);
    setLines((current) => [...current, line]);
  };

  const problemFor = (line: Line, field: string) => {
    const index = sent.indexOf(line);
    return index >= 0 ? fields[`values.${index}.${field}`] : undefined;
  };

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="flex flex-col gap-5"
      aria-label="The report"
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[12rem_minmax(0,1fr)]">
        <div className="flex flex-col gap-1">
          <label htmlFor={`${id}-on`} className="text-[13px] font-medium">
            Date on the report
          </label>
          <input
            id={`${id}-on`}
            type="date"
            value={reportedOn}
            min={earliest}
            max={today}
            required
            onChange={(event) => setReportedOn(event.target.value)}
            aria-invalid={Boolean(fields.reported_on)}
            aria-describedby={fields.reported_on ? `${id}-on-error` : undefined}
            className={`${FIELD} tabular`}
          />
          {fields.reported_on && (
            <p id={`${id}-on-error`} className="text-[13px] text-[var(--color-state-noshow)]">
              {fields.reported_on}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-1">
          <label htmlFor={`${id}-lab`} className="text-[13px] font-medium">
            Lab <span className="font-normal text-[var(--text-muted)]">(if not your own)</span>
          </label>
          <input
            id={`${id}-lab`}
            value={labName}
            maxLength={120}
            onChange={(event) => setLabName(event.target.value)}
            className={FIELD}
          />
        </div>
      </div>

      {order.ranges_left_out && order.values.length === 0 && (
        <p className="flex items-start gap-2 rounded-[var(--radius-field)] bg-[var(--surface-sunken)] px-3 py-2 text-[13px] leading-relaxed text-[var(--text-muted)]">
          <Info aria-hidden className="mt-0.5 size-4 shrink-0" />
          Some normal ranges are left blank because {whyBlank(order)}. Copy them from the
          lab&apos;s report.
        </p>
      )}

      {!wordsOnly && (
        <fieldset className="flex min-w-0 flex-col gap-2">
          <legend className="mb-1 text-[13px] font-medium">Values</legend>
          {lines.length > 0 && (
            <div
              aria-hidden
              className={`hidden ${COLUMNS} gap-2 px-0.5 text-[12px] text-[var(--text-subtle)] md:grid`}
            >
              <span>Test</span>
              <span>Result</span>
              <span>Unit</span>
              <span>Normal range</span>
              <span />
            </div>
          )}
          <ol className="flex flex-col gap-2">
            {lines.map((line, index) => (
              <ValueLine
                key={line.key}
                line={line}
                position={index + 1}
                autoFocus={added === line.key}
                problems={{
                  name: problemFor(line, "name"),
                  value: problemFor(line, "value"),
                  low: problemFor(line, "low"),
                  high: problemFor(line, "high"),
                }}
                onChange={(changes) => change(line.key, changes)}
                onRemove={() =>
                  setLines((current) => current.filter((each) => each.key !== line.key))
                }
              />
            ))}
          </ol>
          <div className="flex flex-wrap items-center gap-3">
            {lines.length < MAX_VALUES ? (
              <button
                type="button"
                onClick={add}
                className="inline-flex w-fit items-center gap-1.5 rounded-[var(--radius-field)] border border-dashed border-[var(--border-strong)] px-3 py-1.5 text-[14px] transition-colors hover:border-solid hover:bg-[var(--surface-sunken)]"
              >
                <Plus className="size-4" />
                Add a value
              </button>
            ) : (
              <p className="text-[13px] text-[var(--text-muted)]">
                That is {MAX_VALUES} values, as many as one report takes.
              </p>
            )}
            {lines.some((line) => !line.value.trim()) && (
              <p className="text-[13px] text-[var(--text-muted)]">
                Lines left empty are left off the report.
              </p>
            )}
          </div>
        </fieldset>
      )}

      <div className="flex flex-col gap-1">
        <label htmlFor={`${id}-findings`} className="text-[13px] font-medium">
          {listedWithValues ? "Remarks on the report" : "What the report says"}
          {listedWithValues && (
            <span className="font-normal text-[var(--text-muted)]"> (optional)</span>
          )}
        </label>
        <textarea
          id={`${id}-findings`}
          value={findings}
          maxLength={5000}
          rows={wordsOnly ? 5 : 2}
          onChange={(event) => {
            setFindings(event.target.value);
            setProblem(null);
          }}
          aria-invalid={Boolean(fields.values && wordsOnly)}
          className={`${FIELD} min-h-[4rem] resize-y leading-relaxed [field-sizing:content]`}
        />
      </div>

      {problem && (
        <p role="alert" className="text-[14px] text-[var(--color-state-noshow)]">
          {problem}
        </p>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={save.isPending}
          className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2.5 text-[15px] font-semibold text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-60"
        >
          {save.isPending && <Loader2 className="size-4 animate-spin" />}
          {order.status === "ordered" ? "Save the report" : "Save the changes"}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={save.isPending}
            className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-4 py-2.5 text-[15px] transition-colors hover:bg-[var(--surface-sunken)]"
          >
            Keep it as it was
          </button>
        )}
      </div>
    </form>
  );
}

function ValueLine({
  line,
  position,
  autoFocus,
  problems,
  onChange,
  onRemove,
}: {
  line: Line;
  position: number;
  autoFocus: boolean;
  problems: { name?: string; value?: string; low?: string; high?: string };
  onChange: (changes: Partial<Line>) => void;
  onRemove: () => void;
}) {
  const id = useId();
  const low = number(line.low);
  const high = number(line.high);
  const flag = line.value.trim()
    ? judge({
        value: line.value,
        low: low === null || Number.isNaN(low) ? null : low,
        high: high === null || Number.isNaN(high) ? null : high,
        expected: tidy(line.expected),
      })
    : null;
  const label = line.name.trim() || `Value ${position}`;
  const wordRange = !line.low && !line.high && line.expected;
  const problem = problems.name ?? problems.value ?? problems.low ?? problems.high;

  return (
    <li
      className={`grid grid-cols-[minmax(0,1fr)_2rem] gap-2 rounded-[var(--radius-field)] border border-[var(--border)] bg-[var(--surface)] p-2.5 ${COLUMNS} md:items-center md:border-0 md:bg-transparent md:p-0`}
    >
      <div className="min-w-0">
        {line.fixed ? (
          <label
            htmlFor={`${id}-value`}
            className="block text-[15px] leading-snug font-medium break-words"
          >
            {line.name}
          </label>
        ) : (
          <>
            <label htmlFor={`${id}-name`} className="sr-only">
              What value {position} is
            </label>
            <input
              id={`${id}-name`}
              value={line.name}
              maxLength={80}
              autoFocus={autoFocus}
              placeholder="For example, ESR"
              onChange={(event) => onChange({ name: event.target.value })}
              aria-invalid={Boolean(problems.name)}
              className={`${FIELD} font-medium`}
            />
          </>
        )}
      </div>
      <button
        type="button"
        onClick={onRemove}
        aria-label={`Take ${label} off the report`}
        className="grid size-8 place-items-center self-center rounded-[6px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)] md:order-last"
      >
        <X className="size-4" />
      </button>
      <div className="col-span-2 grid grid-cols-[minmax(0,1fr)_5.5rem] gap-2 md:col-span-1 md:contents">
        <div className="relative min-w-0">
          {!line.fixed && (
            <label htmlFor={`${id}-value`} className="sr-only">
              {label} result
            </label>
          )}
          <input
            id={`${id}-value`}
            value={line.value}
            maxLength={60}
            inputMode="text"
            placeholder="Result"
            onChange={(event) => onChange({ value: event.target.value })}
            aria-invalid={Boolean(problems.value)}
            aria-describedby={flag ? `${id}-flag` : undefined}
            className={`${FIELD} pr-16 tabular ${
              flag
                ? "border-[color-mix(in_srgb,var(--color-state-noshow)_60%,transparent)] font-semibold text-[var(--color-state-noshow)]"
                : ""
            }`}
          />
          {flag && (
            <span id={`${id}-flag`} className="absolute top-1/2 right-2.5 -translate-y-1/2">
              <Judged flag={flag} spoken />
            </span>
          )}
        </div>
        <div>
          <label htmlFor={`${id}-unit`} className="sr-only">
            {label} unit
          </label>
          <input
            id={`${id}-unit`}
            value={line.unit}
            maxLength={24}
            placeholder="Unit"
            onChange={(event) => onChange({ unit: event.target.value })}
            className={`${FIELD} text-[14px]`}
          />
        </div>
      </div>
      <div className="col-span-2 min-w-0 md:col-span-1">
        {wordRange ? (
          <div className="flex items-center gap-1.5">
            <label htmlFor={`${id}-expected`} className="text-[12px] text-[var(--text-muted)]">
              Should be
            </label>
            <input
              id={`${id}-expected`}
              value={line.expected}
              maxLength={40}
              onChange={(event) => onChange({ expected: event.target.value })}
              className={`${FIELD} text-[14px]`}
            />
          </div>
        ) : (
          <div className="flex items-center gap-1">
            <label htmlFor={`${id}-low`} className="sr-only">
              {label}, bottom of the normal range
            </label>
            <input
              id={`${id}-low`}
              value={line.low}
              inputMode="decimal"
              maxLength={12}
              placeholder="from"
              onChange={(event) => onChange({ low: event.target.value })}
              aria-invalid={Boolean(problems.low)}
              className={`${FIELD} px-2 text-[14px] tabular`}
            />
            <span aria-hidden className="text-[var(--text-subtle)]">
              –
            </span>
            <label htmlFor={`${id}-high`} className="sr-only">
              {label}, top of the normal range
            </label>
            <input
              id={`${id}-high`}
              value={line.high}
              inputMode="decimal"
              maxLength={12}
              placeholder="to"
              onChange={(event) => onChange({ high: event.target.value })}
              aria-invalid={Boolean(problems.high)}
              className={`${FIELD} px-2 text-[14px] tabular`}
            />
          </div>
        )}
      </div>
      {problem && (
        <p className="col-span-2 text-[13px] text-[var(--color-state-noshow)] md:order-last md:col-span-5">
          {problem}
        </p>
      )}
    </li>
  );
}
