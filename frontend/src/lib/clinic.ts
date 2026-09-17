import { post, request } from "@/lib/api";

export type Address = {
  line1: string;
  line2: string;
  city: string;
  state: string;
  postal_code: string;
  country: string;
};

export type Clinic = {
  id: string;
  name: string;
  slug: string;
  phone: string | null;
  email: string | null;
  website: string | null;
  timezone: string;
  currency: string;
  status: "pending" | "active" | "suspended";
  address: Partial<Address> | null;
  onboarding_completed_at: string | null;
};

export type ClinicSettings = {
  consultation_duration_minutes: number;
  consultation_fee: string;
  follow_up_fee: string;
  follow_up_window_days: number;
  tax_percent: string;
  invoice_prefix: string;
  token_prefix: string;
};

export type Role = {
  id: string;
  slug: string;
  name: string;
  description: string;
};

export type StaffMember = {
  id: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  status: string;
  role: Role | null;
  email_verified: boolean;
  last_login_at: string | null;
  is_you: boolean;
};

export type Invitation = {
  id: string;
  email: string;
  role: Role;
  invited_by_name: string;
  expires_at: string;
  created_at: string;
};

export type InvitationPreview = {
  clinic_name: string;
  role_name: string;
  email: string;
  first_name: string;
};

export const getClinic = () => request<Clinic>("/clinic");

export const saveClinic = (changes: Partial<Clinic> & { address?: Partial<Address> }) =>
  request<Clinic>("/clinic", { method: "PATCH", body: JSON.stringify(changes) });

export const getSettings = () => request<ClinicSettings>("/clinic/settings");

export const saveSettings = (changes: Partial<ClinicSettings>) =>
  request<ClinicSettings>("/clinic/settings", {
    method: "PATCH",
    body: JSON.stringify(changes),
  });

export const completeSetup = () => post<Clinic>("/clinic/complete-setup", {});

export const getRoles = () => request<Role[]>("/clinic/roles");

export const getStaff = () => request<StaffMember[]>("/staff");

export const getInvitations = () => request<Invitation[]>("/staff/invitations");

export const sendInvitation = (payload: {
  email: string;
  first_name: string;
  last_name: string;
  role_slug: string;
}) => post<{ acknowledged: boolean; email_configured: boolean }>("/staff/invitations", payload);

export const revokeInvitation = (id: string) =>
  request<{ acknowledged: boolean }>(`/staff/invitations/${id}`, { method: "DELETE" });

export const changeRole = (memberId: string, roleSlug: string) =>
  request<{ acknowledged: boolean }>(`/staff/${memberId}/role`, {
    method: "PATCH",
    body: JSON.stringify({ role_slug: roleSlug }),
  });

export const suspendMember = (memberId: string) =>
  post<{ acknowledged: boolean }>(`/staff/${memberId}/suspend`, {});

export const restoreMember = (memberId: string) =>
  post<{ acknowledged: boolean }>(`/staff/${memberId}/restore`, {});

export const previewInvitation = (token: string) =>
  request<InvitationPreview>(`/invitations/${encodeURIComponent(token)}`);

export const acceptInvitation = (token: string, password: string) =>
  post<{ acknowledged: boolean }>("/invitations/accept", { token, password });

/** A clinic's own currency, written the way its staff would expect to read it. */
export function money(amount: string, currency: string, locale = "en-IN"): string {
  const value = Number(amount);
  if (!Number.isFinite(value)) return amount;
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(value);
}
