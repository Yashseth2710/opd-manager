import { post, request } from "@/lib/api";
import type { DoctorRef, PatientRef } from "@/lib/appointments";

export type Timing =
  "before_food" | "after_food" | "with_food" | "empty_stomach" | "bedtime" | "as_needed";

export const TIMING_WORDS: Record<Timing, string> = {
  before_food: "Before food",
  after_food: "After food",
  with_food: "With food",
  empty_stomach: "Empty stomach",
  bedtime: "At bedtime",
  as_needed: "When needed",
};

/** The dose patterns a doctor writes most, morning-afternoon-night. */
export const DOSE_PATTERNS = ["1-0-1", "1-0-0", "0-0-1", "1-1-1", "0-1-0"] as const;

export const MAX_LINES = 30;

export type MedicineLine = {
  medicine_name: string;
  presentation: string | null;
  dose: string | null;
  timing: Timing | null;
  duration_days: number | null;
  instructions: string | null;
};

export type PrescriptionStatus = "draft" | "issued" | "replaced";

export type PrescriptionRef = { id: string; number: string | null };

export type Prescription = {
  id: string;
  number: string | null;
  status: PrescriptionStatus;
  issued_at: string | null;
  follow_up_date: string | null;
  instructions: string | null;
  items: MedicineLine[];
  replaces: PrescriptionRef | null;
  replaced_by: PrescriptionRef | null;
  correction_reason: string | null;
};

export type PrescriptionDetail = Prescription & {
  patient: PatientRef;
  doctor: {
    id: string;
    display_name: string;
    speciality: string | null;
    qualifications: string | null;
    registration_number: string | null;
  };
  clinic: { name: string; address: string[]; phone: string | null; email: string | null };
  consultation_id: string;
  visit_date: string;
  can_correct: boolean;
};

export type PrescriptionSummary = {
  id: string;
  number: string | null;
  status: PrescriptionStatus;
  issued_at: string | null;
  patient: PatientRef;
  doctor: DoctorRef;
  medicines: string[];
};

export type PrescriptionPage = { items: PrescriptionSummary[]; total: number };

export type MedicineSuggestion = {
  name: string;
  presentation: string | null;
  source: "clinic" | "list";
  times_prescribed: number;
};

export const suggestMedicines = (typed: string) =>
  request<MedicineSuggestion[]>(`/medicines?q=${encodeURIComponent(typed)}`);

export const getPrescription = (id: string) =>
  request<PrescriptionDetail>(`/prescriptions/${id}`);

export const listPrescriptions = (filters: { patient?: string; limit?: number } = {}) => {
  const params = new URLSearchParams();
  if (filters.patient) params.set("patient_id", filters.patient);
  if (filters.limit) params.set("limit", String(filters.limit));
  const query = params.toString();
  return request<PrescriptionPage>(`/prescriptions${query ? `?${query}` : ""}`);
};

export const correctPrescription = (
  id: string,
  body: { medicines: MedicineLine[]; instructions: string | null; reason: string },
) => post<PrescriptionDetail>(`/prescriptions/${id}/corrections`, body);

/** Opened in a new tab, where the browser's own viewer prints it. */
export const pdfHref = (id: string) => `/api/v1/prescriptions/${id}/pdf`;

/** The calendar day an instant fell on here, as the date inputs write it. */
export function localDay(instant: string): string {
  const moment = new Date(instant);
  const local = new Date(moment.getTime() - moment.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export function spokenDays(days: number | null): string {
  if (days === null) return "";
  return days === 1 ? "1 day" : `${days} days`;
}
