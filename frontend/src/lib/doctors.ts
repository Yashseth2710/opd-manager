import { post, request } from "@/lib/api";

export type Title = "Dr" | "Prof" | "Mr" | "Ms" | "Mrs";
export type DoctorStatus = "active" | "inactive";

export const TITLES: Title[] = ["Dr", "Prof", "Mr", "Ms", "Mrs"];

/** Monday first, the way a rota is read and written. */
export const DAYS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
] as const;

export const SHORT_DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"] as const;

export type ScheduleBlock = {
  id: string;
  day_of_week: number;
  start_time: string;
  end_time: string;
  break_start: string | null;
  break_end: string | null;
  slot_duration_minutes: number | null;
};

/** A block being edited, before it has been saved and given an id. */
export type BlockDraft = Omit<ScheduleBlock, "id"> & { key: string };

export type Leave = {
  id: string;
  starts_on: string;
  ends_on: string;
  start_time: string | null;
  end_time: string | null;
  reason: string | null;
  created_at: string;
};

export type DoctorSummary = {
  id: string;
  display_name: string;
  full_name: string;
  title: Title;
  speciality: string | null;
  qualifications: string | null;
  room: string | null;
  status: DoctorStatus;
  consultation_fee: string;
  fee_from_clinic: boolean;
  slot_duration_minutes: number;
  working_days: number;
  has_account: boolean;
  created_at: string;
};

export type Doctor = DoctorSummary & {
  first_name: string;
  last_name: string;
  registration_number: string | null;
  years_of_experience: number | null;
  phone: string | null;
  email: string | null;
  languages: string[] | null;
  bio: string | null;
  follow_up_fee: string;
  follow_up_fee_from_clinic: boolean;
  own_consultation_fee: string | null;
  own_follow_up_fee: string | null;
  own_slot_duration_minutes: number | null;
  user_id: string | null;
  account_name: string | null;
  deactivated_at: string | null;
  schedule: ScheduleBlock[];
  leaves: Leave[];
};

export type DoctorDraft = {
  title: Title;
  first_name: string;
  last_name: string;
  speciality?: string | null;
  qualifications?: string | null;
  registration_number?: string | null;
  years_of_experience?: number | null;
  phone?: string | null;
  email?: string | null;
  room?: string | null;
  languages?: string[] | null;
  bio?: string | null;
  consultation_fee?: string | null;
  follow_up_fee?: string | null;
  slot_duration_minutes?: number | null;
  user_id?: string | null;
};

