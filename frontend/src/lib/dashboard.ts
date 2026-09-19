import { request } from "@/lib/api";
import type { DoctorRef, PatientRef } from "@/lib/appointments";
import type { Priority } from "@/lib/queue";
import type { VitalsBrief } from "@/lib/vitals";

export type Counts = {
  booked: number;
  to_come: number;
  late: number;
  walk_ins: number;
  waiting: number;
  with_doctor: number;
  seen: number;
  no_shows: number;
};

export type InRoom = {
  entry_id: string;
  token: number;
  patient: PatientRef;
  minutes: number;
  consultation_id: string | null;
};

export type DayLane = {
  doctor: DoctorRef;
  closed: string | null;
  now_seeing: InRoom | null;
  called: InRoom | null;
  waiting: number;
  longest_wait_minutes: number | null;
  seen: number;
  to_come: number;
  average_minutes: number;
  /** The one called, or the head of the line in the order the queue runs. */
  next: WaitingPatient | null;
};

export type WaitingPatient = {
  entry_id: string;
  token: number;
  patient: PatientRef;
  doctor: DoctorRef;
  priority: Priority;
  reason: string | null;
  waited_minutes: number;
  vitals: VitalsBrief | null;
};

export type DueArrival = {
  appointment_id: string;
  patient: PatientRef;
  doctor: DoctorRef;
  start_time: string;
  is_late: boolean;
};

export type DueBack = {
  patient: PatientRef;
  doctor: DoctorRef;
  asked_on: string;
  consultation_id: string;
  state: "here" | "seen" | "booked" | "not_booked";
  booked_for: string | null;
};

export type Unfinished = {
  consultation_id: string;
  patient: PatientRef;
  visit_date: string;
  chief_complaint: string | null;
};

export type Today = {
  date: string;
  day_name: string;
  view: "clinic" | "doctor" | "unlinked";
  counts: Counts;
  lanes: DayLane[];
  waiting: WaitingPatient[];
  waiting_total: number;
  without_vitals: number;
  arrivals: DueArrival[];
  arrivals_total: number;
  due_back: DueBack[];
  unfinished: Unfinished[];
  unfinished_total: number;
};

/** Asked again this often while the page is open. */
export const REFRESH_MS = 30_000;

export const getToday = () => request<Today>("/dashboard/summary");

/** A wait at which the desk should go and say something. */
export const LONG_WAIT_MINUTES = 45;

export function greeting(hour: number): string {
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}
