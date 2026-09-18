import { post, request } from "@/lib/api";
import type { AppointmentType, DoctorRef, PatientRef, Status } from "@/lib/appointments";
import type { MedicineLine, Prescription } from "@/lib/prescriptions";

export type ConsultationStatus = "draft" | "completed";

export type Diagnosis = { label: string; is_primary: boolean };

export type Addendum = {
  id: string;
  body: string;
  written_by: string | null;
  created_at: string;
};

export type ConsultationSummary = {
  id: string;
  status: ConsultationStatus;
  patient: PatientRef;
  doctor: DoctorRef;
  /** The clinic's date the patient was seen on. */
  visit_date: string;
  started_at: string;
  completed_at: string | null;
  token: number | null;
  chief_complaint: string | null;
  primary_diagnosis: string | null;
  diagnosis_count: number;
  follow_up_date: string | null;
  addendum_count: number;
};

export type Consultation = ConsultationSummary & {
  version: number;
  queue_entry_id: string | null;
  appointment: {
    id: string;
    start_time: string;
    end_time: string;
    appointment_type: AppointmentType;
    reason: string | null;
    status: Status;
  } | null;
  history: string | null;
  examination: string | null;
  advice: string | null;
  diagnoses: Diagnosis[];
  addenda: Addendum[];
  /** The one being written or standing first, then anything it replaced. */
  prescriptions: Prescription[];
  updated_at: string;
  can_edit: boolean;
  can_add_addendum: boolean;
};

export type ConsultationPage = { items: ConsultationSummary[]; total: number };

/** The parts of the note a save can carry. Anything left out is kept. */
export type NoteChanges = {
  chief_complaint?: string;
  history?: string;
  examination?: string;
  advice?: string;
  diagnoses?: Diagnosis[];
  follow_up_date?: string | null;
  medicines?: MedicineLine[];
  prescription_instructions?: string;
};

export const TEXT_SECTIONS = ["chief_complaint", "history", "examination", "advice"] as const;
export type TextSection = (typeof TEXT_SECTIONS)[number];

export const SECTION_LIMITS: Record<TextSection, number> = {
  chief_complaint: 500,
  history: 10_000,
  examination: 10_000,
  advice: 10_000,
};

export const DIAGNOSIS_LIMIT = 20;

export function listConsultations(
  filters: {
    patient?: string;
    doctor?: string;
    status?: ConsultationStatus;
    limit?: number;
    offset?: number;
  } = {},
) {
  const params = new URLSearchParams();
  if (filters.patient) params.set("patient_id", filters.patient);
  if (filters.doctor) params.set("doctor_id", filters.doctor);
  if (filters.status) params.set("status", filters.status);
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  const query = params.toString();
  return request<ConsultationPage>(`/consultations${query ? `?${query}` : ""}`);
}

export const getConsultation = (id: string) => request<Consultation>(`/consultations/${id}`);

/** Opens the notes for a patient in the room, or hands back the ones already open. */
export const openNotes = (queueEntryId: string) =>
  post<Consultation>("/consultations", { queue_entry_id: queueEntryId });

export const saveNotes = (id: string, version: number, changes: NoteChanges) =>
  request<Consultation>(`/consultations/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ version, ...changes }),
  });

export const finishNotes = (id: string, version: number) =>
  post<Consultation>(`/consultations/${id}/complete`, { version });

export const addAddendum = (id: string, body: string) =>
  post<Consultation>(`/consultations/${id}/addenda`, { body });

/** A follow-up as the doctor thinks of it: in so many days. */
export const FOLLOW_UP_CHOICES = [3, 7, 14, 30] as const;

export function daysAfter(date: string, days: number): string {
  const day = new Date(`${date}T00:00:00`);
  day.setDate(day.getDate() + days);
  const local = new Date(day.getTime() - day.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export function daysBetween(from: string, to: string): number {
  const start = new Date(`${from}T00:00:00`).getTime();
  const end = new Date(`${to}T00:00:00`).getTime();
  return Math.round((end - start) / 86_400_000);
}