export type DoctorPage = {
  items: DoctorSummary[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
};

export type Slot = { start_time: string; end_time: string };

export type Availability = {
  date: string;
  day_of_week: number;
  day_name: string;
  working: boolean;
  reason: string | null;
  slot_duration_minutes: number;
  slots: Slot[];
};

export type DoctorQuery = {
  q?: string;
  speciality?: string;
  status?: "active" | "inactive" | "all";
  page?: number;
  per_page?: number;
};

export const PAGE_SIZE = 25;

export function listDoctors({
  q = "",
  speciality = "",
  status = "active",
  page = 1,
  per_page = PAGE_SIZE,
}: DoctorQuery = {}): Promise<DoctorPage> {
  const params = new URLSearchParams({
    status,
    page: String(page),
    per_page: String(per_page),
  });
  if (q.trim()) params.set("q", q.trim());
  if (speciality.trim()) params.set("speciality", speciality.trim());
  return request<DoctorPage>(`/doctors?${params}`);
}

export const getDoctor = (id: string) => request<Doctor>(`/doctors/${id}`);

export const listSpecialities = (status: DoctorQuery["status"] = "active") =>
  request<string[]>(`/doctors/specialities?status=${status}`);

export const addDoctor = (draft: DoctorDraft) => post<Doctor>("/doctors", draft);

export const saveDoctor = (id: string, changes: Partial<DoctorDraft>) =>
  request<Doctor>(`/doctors/${id}`, { method: "PATCH", body: JSON.stringify(changes) });

export const deactivateDoctor = (id: string) => post<Doctor>(`/doctors/${id}/deactivate`, {});

export const restoreDoctor = (id: string) => post<Doctor>(`/doctors/${id}/restore`, {});

export const getSchedule = (id: string) => request<ScheduleBlock[]>(`/doctors/${id}/schedule`);

export const saveSchedule = (id: string, blocks: Omit<ScheduleBlock, "id">[]) =>
  request<ScheduleBlock[]>(`/doctors/${id}/schedule`, {
    method: "PUT",
    body: JSON.stringify({ blocks }),
  });

export const getAvailability = (id: string, date: string) =>
  request<Availability>(`/doctors/${id}/availability?date=${date}`);

export const recordLeave = (
  id: string,
  leave: {
    starts_on: string;
    ends_on?: string | null;
    start_time?: string | null;
    end_time?: string | null;
    reason?: string | null;
  },
) => post<Leave>(`/doctors/${id}/leaves`, leave);

export const cancelLeave = (doctorId: string, leaveId: string) =>
  request<{ removed: boolean }>(`/doctors/${doctorId}/leaves/${leaveId}`, {
    method: "DELETE",
  });

/** Initials for the avatar, from whichever names exist. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts.at(0);
  if (!first) return "?";
  if (parts.length === 1) return first.slice(0, 2).toUpperCase();
  return `${first.charAt(0)}${parts.at(-1)?.charAt(0) ?? ""}`.toUpperCase();
}

/** "09:00:00" as "9:00 am", which is how a clinic writes its hours up. */
export function readableTime(value: string | null): string {
  if (!value) return "";
  const [hours = NaN, minutes = 0] = value.split(":").map(Number);
  if (Number.isNaN(hours)) return value;
  const suffix = hours < 12 ? "am" : "pm";
  const twelve = hours % 12 === 0 ? 12 : hours % 12;
  return `${twelve}:${String(minutes).padStart(2, "0")} ${suffix}`;
}

/** How long a slot runs, in minutes. */
export function slotMinutes(slot: Slot): number {
  const at = (value: string) => {
    const [hours = 0, minutes = 0] = value.split(":").map(Number);
    return hours * 60 + minutes;
  };
  return at(slot.end_time) - at(slot.start_time);
}

/**
 * How the free times read at the bottom of the list.
 *
 * A length is only named when every slot is that long. A clinic that runs
 * its evening at ten minutes a head and its morning at thirty has neither
 * number as the answer, and picking one of them is worse than picking none.
 */
export function countSlots(slots: Slot[]): string {
  const many = slots.length === 1 ? "1 appointment" : `${slots.length} appointments`;
  const lengths = new Set(slots.map(slotMinutes));
  const only = lengths.size === 1 ? [...lengths][0] : null;
  return only ? `${many} of ${only} minutes.` : `${many}.`;
}

/** What a time input needs, from what the API sends back. */
export const forInput = (value: string | null): string => (value ? value.slice(0, 5) : "");

export function readableDate(value: string): string {
  return new Date(`${value}T00:00:00`).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

export function describeLeave(leave: Leave): string {
  const span =
    leave.starts_on === leave.ends_on
      ? readableDate(leave.starts_on)
      : `${readableDate(leave.starts_on)} – ${readableDate(leave.ends_on)}`;
  if (!leave.start_time) return span;
  return `${span}, ${readableTime(leave.start_time)} – ${readableTime(leave.end_time)}`;
}

/** A line describing a doctor at a glance under their name. */
export function describe(doctor: DoctorSummary): string {
  return [doctor.speciality, doctor.qualifications].filter(Boolean).join(" · ");
}

/** The days of the week a rota touches, in order, for the list row. */
export function workingDays(blocks: ScheduleBlock[]): number[] {
  return [...new Set(blocks.map((item) => item.day_of_week))].sort((a, b) => a - b);
}

/** Today at the browser, as the date input and the API both want it. */
export function todayISO(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

export function shiftDate(value: string, days: number): string {
  const day = new Date(`${value}T00:00:00`);
  day.setDate(day.getDate() + days);
  const local = new Date(day.getTime() - day.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 10);
}

/**
 * Strips what a form produces but the API should not read as a value.
 *
 * A fee has to survive this as null rather than as "0": null means "follow
 * the clinic" and zero means "this doctor sees people for nothing".
 */
export function cleaned(draft: DoctorDraft): DoctorDraft {
  const blank = (value: unknown) => typeof value === "string" && value.trim() === "";
  const tidied = Object.fromEntries(
    Object.entries(draft).map(([key, value]) => [key, blank(value) ? null : value]),
  ) as DoctorDraft;

  const languages = (tidied.languages ?? []).map((one) => one.trim()).filter(Boolean);
  tidied.languages = languages.length ? languages : null;
  return tidied;
}
