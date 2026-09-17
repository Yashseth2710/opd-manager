import { post, request } from "@/lib/api";

export type Gender = "female" | "male" | "other";
export type BloodGroup = "A+" | "A-" | "B+" | "B-" | "AB+" | "AB-" | "O+" | "O-";
export type Severity = "mild" | "moderate" | "severe";

export const GENDERS: Gender[] = ["female", "male", "other"];
export const BLOOD_GROUPS: BloodGroup[] = ["A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"];
export const SEVERITIES: Severity[] = ["mild", "moderate", "severe"];

export type PatientAddress = {
  line1: string;
  line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
};

export type EmergencyContact = {
  name: string;
  relationship: string;
  phone: string;
};

export type Allergy = {
  id: string;
  substance: string;
  reaction: string | null;
  severity: Severity;
  created_at: string;
};

export type PatientSummary = {
  id: string;
  patient_number: string;
  full_name: string;
  preferred_name: string | null;
  phone: string | null;
  date_of_birth: string | null;
  age: string | null;
  gender: Gender | null;
  blood_group: BloodGroup | null;
  status: "active" | "archived";
  allergy_count: number;
  created_at: string;
};

export type Patient = PatientSummary & {
  first_name: string;
  last_name: string;
  alternate_phone: string | null;
  email: string | null;
  address: Partial<PatientAddress> | null;
  emergency_contact: Partial<EmergencyContact> | null;
  notes: string | null;
  archived_at: string | null;
  registered_by_name: string | null;
  allergies: Allergy[];
};

/** A record that might be the same person, and the reason it surfaced. */
export type DuplicateCandidate = PatientSummary & { reason: string };

export type PatientPage = {
  items: PatientSummary[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
};

export type PatientDraft = {
  first_name: string;
  last_name: string;
  preferred_name?: string | null;
  phone?: string | null;
  alternate_phone?: string | null;
  email?: string | null;
  date_of_birth?: string | null;
  gender?: Gender | null;
  blood_group?: BloodGroup | null;
  address?: Partial<PatientAddress> | null;
  emergency_contact?: Partial<EmergencyContact> | null;
  notes?: string | null;
};

export type PatientQuery = {
  q?: string;
  status?: "active" | "archived" | "all";
  page?: number;
  per_page?: number;
};

export const PAGE_SIZE = 25;

export function listPatients({
  q = "",
  status = "active",
  page = 1,
  per_page = PAGE_SIZE,
}: PatientQuery = {}): Promise<PatientPage> {
  const params = new URLSearchParams({
    status,
    page: String(page),
    per_page: String(per_page),
  });
  if (q.trim()) params.set("q", q.trim());
  return request<PatientPage>(`/patients?${params}`);
}

export const getPatient = (id: string) => request<Patient>(`/patients/${id}`);

export const registerPatient = (draft: PatientDraft & { confirm_duplicate?: boolean }) =>
  post<Patient>("/patients", draft);

export const savePatient = (id: string, changes: Partial<PatientDraft>) =>
  request<Patient>(`/patients/${id}`, { method: "PATCH", body: JSON.stringify(changes) });

export const archivePatient = (id: string) => post<Patient>(`/patients/${id}/archive`, {});

export const restorePatient = (id: string) => post<Patient>(`/patients/${id}/restore`, {});

export const checkDuplicates = (draft: {
  first_name?: string;
  last_name?: string;
  phone?: string | null;
  email?: string | null;
  date_of_birth?: string | null;
  exclude_id?: string;
}) => post<DuplicateCandidate[]>("/patients/check-duplicates", draft);

export const recordAllergy = (
  patientId: string,
  allergy: { substance: string; reaction?: string | null; severity: Severity },
) => post<Allergy>(`/patients/${patientId}/allergies`, allergy);

export const removeAllergy = (patientId: string, allergyId: string) =>
  request<{ removed: boolean }>(`/patients/${patientId}/allergies/${allergyId}`, {
    method: "DELETE",
  });

/** Initials for the avatar on the list, from whichever names exist. */
export function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  const first = parts.at(0);
  if (!first) return "?";
  const last = parts.at(-1);
  if (parts.length === 1) return first.slice(0, 2).toUpperCase();
  return `${first.charAt(0)}${last?.charAt(0) ?? ""}`.toUpperCase();
}

/** A phone number grouped the way it is read back, without changing it. */
export function readablePhone(phone: string | null): string {
  if (!phone) return "";
  const local = phone.startsWith("+91") ? phone.slice(3) : phone;
  if (local.length === 10) {
    const spaced = `${local.slice(0, 5)} ${local.slice(5)}`;
    return phone.startsWith("+91") ? `+91 ${spaced}` : spaced;
  }
  return phone;
}

/** A line describing a person at a glance: "38 y · female · O+". */
export function describe(patient: PatientSummary): string {
  return [patient.age, patient.gender, patient.blood_group].filter(Boolean).join(" · ");
}
