import { post, request } from "@/lib/api";

export type ClinicStatus = "pending" | "active" | "suspended";

export type Limits = {
  max_doctors: number | null;
  max_staff: number | null;
  max_patients: number | null;
  max_appointments_per_month: number | null;
  max_storage_mb: number | null;
};

export type Plan = {
  id: string;
  slug: string;
  name: string;
  description: string;
  price_monthly: string;
  limits: Limits;
  clinics: number;
};

export type Standing = {
  plan_id: string;
  plan_name: string;
  chosen_name: string;
  trial_ends_at: string | null;
  on_trial: boolean;
  trial_over: boolean;
};

export type ClinicRow = {
  id: string;
  name: string;
  slug: string;
  status: ClinicStatus;
  created_at: string;
  set_up: boolean;
  standing: Standing;
  owner: { name: string; email: string } | null;
  doctors: number;
  staff: number;
  patients: number;
  appointments_this_month: number;
  last_active_at: string | null;
};

export type ClinicPage = {
  items: ClinicRow[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
  statuses: { all: number } & Record<ClinicStatus, number>;
};

export type Measure = { used: number; limit: number | null };

export type PlatformEvent = {
  id: string;
  action: "platform.suspended" | "platform.reactivated" | "platform.plan_changed";
  actor_name: string;
  changes: Record<string, unknown> | null;
  created_at: string;
};

export type ClinicDetail = ClinicRow & {
  phone: string | null;
  email: string | null;
  city: string | null;
  timezone: string;
  usage: Record<Usage, Measure>;
  history: PlatformEvent[];
};

export type Usage = "doctors" | "staff" | "patients" | "appointments_this_month" | "storage_mb";

export type Metrics = {
  clinics: number;
  statuses: Record<ClinicStatus, number>;
  new_clinics_this_month: number;
  accounts: number;
  doctors: number;
  patients: number;
  appointments_this_month: number;
  on_trial: number;
  signups: { starts: string; clinics: number }[];
  plans: { id: string; name: string; clinics: number }[];
};

export type Sort = "-created_at" | "created_at" | "name";

export const PER_PAGE = 25;

export const getMetrics = () => request<Metrics>("/platform/metrics");

export function listClinics(filters: {
  q?: string;
  status?: ClinicStatus | null;
  plan?: string | null;
  sort?: Sort;
  page?: number;
  per_page?: number;
}) {
  const query = new URLSearchParams();
  if (filters.q) query.set("q", filters.q);
  if (filters.status) query.set("status", filters.status);
  if (filters.plan) query.set("plan_id", filters.plan);
  if (filters.sort && filters.sort !== "-created_at") query.set("sort", filters.sort);
  if (filters.page && filters.page > 1) query.set("page", String(filters.page));
  query.set("per_page", String(filters.per_page ?? PER_PAGE));
  return request<ClinicPage>(`/platform/organizations?${query}`);
}

export const getClinic = (id: string) =>
  request<ClinicDetail>(`/platform/organizations/${encodeURIComponent(id)}`);

export const suspendClinic = (id: string, reason: string) =>
  post<ClinicDetail>(`/platform/organizations/${encodeURIComponent(id)}/suspend`, { reason });

export const reactivateClinic = (id: string) =>
  post<ClinicDetail>(`/platform/organizations/${encodeURIComponent(id)}/reactivate`, {});

export const choosePlan = (id: string, planId: string) =>
  request<ClinicDetail>(`/platform/organizations/${encodeURIComponent(id)}/plan`, {
    method: "PUT",
    body: JSON.stringify({ plan_id: planId }),
  });

export const listPlans = () => request<Plan[]>("/platform/plans");

export const savePlan = (
  id: string,
  changes: { name?: string; description?: string; price_monthly?: string; limits?: Limits },
) =>
  request<Plan>(`/platform/plans/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });

export const STATUS_WORDS: Record<ClinicStatus, string> = {
  pending: "Setting up",
  active: "Running",
  suspended: "Suspended",
};

export const MEASURES: { key: Usage; limit: keyof Limits; label: string; unit?: string }[] = [
  { key: "doctors", limit: "max_doctors", label: "Doctors seeing patients" },
  { key: "staff", limit: "max_staff", label: "People on staff, with invitations waiting" },
  { key: "patients", limit: "max_patients", label: "Patients on the books" },
  {
    key: "appointments_this_month",
    limit: "max_appointments_per_month",
    label: "Bookings made this month",
  },
  { key: "storage_mb", limit: "max_storage_mb", label: "Files kept", unit: "MB" },
];

/** "Group trial, 12 days left", "Starter, trial over", or just the plan. */
export function describeStanding(standing: Standing, now: Date = new Date()): string {
  if (standing.on_trial && standing.trial_ends_at) {
    const days = Math.max(
      Math.ceil((new Date(standing.trial_ends_at).getTime() - now.getTime()) / 86_400_000),
      0,
    );
    const left = days <= 1 ? "last day" : `${days} days left`;
    return `${standing.chosen_name} trial, ${left}`;
  }
  if (standing.trial_over) return `${standing.plan_name}, trial over`;
  return standing.plan_name;
}

export function whole(value: number): string {
  return value.toLocaleString("en-IN");
}
