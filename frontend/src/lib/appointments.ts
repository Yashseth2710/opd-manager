import { post, request } from "@/lib/api";

export type AppointmentType = "consultation" | "follow_up";
export type Source = "desk" | "phone";
export type Status =
  | "scheduled"
  | "confirmed"
  | "checked_in"
  | "waiting"
  | "in_consultation"
  | "completed"
  | "cancelled"
  | "no_show";

export type PatientRef = {
  id: string;
  patient_number: string;
  full_name: string;
  preferred_name: string | null;
  phone: string | null;
  age: string | null;
  gender: string | null;
  status: "active" | "archived";
  allergy_count: number;
};

export type DoctorRef = {
  id: string;
  display_name: string;
  speciality: string | null;
  room: string | null;
  status: "active" | "inactive";
};

export type Appointment = {
  id: string;
  patient: PatientRef;
  doctor: DoctorRef;
  /** The clinic's own date and wall clock, which is what gets shown. */
  date: string;
  start_time: string;
  end_time: string;
  scheduled_start: string;
  scheduled_end: string;
  appointment_type: AppointmentType;
  source: Source;
  status: Status;
  reason: string | null;
  notes: string | null;
  fee: string;
  cancelled_reason: string | null;
  cancelled_at: string | null;
  booked_by_name: string | null;
  created_at: string;
  /** Against the clinic's clock, not this browser's. */
  has_started: boolean;
  is_over: boolean;
  /** The clinic's today, the only day anybody can be checked in for. */
  is_today: boolean;
  conflict: string | null;
  /** The number they were given at check-in, once they have one. */
  queue_token: number | null;
};

export type AppointmentEvent = {
  id: string;
  event:
    | "booked"
    | "confirmed"
    | "rescheduled"
    | "cancelled"
    | "no_show"
    | "edited"
    | "checked_in"
    | "check_in_undone"
    | "started"
    | "seen"
    | "left";
  from_status: Status | null;
  to_status: Status;
  detail: string | null;
  actor_name: string | null;
  created_at: string;
};

export type AppointmentDetail = Appointment & { history: AppointmentEvent[] };

export type AppointmentDay = {
  date: string;
  day_name: string;
  is_today: boolean;
  items: Appointment[];
  only_doctor_id: string | null;
  unlinked: boolean;
};

export type PatientAppointments = {
  upcoming: Appointment[];
  history: Appointment[];
};

export type Booking = {
  patient_id: string;
  doctor_id: string;
  date: string;
  start_time: string;
  appointment_type: AppointmentType;
  source: Source;
  reason?: string | null;
  notes?: string | null;
};

export type Changes = Partial<Omit<Booking, "patient_id">>;

export function getDay({ date, doctor }: { date?: string; doctor?: string } = {}) {
  const params = new URLSearchParams();
  if (date) params.set("date", date);
  if (doctor) params.set("doctor_id", doctor);
  const query = params.toString();
  return request<AppointmentDay>(`/appointments${query ? `?${query}` : ""}`);
}

export const getAppointment = (id: string) => request<AppointmentDetail>(`/appointments/${id}`);

export const getPatientAppointments = (patientId: string) =>
  request<PatientAppointments>(`/patients/${patientId}/appointments`);

export const bookAppointment = (booking: Booking) =>
  post<AppointmentDetail>("/appointments", booking);

export const changeAppointment = (id: string, changes: Changes) =>
  request<AppointmentDetail>(`/appointments/${id}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });

export const confirmAppointment = (id: string) =>
  post<AppointmentDetail>(`/appointments/${id}/confirm`, {});

export const cancelAppointment = (id: string, reason: string | null) =>
  post<AppointmentDetail>(`/appointments/${id}/cancel`, { reason });

export const markNoShow = (id: string) =>
  post<AppointmentDetail>(`/appointments/${id}/no-show`, {});

/**
 * What each state is called at the desk, which is not always what the data
 * calls it: "scheduled" is how a system says what a receptionist calls
 * booked.
 */
export const STATUS_LABELS: Record<Status, string> = {
  scheduled: "Booked",
  confirmed: "Confirmed",
  checked_in: "Checked in",
  waiting: "Waiting",
  in_consultation: "With the doctor",
  completed: "Seen",
  cancelled: "Cancelled",
  no_show: "No-show",
};

/** The status colour tokens, one per state and the same everywhere. */
export const STATUS_COLOURS: Record<Status, string> = {
  scheduled: "var(--color-state-scheduled)",
  confirmed: "var(--color-state-confirmed)",
  checked_in: "var(--color-state-waiting)",
  waiting: "var(--color-state-waiting)",
  in_consultation: "var(--color-state-consulting)",
  completed: "var(--color-state-completed)",
  cancelled: "var(--color-state-cancelled)",
  no_show: "var(--color-state-noshow)",
};

export const TYPE_LABELS: Record<AppointmentType, string> = {
  consultation: "Consultation",
  follow_up: "Follow-up",
};

export const SOURCE_LABELS: Record<Source, string> = {
  desk: "At the desk",
  phone: "By phone",
};

/** Still ahead of the patient, and so still movable or cancellable. */
export const isOpen = (status: Status) => status === "scheduled" || status === "confirmed";

/** Given up or missed, so the time it held is free again. */
export const isReleased = (status: Status) => status === "cancelled" || status === "no_show";

/** "Thursday 18 September", or with the year when it is not this one. */
export function longDate(value: string): string {
  const day = new Date(`${value}T00:00:00`);
  const sameYear = day.getFullYear() === new Date().getFullYear();
  return day.toLocaleDateString("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

/** "Thu 18 Sep", for lists where the long form would wrap. */
export function shortDate(value: string): string {
  const day = new Date(`${value}T00:00:00`);
  const sameYear = day.getFullYear() === new Date().getFullYear();
  return day.toLocaleDateString("en-IN", {
    weekday: "short",
    day: "numeric",
    month: "short",
    ...(sameYear ? {} : { year: "numeric" }),
  });
}

/** An instant, as the clinic's staff would say when something happened. */
export function whenItHappened(value: string): string {
  return new Date(value).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** What goes in the address bar to book, with whatever is already known. */
export function bookingHref(known: {
  patient?: string;
  doctor?: string;
  date?: string;
  time?: string;
}): string {
  const params = new URLSearchParams();
  if (known.patient) params.set("patient", known.patient);
  if (known.doctor) params.set("doctor", known.doctor);
  if (known.date) params.set("date", known.date);
  if (known.time) params.set("time", known.time.slice(0, 5));
  const query = params.toString();
  return `/appointments/new${query ? `?${query}` : ""}`;
}

/** The screen for one day, keeping a doctor filter if there is one. */
export function dayHref(date: string, doctor?: string | null): string {
  const params = new URLSearchParams({ date });
  if (doctor) params.set("doctor", doctor);
  return `/appointments?${params}`;
}
