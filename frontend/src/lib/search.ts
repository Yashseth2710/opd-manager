import { request } from "@/lib/api";
import { STATUS_LABELS, type Status } from "@/lib/appointments";
import { STATUS_WORDS, type InvoiceStatus } from "@/lib/billing";
import { money } from "@/lib/clinic";

export type Kind = "patients" | "appointments" | "bills" | "doctors" | "staff";

export type Found = {
  query: string;
  searched: Kind[];
  patients: {
    id: string;
    patient_number: string;
    full_name: string;
    phone: string | null;
    age: string | null;
    gender: string | null;
    archived: boolean;
  }[];
  appointments: {
    id: string;
    patient_name: string;
    patient_number: string;
    doctor_name: string;
    starts_at: string;
    status: Status;
  }[];
  bills: {
    id: string;
    invoice_number: string | null;
    status: InvoiceStatus;
    total: string;
    balance: string;
    patient_name: string;
    placed_at: string;
  }[];
  doctors: { id: string; display_name: string; speciality: string | null; active: boolean }[];
  staff: {
    id: string;
    full_name: string;
    email: string;
    role: string | null;
    active: boolean;
  }[];
};

/** Below this the server answers with nothing, so the box does not ask. */
export const SHORTEST = 2;

export const search = (typed: string, signal?: AbortSignal) =>
  request<Found>(`/search?${new URLSearchParams({ q: typed })}`, { signal });

/** Collapses runs of spaces the way the server does, so both agree on the term. */
export const squeezed = (typed: string) => typed.trim().replace(/\s+/g, " ");

/** One line in the results, whatever kind of record it stands for. */
export type Hit = {
  kind: Kind | "page";
  id: string;
  title: string;
  detail: string;
  href: string;
  /** A word beside the title when the record is not in its usual state. */
  flag?: string;
  /**
   * What the opened-lately list says underneath instead. A booking moves and
   * a bill gets paid after somebody opens it, so the list keeps only what
   * stays true rather than a time or a balance that may have gone stale.
   */
  kept?: string;
};

export const HEADINGS: Record<Kind | "page", string> = {
  page: "Go to",
  patients: "Patients",
  appointments: "Coming up",
  bills: "Bills",
  doctors: "Doctors",
  staff: "Staff",
};

/** What each kind is, said the way "nothing matched" names where it looked. */
const LOOKED_IN: Record<Kind, string> = {
  patients: "patients",
  appointments: "bookings coming up",
  bills: "bills",
  doctors: "doctors",
  staff: "staff",
};

export function lookedIn(kinds: Kind[]): string {
  const words = kinds.map((kind) => LOOKED_IN[kind]);
  if (words.length <= 1) return words.join("");
  return `${words.slice(0, -1).join(", ")} and ${words.at(-1)}`;
}

function when(iso: string, timeZone: string): string {
  const at = new Date(iso);
  const day = new Intl.DateTimeFormat("en-IN", {
    timeZone,
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(at);
  const time = new Intl.DateTimeFormat("en-IN", {
    timeZone,
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  })
    .format(at)
    .toLowerCase();
  return `${day}, ${time}`;
}

const joined = (...parts: (string | null | undefined | false)[]) =>
  parts.filter(Boolean).join(", ");

/** Every kind flattened into the one list the keyboard moves through. */
export function hits(found: Found, clinic: { timezone: string; currency: string }): Hit[] {
  return [
    ...found.patients.map((patient) => ({
      kind: "patients" as const,
      id: patient.id,
      title: patient.full_name,
      detail: joined(patient.patient_number, patient.age, patient.phone),
      href: `/patients/${patient.id}`,
      flag: patient.archived ? "Archived" : undefined,
      kept: patient.patient_number,
    })),
    ...found.appointments.map((booked) => ({
      kind: "appointments" as const,
      id: booked.id,
      title: booked.patient_name,
      detail: joined(when(booked.starts_at, clinic.timezone), booked.doctor_name),
      href: `/appointments/${booked.id}`,
      flag: booked.status === "scheduled" ? undefined : STATUS_LABELS[booked.status],
      kept: `Booking with ${booked.doctor_name}`,
    })),
    ...found.bills.map((bill) => ({
      kind: "bills" as const,
      id: bill.id,
      title: bill.invoice_number ?? "Draft bill",
      detail: joined(
        bill.patient_name,
        money(bill.total, clinic.currency),
        Number(bill.balance) > 0 && bill.status !== "draft"
          ? `${money(bill.balance, clinic.currency)} owed`
          : null,
      ),
      href: `/billing/${bill.id}`,
      flag: STATUS_WORDS[bill.status],
      kept: `Bill for ${bill.patient_name}`,
    })),
    ...found.doctors.map((doctor) => ({
      kind: "doctors" as const,
      id: doctor.id,
      title: doctor.display_name,
      detail: doctor.speciality ?? "Doctor",
      href: `/doctors/${doctor.id}`,
      flag: doctor.active ? undefined : "Not seeing patients",
      kept: doctor.speciality ?? "Doctor",
    })),
    ...found.staff.map((person) => ({
      kind: "staff" as const,
      id: person.id,
      title: person.full_name,
      detail: joined(person.role, person.email),
      href: `/staff?member=${person.id}`,
      flag: person.active ? undefined : "Suspended",
      kept: person.email,
    })),
  ];
}

/*
  Records opened from the box, newest first, kept on this computer for the
  person signed in. Clinic computers are shared, so the list is keyed by
  account and cleared on signing out.
*/
const RECENT_PREFIX = "opd.recent.";
const KEPT = 6;

export function recentFor(userId: string): Hit[] {
  try {
    const stored = localStorage.getItem(RECENT_PREFIX + userId);
    const parsed: unknown = stored ? JSON.parse(stored) : [];
    return Array.isArray(parsed) ? (parsed as Hit[]).slice(0, KEPT) : [];
  } catch {
    return [];
  }
}

export function remember(userId: string, hit: Hit): void {
  if (hit.kind === "page") return;
  try {
    const lasting: Hit = {
      kind: hit.kind,
      id: hit.id,
      title: hit.title,
      detail: hit.kept ?? "",
      href: hit.href,
    };
    const others = recentFor(userId).filter(
      (each) => !(each.kind === hit.kind && each.id === hit.id),
    );
    localStorage.setItem(
      RECENT_PREFIX + userId,
      JSON.stringify([lasting, ...others].slice(0, KEPT)),
    );
  } catch {
    // Private windows and full storage both land here; the box works without it.
  }
}

export function forget(userId: string): void {
  try {
    localStorage.removeItem(RECENT_PREFIX + userId);
  } catch {
    // Nothing stored is nothing to clear.
  }
}

export function forgetEveryone(): void {
  try {
    for (const key of Object.keys(localStorage)) {
      if (key.startsWith(RECENT_PREFIX)) localStorage.removeItem(key);
    }
  } catch {
    // Nothing stored is nothing to clear.
  }
}
