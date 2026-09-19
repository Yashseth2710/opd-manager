import { request } from "@/lib/api";

export type GlucoseTiming = "fasting" | "random" | "after_meal";
export type Level = "high" | "low";
export type BmiBand = "underweight" | "normal" | "overweight" | "obese";
export type FlagKey =
  "blood_pressure" | "pulse" | "temperature" | "spo2" | "respiratory_rate" | "glucose" | "bmi";

export type Readings = {
  systolic_mmhg: number | null;
  diastolic_mmhg: number | null;
  pulse_bpm: number | null;
  temperature_c: number | null;
  spo2_percent: number | null;
  respiratory_rate: number | null;
  weight_kg: number | null;
  height_cm: number | null;
  glucose_mg_dl: number | null;
  glucose_timing: GlucoseTiming | null;
  note: string | null;
};

export type Vitals = Readings & {
  id: string;
  patient_id: string;
  queue_entry_id: string;
  bmi: number | null;
  bmi_band: BmiBand | null;
  flags: Partial<Record<FlagKey, Level>>;
  taken_at: string;
  taken_on: string;
  taken_by: string | null;
  changed_by: string | null;
  updated_at: string;
  can_change: boolean;
};

/** What the queue carries of a place's readings. */
export type VitalsBrief = Pick<
  Vitals,
  | "id"
  | "systolic_mmhg"
  | "diastolic_mmhg"
  | "pulse_bpm"
  | "temperature_c"
  | "spo2_percent"
  | "weight_kg"
  | "glucose_mg_dl"
  | "flags"
>;

export type VitalsPage = { items: Vitals[]; total: number };

export const vitalsForVisit = (entryId: string) =>
  request<VitalsPage>(`/vitals?queue_entry_id=${encodeURIComponent(entryId)}`);

export const vitalsForPatient = (patientId: string, limit = 25, offset = 0) =>
  request<VitalsPage>(
    `/vitals?patient_id=${encodeURIComponent(patientId)}&limit=${limit}&offset=${offset}`,
  );

export const takeVitals = (entryId: string, readings: Readings) =>
  request<Vitals>("/vitals", {
    method: "POST",
    body: JSON.stringify({ queue_entry_id: entryId, ...readings }),
  });

export const correctVitals = (id: string, readings: Readings) =>
  request<Vitals>(`/vitals/${id}`, { method: "PUT", body: JSON.stringify(readings) });

export const removeVitals = (id: string) =>
  request<{ removed: boolean }>(`/vitals/${id}`, { method: "DELETE" });

export type TemperatureUnit = "F" | "C";

export const toFahrenheit = (celsius: number) => Math.round((celsius * 9 * 10) / 5 + 320) / 10;

/** Two places, so a reading typed to one in Fahrenheit comes back as typed. */
export const toCelsius = (fahrenheit: number) =>
  Math.round(((fahrenheit - 32) * 5 * 100) / 9) / 100;

export function temperature(celsius: number, unit: TemperatureUnit): string {
  return unit === "F"
    ? `${toFahrenheit(celsius).toFixed(1)} °F`
    : `${(Math.round(celsius * 10) / 10).toFixed(1)} °C`;
}

const UNIT_KEY = "opd.temperature-unit";

/** Remembered per browser. India mostly reads °F, so that comes first. */
export function savedUnit(): TemperatureUnit {
  try {
    return window.localStorage.getItem(UNIT_KEY) === "C" ? "C" : "F";
  } catch {
    return "F";
  }
}

export function saveUnit(unit: TemperatureUnit) {
  try {
    window.localStorage.setItem(UNIT_KEY, unit);
  } catch {
    // A private window: the choice lasts as long as the page does.
  }
}

export const GLUCOSE_TIMINGS: { value: GlucoseTiming; label: string }[] = [
  { value: "fasting", label: "Fasting" },
  { value: "random", label: "Random" },
  { value: "after_meal", label: "After a meal" },
];

export const BMI_WORDS: Record<BmiBand, string> = {
  underweight: "underweight",
  normal: "healthy range",
  overweight: "overweight",
  obese: "obese",
};

/** A reading as shown: with its unit, and bare for a column headed by the unit. */
export type Shown = { key: string; label: string; value: string; bare: string; flag?: Level };

/** Each reading that was taken, in the order a doctor reads them. */
export function shownReadings(
  vitals: Partial<Vitals> & Pick<Vitals, "flags">,
  unit: TemperatureUnit,
): Shown[] {
  const shown: Shown[] = [];
  const f = vitals.flags;
  if (vitals.systolic_mmhg != null && vitals.diastolic_mmhg != null)
    shown.push({
      key: "bp",
      label: "BP",
      value: `${vitals.systolic_mmhg}/${vitals.diastolic_mmhg}`,
      bare: `${vitals.systolic_mmhg}/${vitals.diastolic_mmhg}`,
      flag: f.blood_pressure,
    });
  if (vitals.pulse_bpm != null)
    shown.push({
      key: "pulse",
      label: "Pulse",
      value: `${vitals.pulse_bpm}`,
      bare: `${vitals.pulse_bpm}`,
      flag: f.pulse,
    });
  if (vitals.temperature_c != null)
    shown.push({
      key: "temp",
      label: "Temp",
      value: temperature(vitals.temperature_c, unit),
      bare: temperature(vitals.temperature_c, unit).split(" ")[0]!,
      flag: f.temperature,
    });
  if (vitals.spo2_percent != null)
    shown.push({
      key: "spo2",
      label: "SpO₂",
      value: `${vitals.spo2_percent}%`,
      bare: `${vitals.spo2_percent}`,
      flag: f.spo2,
    });
  if (vitals.respiratory_rate != null)
    shown.push({
      key: "rr",
      label: "Breaths",
      value: `${vitals.respiratory_rate}/min`,
      bare: `${vitals.respiratory_rate}`,
      flag: f.respiratory_rate,
    });
  if (vitals.weight_kg != null)
    shown.push({
      key: "weight",
      label: "Weight",
      value: `${vitals.weight_kg} kg`,
      bare: `${vitals.weight_kg}`,
    });
  if (vitals.height_cm != null)
    shown.push({
      key: "height",
      label: "Height",
      value: `${vitals.height_cm} cm`,
      bare: `${vitals.height_cm}`,
    });
  if (vitals.bmi != null)
    shown.push({
      key: "bmi",
      label: "BMI",
      value: `${vitals.bmi}`,
      bare: `${vitals.bmi}`,
      flag: f.bmi,
    });
  if (vitals.glucose_mg_dl != null)
    shown.push({
      key: "sugar",
      label: "Sugar",
      value: `${vitals.glucose_mg_dl} mg/dL`,
      bare: `${vitals.glucose_mg_dl}`,
      flag: f.glucose,
    });
  return shown;
}
