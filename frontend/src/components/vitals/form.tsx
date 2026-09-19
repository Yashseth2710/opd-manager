"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { useTemperatureUnit } from "@/components/vitals/readings";
import { ApiFailure } from "@/lib/api";
import type { QueueDay, QueueEntry } from "@/lib/queue";
import {
  correctVitals,
  GLUCOSE_TIMINGS,
  removeVitals,
  takeVitals,
  toCelsius,
  toFahrenheit,
  vitalsForVisit,
  type GlucoseTiming,
  type Readings,
  type TemperatureUnit,
  type Vitals,
} from "@/lib/vitals";

type Field =
  | "systolic"
  | "diastolic"
  | "pulse"
  | "temperature"
  | "spo2"
  | "breaths"
  | "weight"
  | "height"
  | "sugar";

type Draft = Record<Field, string> & { timing: GlucoseTiming | ""; note: string };

const EMPTY: Draft = {
  systolic: "",
  diastolic: "",
  pulse: "",
  temperature: "",
  spo2: "",
  breaths: "",
  weight: "",
  height: "",
  sugar: "",
  timing: "",
  note: "",
};

/** Mirrors the server's limits, so a slip is caught before it is sent. */
const LIMITS: Record<Exclude<Field, "temperature">, [number, number, boolean, string]> = {
  systolic: [50, 300, true, "The upper number"],
  diastolic: [20, 200, true, "The lower number"],
  pulse: [20, 250, true, "Pulse"],
  spo2: [50, 100, true, "Oxygen"],
  breaths: [4, 80, true, "Breathing"],
  weight: [0.3, 400, false, "Weight"],
  height: [20, 250, false, "Height"],
  sugar: [10, 1000, true, "Blood sugar"],
};

const SERVER_FIELD: Record<string, Field | "timing" | "note"> = {
  systolic_mmhg: "systolic",
  diastolic_mmhg: "diastolic",
  pulse_bpm: "pulse",
  temperature_c: "temperature",
  spo2_percent: "spo2",
  respiratory_rate: "breaths",
  weight_kg: "weight",
  height_cm: "height",
  glucose_mg_dl: "sugar",
  glucose_timing: "timing",
  note: "note",
};

function fromVitals(vitals: Vitals, unit: TemperatureUnit): Draft {
  const text = (value: number | null) => (value == null ? "" : String(value));
  return {
    systolic: text(vitals.systolic_mmhg),
    diastolic: text(vitals.diastolic_mmhg),
    pulse: text(vitals.pulse_bpm),
    temperature:
      vitals.temperature_c == null
        ? ""
        : String(unit === "F" ? toFahrenheit(vitals.temperature_c) : vitals.temperature_c),
    spo2: text(vitals.spo2_percent),
    breaths: text(vitals.respiratory_rate),
    weight: text(vitals.weight_kg),
    height: text(vitals.height_cm),
    sugar: text(vitals.glucose_mg_dl),
    timing: vitals.glucose_timing ?? "",
    note: vitals.note ?? "",
  };
}

function withVitals(day: QueueDay, entryId: string, saved: Vitals | null): QueueDay {
  const put = <T extends QueueEntry | null>(entry: T): T =>
    entry && entry.id === entryId ? { ...entry, vitals: saved } : entry;
  return {
    ...day,
    lanes: day.lanes.map((lane) => ({
      ...lane,
      now_seeing: put(lane.now_seeing),
      called: put(lane.called),
      waiting: lane.waiting.map(put),
      skipped: lane.skipped.map(put),
    })),
  };
}

type Problems = Partial<Record<Field | "timing" | "note" | "form", string>>;

function number(raw: string): number | null {
  const cleaned = raw.trim();
  if (!cleaned) return null;
  return /^\d+(\.\d+)?$/.test(cleaned) ? Number(cleaned) : Number.NaN;
}

