"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { Flag, useTemperatureUnit } from "@/components/vitals/readings";
import { vitalsForPatient, shownReadings, type Vitals } from "@/lib/vitals";

const SHOWN = 10;

// The unit goes in the heading, once, so the cells can be only numbers and
// the whole history fits beside the sidebar.
const COLUMNS: { key: string; heading: string; unit?: string }[] = [
  { key: "bp", heading: "BP", unit: "mmHg" },
  { key: "pulse", heading: "Pulse", unit: "/min" },
  { key: "temp", heading: "Temp" },
  { key: "spo2", heading: "SpO₂", unit: "%" },
  { key: "rr", heading: "Breaths", unit: "/min" },
  { key: "weight", heading: "Weight", unit: "kg" },
  { key: "bmi", heading: "BMI" },
  { key: "sugar", heading: "Sugar", unit: "mg/dL" },
];

/**
 * Every set of readings, newest first, so a doctor can see a pressure or a
 * weight move from one visit to the next. Columns nobody has filled in are
 * left out rather than shown empty.
 */
export function PatientVitals({ patientId }: { patientId: string }) {
  const [unit] = useTemperatureUnit();
  const found = useQuery({
    queryKey: ["vitals", "patient", patientId],
    queryFn: () => vitalsForPatient(patientId, SHOWN),
    retry: false,
  });

  const rows = (found.data?.items ?? []).map((vitals) => ({
    vitals,
    readings: Object.fromEntries(shownReadings(vitals, unit).map((item) => [item.key, item])),
  }));
  const columns = COLUMNS.filter((column) => rows.some((row) => row.readings[column.key]));
  const headedUnit = (column: (typeof COLUMNS)[number]) =>
    column.key === "temp" ? `°${unit}` : column.unit;

  return (
    <section
      aria-labelledby="vitals-title"
      className="min-w-0 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
    >
      <h2 id="vitals-title" className="text-[15px] font-semibold">
        Vitals
      </h2>
      {found.isPending ? (
        <p className="mt-3 inline-flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" /> Looking…
        </p>
      ) : found.isError ? (
        <p className="mt-3 text-[14px] text-[var(--text-muted)]">Vitals did not load.</p>
      ) : rows.length === 0 ? (
        <p className="mt-2 text-[14px] leading-relaxed text-[var(--text-muted)]">
          None taken yet. They are taken from the queue while the patient waits.
        </p>
      ) : (
        <>
          {/* Positioned, so the words kept for screen readers scroll with the
              table instead of widening the page. */}
          <div className="relative -mx-5 mt-3 overflow-x-auto px-5">
            <table className="w-full min-w-max border-collapse text-[13px] tabular">
              <caption className="sr-only">Vital signs, newest first</caption>
              <thead>
                <tr className="text-left text-[12px] text-[var(--text-subtle)]">
                  <th scope="col" className="py-1.5 pr-2.5 align-bottom font-medium">
                    Taken
                  </th>
                  {columns.map((column) => (
                    <th
                      key={column.key}
                      scope="col"
                      className="py-1.5 pr-2.5 align-bottom font-medium"
                    >
                      {column.heading}
                      {headedUnit(column) && (
                        <span className="block font-normal">{headedUnit(column)}</span>
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--border)]">
                {rows.map(({ vitals, readings }) => (
                  <tr key={vitals.id} className="align-baseline">
                    <th
                      scope="row"
                      className="py-2 pr-2.5 text-left font-normal whitespace-nowrap"
                    >
                      <Taken vitals={vitals} />
                    </th>
                    {columns.map((column) => {
                      const item = readings[column.key];
                      return (
                        <td key={column.key} className="py-2 pr-2.5 whitespace-nowrap">
                          {item ? (
                            <span
                              className={`inline-flex items-baseline gap-0.5 ${
                                item.flag
                                  ? "font-semibold text-[var(--color-state-noshow)]"
                                  : ""
                              }`}
                            >
                              {item.bare}
                              {item.flag && <Flag level={item.flag} />}
                            </span>
                          ) : (
                            <span className="text-[var(--text-subtle)]" aria-label="Not taken">
                              –
                            </span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {found.data.total > SHOWN && (
            <p className="mt-2 text-[13px] text-[var(--text-muted)] tabular">
              Showing the latest {SHOWN} of {found.data.total}.
            </p>
          )}
        </>
      )}
    </section>
  );
}

function Taken({ vitals }: { vitals: Vitals }) {
  const day = new Date(`${vitals.taken_on}T00:00:00`);
  const time = new Date(vitals.taken_at).toLocaleTimeString("en-IN", {
    hour: "numeric",
    minute: "2-digit",
  });
  return (
    <span title={vitals.note ?? undefined}>
      {day.toLocaleDateString("en-IN", {
        day: "numeric",
        month: "short",
        ...(day.getFullYear() === new Date().getFullYear() ? {} : { year: "numeric" }),
      })}
      <span className="block text-[12px] text-[var(--text-subtle)]">{time}</span>
    </span>
  );
}
