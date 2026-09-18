import { post, request } from "@/lib/api";
import type {
  AppointmentDetail,
  AppointmentType,
  DoctorRef,
  PatientRef,
  Status,
} from "@/lib/appointments";

export type QueueStatus =
  "waiting" | "called" | "in_consultation" | "completed" | "skipped" | "no_show";

export type Priority = "normal" | "urgent";

export type QueueEntry = {
  id: string;
  token: number;
  status: QueueStatus;
  priority: Priority;
  patient: PatientRef;
  doctor: DoctorRef;
  appointment: {
    id: string;
    start_time: string;
    end_time: string;
    appointment_type: AppointmentType;
    reason: string | null;
    status: Status;
  } | null;
  reason: string | null;
  checked_in_at: string;
  called_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  /** Worked out on the server, whose clock the timestamps came from. */
  waited_minutes: number;
  position: number | null;
  expected_wait_minutes: number | null;
};

export type Arrival = {
  id: string;
  patient: PatientRef;
  start_time: string;
  end_time: string;
  appointment_type: AppointmentType;
  status: Status;
  reason: string | null;
  is_late: boolean;
};

export type Lane = {
  doctor: DoctorRef;
  closed: string | null;
  now_seeing: QueueEntry | null;
  called: QueueEntry | null;
  waiting: QueueEntry[];
  skipped: QueueEntry[];
  done: QueueEntry[];
  expected: Arrival[];
  seen_count: number;
  average_minutes: number;
};

export type QueueDay = {
  date: string;
  day_name: string;
  lanes: Lane[];
  only_doctor_id: string | null;
  unlinked: boolean;
};

export type Step = "call" | "start" | "complete" | "skip" | "recall" | "no-show";

/** How often a screen showing the queue asks again, while it is in view. */
export const POLL_MS = 5_000;

export const getQueue = (doctor?: string) =>
  request<QueueDay>(`/queue${doctor ? `?doctor_id=${encodeURIComponent(doctor)}` : ""}`);

export const checkIn = (appointmentId: string, priority: Priority = "normal") =>
  post<QueueEntry>(`/appointments/${appointmentId}/check-in`, { priority });

export const addWalkIn = (walkIn: {
  patient_id: string;
  doctor_id: string;
  reason?: string | null;
  priority: Priority;
}) => post<QueueEntry>("/queue/walk-in", walkIn);

export const takeStep = (entryId: string, step: Step) =>
  post<QueueEntry>(`/queue/${entryId}/${step}`, {});

export const setPriority = (entryId: string, priority: Priority) =>
  request<QueueEntry>(`/queue/${entryId}`, {
    method: "PATCH",
    body: JSON.stringify({ priority }),
  });

/** Takes back a check-in. A booked patient's appointment comes back as it was. */
export const undoCheckIn = (entryId: string) =>
  request<AppointmentDetail | null>(`/queue/${entryId}`, { method: "DELETE" });

/** "12 min", "1 hr 5 min": a wait, the way somebody at the desk says it. */
export function spokenMinutes(minutes: number): string {
  if (minutes < 1) return "under a minute";
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  const left = minutes % 60;
  return left ? `${hours} hr ${left} min` : `${hours} hr`;
}

/** A guess, and said like one. Nobody should be promised a minute. */
export function roughly(minutes: number | null): string | null {
  if (minutes === null) return null;
  if (minutes <= 0) return "Next in line";
  const rounded =
    minutes < 15 ? Math.max(5, Math.round(minutes / 5) * 5) : Math.round(minutes / 10) * 10;
  return `In about ${spokenMinutes(rounded)}`;
}

/** The name somebody is called by, which is not always the one on file. */
export function calledBy(patient: PatientRef): string {
  return patient.preferred_name ?? patient.full_name.split(" ")[0] ?? patient.full_name;
}