/** The readings as the API takes them, or what needs fixing first. */
function check(draft: Draft, unit: TemperatureUnit): [Readings | null, Problems] {
  const problems: Problems = {};
  const values: Partial<Record<Field, number | null>> = {};

  for (const [field, [low, high, whole, name]] of Object.entries(LIMITS) as [
    Exclude<Field, "temperature">,
    [number, number, boolean, string],
  ][]) {
    const value = number(draft[field]);
    values[field] = value;
    if (value === null) continue;
    if (Number.isNaN(value)) problems[field] = "Numbers only.";
    else if (whole && !Number.isInteger(value)) problems[field] = "Whole numbers only.";
    else if (value < low || value > high)
      problems[field] = `${name} has to be between ${low} and ${high}. Check for a slip.`;
  }

  const typed = number(draft.temperature);
  let celsius: number | null = null;
  if (typed !== null) {
    const [low, high] = unit === "F" ? [86, 113] : [30, 45];
    if (Number.isNaN(typed)) problems.temperature = "Numbers only.";
    else if (typed < low || typed > high)
      problems.temperature = `Temperature has to be between ${low} and ${high} °${unit}. Check the unit too.`;
    else celsius = unit === "F" ? toCelsius(typed) : typed;
  }

  const { systolic, diastolic } = values;
  if (!problems.systolic && !problems.diastolic) {
    if (systolic != null && diastolic == null)
      problems.diastolic = "Enter the lower number as well.";
    else if (diastolic != null && systolic == null)
      problems.systolic = "Enter the upper number as well.";
    else if (systolic != null && diastolic != null && diastolic >= systolic)
      problems.diastolic = "The lower number has to be below the upper one.";
  }
  if (values.sugar != null && !problems.sugar && !draft.timing)
    problems.timing = "Say when the sugar was taken.";

  const measured =
    Object.values(values).some((value) => value != null) || draft.temperature.trim() !== "";
  if (!measured) problems.form = "Enter at least one reading.";

  if (Object.keys(problems).length > 0) return [null, problems];
  return [
    {
      systolic_mmhg: systolic ?? null,
      diastolic_mmhg: diastolic ?? null,
      pulse_bpm: values.pulse ?? null,
      temperature_c: celsius,
      spo2_percent: values.spo2 ?? null,
      respiratory_rate: values.breaths ?? null,
      weight_kg: values.weight ?? null,
      height_cm: values.height ?? null,
      glucose_mg_dl: values.sugar ?? null,
      glucose_timing: values.sugar != null && draft.timing ? draft.timing : null,
      note: draft.note.trim() || null,
    },
    {},
  ];
}

/**
 * Takes the readings for one place in the queue, or corrects the ones
 * already taken. Opens in place, under whatever it was opened from.
 */
