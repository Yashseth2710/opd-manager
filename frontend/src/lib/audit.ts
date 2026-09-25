import type { Route } from "next";
import { request } from "@/lib/api";

export type Area =
  "patients" | "appointments" | "clinical" | "billing" | "people" | "clinic" | "sign_in";

export type Entry = {
  id: string;
  created_at: string;
  actor_id: string | null;
  actor_name: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  resource_label: string | null;
  changes: Record<string, unknown> | null;
  ip_address: string | null;
  user_agent: string | null;
};

export type LogPage = {
  items: Entry[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
  actors: { id: string; name: string }[];
};

export type Asked = {
  area: Area | "";
  actor: string;
  record: string;
  from: string;
  to: string;
  q: string;
  page: number;
};

export const AREAS: { value: Area | ""; label: string }[] = [
  { value: "", label: "Everything" },
  { value: "patients", label: "Patients" },
  { value: "appointments", label: "Appointments" },
  { value: "clinical", label: "Clinical" },
  { value: "billing", label: "Billing" },
  { value: "people", label: "Staff and doctors" },
  { value: "clinic", label: "Clinic" },
  { value: "sign_in", label: "Sign-ins" },
];

export function readLog(asked: Asked) {
  const params = new URLSearchParams({ page: String(asked.page), per_page: "50" });
  if (asked.area) params.set("area", asked.area);
  if (asked.actor) params.set("actor_id", asked.actor);
  if (asked.record) params.set("resource_id", asked.record);
  if (asked.from) params.set("from", asked.from);
  if (asked.to) params.set("to", asked.to);
  if (asked.q) params.set("q", asked.q);
  return request<LogPage>(`/audit-logs?${params}`);
}

/** What the person did, as the middle of a sentence that starts with them. */
const DID: Record<string, string> = {
  "patient.registered": "registered",
  "patient.updated": "edited the details of",
  "patient.archived": "archived",
  "patient.restored": "brought back",
  "allergy.added": "added an allergy for",
  "allergy.removed": "removed an allergy from",
  "document.uploaded": "uploaded a document for",
  "document.changed": "changed a document for",
  "document.removed": "removed a document from",
  "appointment.booked": "booked",
  "appointment.changed": "changed the appointment for",
  "appointment.confirmed": "confirmed",
  "appointment.cancelled": "cancelled",
  "appointment.no_show": "marked {} as a no-show",
  "visit.checked_in": "checked in",
  "visit.walked_in": "added a walk-in,",
  "visit.no_show": "marked {} as gone without being seen",
  "visit.check_in_undone": "took back the check-in of",
  "consultation.started": "opened notes for",
  "consultation.completed": "completed the notes for",
  "consultation.addendum_added": "added to the notes for",
  "prescription.corrected": "corrected prescription",
  "vitals.taken": "took vitals for",
  "vitals.corrected": "corrected the vitals of",
  "vitals.removed": "removed the vitals of",
  "lab.ordered": "ordered",
  "lab.removed": "took {} off the orders",
  "lab.cancelled": "cancelled",
  "lab.resulted": "entered the result of",
  "lab.result_changed": "changed the result of",
  "lab.result_cleared": "cleared the result of",
  "lab.reviewed": "marked {} as seen",
  "invoice.raised": "raised",
  "invoice.changed": "changed",
  "invoice.discarded": "discarded",
  "invoice.issued": "issued",
  "invoice.voided": "voided",
  "payment.taken": "took a payment on",
  "payment.refunded": "gave money back on",
  "payment.online": "paid",
  "payment_link.raised": "sent a payment link for",
  "payment_link.cancelled": "cancelled the payment link for",
  "doctor.added": "added",
  "doctor.changed": "edited the profile of",
  "doctor.deactivated": "deactivated",
  "doctor.restored": "brought back",
  "doctor.hours_set": "set the hours of",
  "doctor.leave_added": "recorded leave for",
  "doctor.leave_removed": "took back the leave of",
  "staff.invited": "invited",
  "staff.invitation_withdrawn": "withdrew the invitation to",
  "staff.joined": "joined the clinic",
  "staff.role_changed": "changed the role of",
  "staff.suspended": "suspended",
  "staff.restored": "let {} back in",
  "clinic.details_changed": "changed the details of",
  "clinic.settings_changed": "changed the settings of",
  "clinic.opened": "finished setting up",
  "platform.suspended": "suspended",
  "platform.reactivated": "reactivated",
  "platform.plan_changed": "changed the plan of",
  "signin.failed": "got the password wrong for",
  "signin.locked": "locked the account of",
};

/**
 * The words either side of the record's name. Most actions put the name last;
 * a few read better with it in the middle, and joining names nothing at all.
 */
export function sentence(entry: Entry): { before: string; after: string; names: boolean } {
  const words = DID[entry.action] ?? entry.action.replace(/[._]/g, " ");
  if (entry.action === "staff.joined") return { before: words, after: "", names: false };
  const [before = "", after = ""] = words.split("{}");
  return { before: before.trim(), after: after.trim(), names: true };
}

/** The area an entry sits in, for its marker. */
export function areaOf(entry: Entry): Area {
  const type = entry.resource_type;
  if (["patient", "allergy", "document"].includes(type)) return "patients";
  if (["appointment", "visit"].includes(type)) return "appointments";
  if (["consultation", "vitals", "lab_order", "prescription"].includes(type)) return "clinical";
  if (["invoice", "payment_link"].includes(type)) return "billing";
  if (["staff", "invitation", "doctor"].includes(type)) return "people";
  if (type === "account") return "sign_in";
  return "clinic";
}

/** Where the record the entry is about can be opened, if anywhere. */
export function whereItIs(entry: Entry): Route | null {
  const id = entry.resource_id;
  switch (entry.resource_type) {
    case "clinic":
      return "/settings" as Route;
    case "staff":
    case "invitation":
    case "account":
      return "/staff" as Route;
  }
  if (!id) return null;
  switch (entry.resource_type) {
    case "patient":
    case "allergy":
    case "document":
    case "visit":
    case "vitals":
      return `/patients/${id}` as Route;
    case "appointment":
      return `/appointments/${id}` as Route;
    case "consultation":
      return `/consultations/${id}` as Route;
    case "prescription":
      return `/prescriptions/${id}` as Route;
    case "lab_order":
      return `/lab/${id}` as Route;
    case "invoice":
    case "payment_link":
      return `/billing/${id}` as Route;
    case "doctor":
      return `/doctors/${id}` as Route;
  }
  return null;
}

const FIELD: Record<string, string> = {
  first_name: "First name",
  last_name: "Surname",
  preferred_name: "Known as",
  alternate_phone: "Other phone",
  date_of_birth: "Date of birth",
  blood_group: "Blood group",
  emergency_contact: "Emergency contact",
  start_time: "Time",
  end_time: "Ends",
  appointment_type: "Kind of visit",
  discount_amount: "Discount",
  discount_reason: "Reason for discount",
  headline: "Charged for",
  lines: "Lines",
  method: "Paid by",
  emailed_to: "Emailed to",
  consultation_fee: "Consultation fee",
  follow_up_fee: "Follow-up fee",
  consultation_duration_minutes: "Visit length",
  slot_duration_minutes: "Slot length",
  years_of_experience: "Years in practice",
  registration_number: "Registration no.",
  user_id: "Linked account",
  systolic_mmhg: "Systolic",
  diastolic_mmhg: "Diastolic",
  pulse_bpm: "Pulse",
  temperature_c: "Temperature",
  spo2_percent: "SpO₂",
  respiratory_rate: "Breathing rate",
  weight_kg: "Weight",
  height_cm: "Height",
  glucose_mg_dl: "Glucose",
  flagged: "Outside range",
  attempt: "Attempt",
  excess: "Paid over",
  issued: "Issued with it",
};

export function fieldName(key: string): string {
  if (FIELD[key]) return FIELD[key];
  const words = key.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function shown(value: unknown): string {
  if (value === null || value === undefined || value === "") return "nothing";
  if (value === true) return "yes";
  if (value === false) return "no";
  if (typeof value === "object") {
    const parts = Object.values(value as Record<string, unknown>).filter(
      (part) => part !== null && part !== "",
    );
    return parts.length ? parts.map(String).join(", ") : "nothing";
  }
  return String(value);
}

/** A change is stored as [before, after]; anything else is a fact about the action. */
export function asChange(value: unknown): [unknown, unknown] | null {
  return Array.isArray(value) && value.length === 2 ? [value[0], value[1]] : null;
}

/** "Chrome on Windows", enough to recognise a device without reading the header. */
export function device(agent: string | null): string | null {
  if (!agent) return null;
  const browser = /Edg\//.test(agent)
    ? "Edge"
    : /OPR\//.test(agent)
      ? "Opera"
      : /Firefox\//.test(agent)
        ? "Firefox"
        : /Chrome\//.test(agent)
          ? "Chrome"
          : /Safari\//.test(agent)
            ? "Safari"
            : null;
  const system = /Windows/.test(agent)
    ? "Windows"
    : /Android/.test(agent)
      ? "Android"
      : /iPhone|iPad/.test(agent)
        ? "iPhone"
        : /Mac OS X/.test(agent)
          ? "Mac"
          : /Linux/.test(agent)
            ? "Linux"
            : null;
  if (browser && system) return `${browser} on ${system}`;
  return browser ?? system ?? "Another program";
}
