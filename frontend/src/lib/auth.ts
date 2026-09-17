import { post, request, type ClinicChoice } from "@/lib/api";

export type Organization = {
  id: string;
  name: string;
  slug: string;
  timezone: string;
  currency: string;
  status: "pending" | "active" | "suspended";
  onboarding_completed_at: string | null;
};

export type User = {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  phone: string | null;
  status: string;
  email_verified_at: string | null;
};

export type Session = {
  user: User;
  organization: Organization | null;
  role: string;
  permissions: string[];
};

export type RegisterResult = {
  session: Session | null;
  verification_required: boolean;
  email_delivered: boolean;
};

export type Acknowledged = {
  acknowledged: boolean;
  email_configured: boolean;
};

export const currentSession = () => request<Session>("/auth/me");

export const signIn = (payload: {
  email: string;
  password: string;
  organization_slug?: string;
}) => post<Session>("/auth/login", payload);

export const signOut = () => post<Acknowledged>("/auth/logout", {});

export const registerClinic = (payload: {
  clinic_name: string;
  first_name: string;
  last_name: string;
  email: string;
  password: string;
  phone?: string;
}) => post<RegisterResult>("/auth/register", payload);

export const requestReset = (email: string) =>
  post<Acknowledged>("/auth/forgot-password", { email });

export const completeReset = (token: string, password: string) =>
  post<Acknowledged>("/auth/reset-password", { token, password });

export const confirmEmail = (token: string) =>
  post<Acknowledged>("/auth/verify-email", { token });

export const resendConfirmation = (email: string) =>
  post<Acknowledged>("/auth/resend-verification", { email });

export type { ClinicChoice };

/** Mirrors the slug the API builds, so the person sees it before they commit. */
export function previewSlug(name: string): string {
  return (
    name
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "clinic"
  );
}

/** Phrases a wait in whole minutes once it passes a minute. */
export function describeWait(seconds: number | undefined): string {
  if (!seconds || seconds < 60) return "a moment";
  const minutes = Math.ceil(seconds / 60);
  return minutes === 1 ? "a minute" : `${minutes} minutes`;
}