export function VitalsForm({
  entryId,
  patientName,
  onClose,
  onSaved,
}: {
  entryId: string;
  patientName: string;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const queries = useQueryClient();
  const heading = useId();
  const [unit, setUnit] = useTemperatureUnit();
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [problems, setProblems] = useState<Problems>({});
  const [confirmingRemove, setConfirmingRemove] = useState(false);
  const first = useRef<HTMLInputElement>(null);
  const inFlight = useRef(false);

  const existing = useQuery({
    queryKey: ["vitals", "visit", entryId],
    queryFn: () => vitalsForVisit(entryId),
    select: (page) => page.items[0] ?? null,
    retry: false,
  });
  const current = existing.data ?? null;
  const loadedFor = useRef<string | null>(null);

  // The boxes wait for a fresh answer rather than a remembered one: another
  // desk may have taken the readings since this form was last open, and a
  // stale "none yet" would offer to take them a second time.
  const [ready, setReady] = useState(false);

  // Filled from what is on record once, when it arrives, and not again
  // under somebody's typing.
  useEffect(() => {
    if (!existing.isSuccess || existing.isFetching) return;
    const key = current ? `${current.id}:${current.updated_at}` : "none";
    if (loadedFor.current === key) return;
    loadedFor.current = key;
    setDraft(current ? fromVitals(current, unit) : EMPTY);
    setReady(true);
    // The unit is read once here; switching it converts the box below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [existing.isSuccess, existing.isFetching, current]);

  useEffect(() => {
    if (ready) first.current?.focus();
  }, [ready]);

  // The row shows what was saved at once, rather than after the next poll
  // comes back from a database a few seconds away.
  const settle = (saved?: Vitals | null) => {
    if (saved !== undefined) {
      queries.setQueryData<QueueDay>(
        ["queue"],
        (day) => day && withVitals(day, entryId, saved),
      );
      queries.setQueryData(["vitals", "visit", entryId], {
        items: saved ? [saved] : [],
        total: saved ? 1 : 0,
      });
    }
    void queries.invalidateQueries({ queryKey: ["vitals"] });
    void queries.invalidateQueries({ queryKey: ["queue"] });
  };

  const save = useMutation({
    mutationFn: (readings: Readings) =>
      current ? correctVitals(current.id, readings) : takeVitals(entryId, readings),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: (saved) => {
      settle(saved);
      onSaved(
        current ? `Vitals for ${patientName} corrected.` : `Vitals taken for ${patientName}.`,
      );
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.code === "VITALS_ALREADY_TAKEN") {
        // Somebody else got there first. Show theirs rather than overwrite.
        loadedFor.current = null;
        setReady(false);
        setProblems({
          form: "Somebody has just taken these. Their readings are below. Correct them if they need it.",
        });
        settle();
        return;
      }
      if (error instanceof ApiFailure && error.fields) {
        const mapped: Problems = {};
        for (const [key, message] of Object.entries(error.fields)) {
          const field = SERVER_FIELD[key];
          if (field) mapped[field] = message;
          else mapped.form = message;
        }
        setProblems(mapped);
        return;
      }
      setProblems({
        form:
          error instanceof ApiFailure
            ? error.message
            : "That did not go through. Try again in a moment.",
      });
    },
  });

  const remove = useMutation({
    mutationFn: () => removeVitals(current!.id),
    onSuccess: () => {
      settle(null);
      onSaved(`Vitals for ${patientName} removed.`);
    },
    onError: (error) => {
      setConfirmingRemove(false);
      setProblems({
        form: error instanceof ApiFailure ? error.message : "That did not go through.",
      });
    },
  });

  // The temperature as typed before the unit was switched, so switching back
  // restores it rather than a figure rounded both ways.
  const [typedIn, setTypedIn] = useState<{
    unit: TemperatureUnit;
    text: string;
    after: string;
  } | null>(null);

  const set = (field: keyof Draft, value: string) => {
    if (field === "temperature") setTypedIn(null);
    setDraft((now) => ({ ...now, [field]: value }));
    setProblems((now) => {
      const rest = { ...now };
      delete rest[field as keyof Problems];
      delete rest.form;
      if (field === "systolic" || field === "diastolic") {
        delete rest.systolic;
        delete rest.diastolic;
      }
      if (field === "sugar") delete rest.timing;
      return rest;
    });
  };

  const switchUnit = (next: TemperatureUnit) => {
    if (next === unit) return;
    const typed = number(draft.temperature);
    if (typedIn?.unit === next && typedIn.after === draft.temperature) {
      // Back to the unit it was typed in: the exact figure, not one rounded
      // there and back.
      setDraft((now) => ({ ...now, temperature: typedIn.text }));
    } else if (typed !== null && !Number.isNaN(typed)) {
      const converted = String(
        next === "F" ? toFahrenheit(typed) : Math.round(toCelsius(typed) * 10) / 10,
      );
      setTypedIn({ unit, text: draft.temperature, after: converted });
      setDraft((now) => ({ ...now, temperature: converted }));
    }
    setProblems((now) => ({ ...now, temperature: undefined }));
    setUnit(next);
  };

  const submit = () => {
    if (inFlight.current) return;
    const [readings, found] = check(draft, unit);
    setProblems(found);
    if (!readings) return;
    inFlight.current = true;
    save.mutate(readings);
  };

  const busy = save.isPending || remove.isPending;
  const numeric = (field: Field, whole = true) => ({
    value: draft[field],
    inputMode: whole ? ("numeric" as const) : ("decimal" as const),
    autoComplete: "off",
    "aria-invalid": Boolean(problems[field]) || undefined,
    onChange: (event: React.ChangeEvent<HTMLInputElement>) => set(field, event.target.value),
  });

  return (
    <section
      aria-labelledby={heading}
      className="rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-4 py-4"
    >
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 id={heading} className="text-[15px] font-semibold tracking-tight">
          {current ? "Correct vitals" : "Take vitals"}
          <span className="font-normal text-[var(--text-muted)]"> for {patientName}</span>
        </h3>
        {current && (
          <p className="text-[12px] text-[var(--text-subtle)]">
            Taken by {current.taken_by ?? "a former member of staff"}
            {current.changed_by ? `, corrected by ${current.changed_by}` : ""}
          </p>
        )}
      </div>

      {existing.isError ? (
        <div className="flex flex-wrap items-center gap-3 py-2 text-[14px]">
          <p role="alert" className="text-[var(--color-state-noshow)]">
            Could not check for readings already taken.
          </p>
          <button
            type="button"
            onClick={() => void existing.refetch()}
            className="font-medium underline underline-offset-2"
          >
            Try again
          </button>
        </div>
      ) : !ready ? (
        <p className="flex items-center gap-2 py-6 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" />
          Checking for readings already taken…
        </p>
      ) : current && !current.can_change ? (
        <div className="flex flex-wrap items-center justify-between gap-3 py-1 text-[14px]">
          <p className="text-[var(--text-muted)]">
            These can no longer be changed. They are kept as they were taken.
          </p>
          <SecondaryButton onClick={onClose}>Close</SecondaryButton>
        </div>
      ) : (
        <form
          noValidate
          onSubmit={(event) => {
            event.preventDefault();
            submit();
          }}
          className="flex flex-col gap-4"
        >
          {problems.form && (
            <p role="alert" className="text-[13px] text-[var(--color-state-noshow)]">
              {problems.form}
            </p>
          )}

          <div className="grid grid-cols-2 gap-x-4 gap-y-3.5 sm:grid-cols-4">
            <fieldset className="col-span-2">
              <legend className="mb-1.5 text-[13px] font-medium">Blood pressure</legend>
              <div className="flex items-center gap-1.5">
                <Box
                  ref={first}
                  label="Upper number (systolic)"
                  {...numeric("systolic")}
                  width="w-[4.25rem]"
                />
                <span aria-hidden className="text-[var(--text-subtle)]">
                  /
                </span>
                <Box
                  label="Lower number (diastolic)"
                  {...numeric("diastolic")}
                  width="w-[4.25rem]"
                />
                <span className="text-[12px] text-[var(--text-subtle)]">mmHg</span>
              </div>
              <Problem text={problems.systolic ?? problems.diastolic} />
            </fieldset>

            <div className="col-span-2 sm:col-span-1">
              <label
                htmlFor={`${heading}-temp`}
                className="mb-1.5 block text-[13px] font-medium"
              >
                Temperature
              </label>
              <div className="flex items-center gap-1.5">
                <Box
                  id={`${heading}-temp`}
                  label="Temperature"
                  {...numeric("temperature", false)}
                  width="w-full max-w-[5rem]"
                />
                <div
                  role="group"
                  aria-label="°F or °C"
                  className="inline-flex shrink-0 overflow-hidden rounded-[4px] border border-[var(--border-strong)] text-[12px]"
                >
                  {(["F", "C"] as const).map((option) => (
                    <button
                      key={option}
                      type="button"
                      aria-pressed={unit === option}
                      onClick={() => switchUnit(option)}
                      className={`px-1.5 py-1 transition-colors ${
                        unit === option
                          ? "bg-[var(--primary)] font-medium text-[var(--primary-fg)]"
                          : "text-[var(--text-muted)] hover:bg-[var(--surface-sunken)]"
                      }`}
                    >
                      °{option}
                    </button>
                  ))}
                </div>
              </div>
              <Problem text={problems.temperature} />
            </div>

            <Measure label="Pulse" unit="/min" problem={problems.pulse}>
              <Box label="Pulse" {...numeric("pulse")} />
            </Measure>

            <Measure label="Oxygen (SpO₂)" unit="%" problem={problems.spo2}>
              <Box label="Oxygen (SpO₂)" {...numeric("spo2")} />
            </Measure>

            <Measure label="Breathing" unit="/min" problem={problems.breaths}>
              <Box label="Breathing" {...numeric("breaths")} />
            </Measure>

            <Measure label="Weight" unit="kg" problem={problems.weight}>
              <Box label="Weight" {...numeric("weight", false)} />
            </Measure>

            <Measure label="Height" unit="cm" problem={problems.height}>
              <Box label="Height" {...numeric("height", false)} />
            </Measure>

            <Measure label="Blood sugar" unit="mg/dL" problem={problems.sugar}>
              <Box label="Blood sugar" {...numeric("sugar")} />
            </Measure>
          </div>

          {draft.sugar.trim() !== "" && (
            <fieldset>
              <legend className="mb-1.5 text-[13px] font-medium">
                When was the sugar taken?
              </legend>
              <div className="flex flex-wrap gap-x-5 gap-y-2">
                {GLUCOSE_TIMINGS.map((option) => (
                  <label key={option.value} className="flex items-center gap-2 text-[14px]">
                    <input
                      type="radio"
                      name={`${heading}-timing`}
                      value={option.value}
                      checked={draft.timing === option.value}
                      onChange={() => set("timing", option.value)}
                      className="size-4 accent-[var(--primary)]"
                    />
                    {option.label}
                  </label>
                ))}
              </div>
              <Problem text={problems.timing} />
            </fieldset>
          )}

          <label className="block">
            <span className="mb-1.5 block text-[13px] font-medium">
              Note <span className="font-normal text-[var(--text-subtle)]">optional</span>
            </span>
            <input
              value={draft.note}
              onChange={(event) => set("note", event.target.value)}
              maxLength={200}
              className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px]"
            />
            <Problem text={problems.note} />
          </label>

          {confirmingRemove ? (
            <div
              role="group"
              aria-label="Confirm removing these vitals"
              className="flex flex-wrap items-center gap-2 rounded-[var(--radius-field)] bg-[color-mix(in_srgb,var(--color-state-noshow)_8%,transparent)] px-3 py-2 text-[14px]"
            >
              <span className="mr-auto">
                Remove these readings? Do this when they were taken for the wrong person.
              </span>
              <button
                type="button"
                onClick={() => remove.mutate()}
                disabled={busy}
                className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] bg-[var(--color-state-noshow)] px-3 py-1.5 text-[13px] font-semibold text-white transition hover:brightness-110 disabled:opacity-60"
              >
                {remove.isPending && <Loader2 className="size-3.5 animate-spin" />}
                Yes, remove them
              </button>
              <SecondaryButton onClick={() => setConfirmingRemove(false)}>
                Keep them
              </SecondaryButton>
            </div>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="submit"
                disabled={busy}
                className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2 text-[14px] font-semibold text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-60"
              >
                {save.isPending && <Loader2 className="size-4 animate-spin" />}
                {save.isPending ? "Saving" : current ? "Save the correction" : "Save vitals"}
              </button>
              <SecondaryButton onClick={onClose}>Cancel</SecondaryButton>
              {current && (
                <button
                  type="button"
                  onClick={() => setConfirmingRemove(true)}
                  disabled={busy}
                  className="ml-auto text-[13px] text-[var(--color-state-noshow)] underline-offset-2 hover:underline"
                >
                  Remove these readings
                </button>
              )}
            </div>
          )}
        </form>
      )}
    </section>
  );
}

function Measure({
  label,
  unit,
  problem,
  children,
}: {
  label: string;
  unit: string;
  problem?: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <span aria-hidden className="mb-1.5 block text-[13px] font-medium">
        {label}
      </span>
      <div className="flex items-center gap-1.5">
        {children}
        <span className="text-[12px] text-[var(--text-subtle)]">{unit}</span>
      </div>
      <Problem text={problem} />
    </div>
  );
}

function Box({
  label,
  width = "w-full max-w-[6.5rem]",
  ref,
  ...input
}: {
  label: string;
  width?: string;
  ref?: React.Ref<HTMLInputElement>;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      ref={ref}
      aria-label={label}
      type="text"
      maxLength={6}
      className={`${width} rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-2 text-[15px] tabular aria-[invalid]:border-[var(--color-state-noshow)]`}
      {...input}
    />
  );
}

function Problem({ text }: { text?: string }) {
  if (!text) return null;
  return <p className="mt-1 text-[12px] text-[var(--color-state-noshow)]">{text}</p>;
}

function SecondaryButton({
  onClick,
  children,
}: {
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
    >
      {children}
    </button>
  );
}
