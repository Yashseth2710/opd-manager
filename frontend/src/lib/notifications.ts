import { request } from "@/lib/api";

export type NoticeKind =
  | "appointment_booked"
  | "appointment_moved"
  | "appointment_cancelled"
  | "lab_result"
  | "paid_online"
  | "bill_voided"
  | "staff_joined"
  | "role_changed"
  | "account_locked";

export type Notice = {
  id: string;
  kind: NoticeKind;
  title: string;
  body: string | null;
  link: string | null;
  channel: "in_app" | "email";
  read_at: string | null;
  sent_at: string | null;
  created_at: string;
};

export type NoticeList = { items: Notice[]; unread: number; more: boolean };

export type Preference = {
  kind: NoticeKind;
  label: string;
  description: string;
  email: boolean;
};
export type Preferences = { email_available: boolean; kinds: Preference[] };

export const listNotices = (show: "all" | "unread", before?: string) => {
  const params = new URLSearchParams({ show });
  if (before) params.set("before", before);
  return request<NoticeList>(`/notifications?${params}`);
};

export const countUnread = () => request<{ unread: number }>("/notifications/unread");

export const markRead = (id: string) =>
  request<Notice>(`/notifications/${id}/read`, { method: "POST" });

export const markAllRead = () =>
  request<{ unread: number }>("/notifications/read-all", { method: "POST" });

export const getPreferences = () => request<Preferences>("/notifications/preferences");

export const choosePreference = (kind: NoticeKind, email: boolean) =>
  request<Preferences>("/notifications/preferences", {
    method: "PUT",
    body: JSON.stringify({ kind, email }),
  });

/** Which part of the clinic a notice comes from, for its colour. */
export type Tone = "diary" | "clinical" | "money" | "people";

export const TONE: Record<NoticeKind, Tone> = {
  appointment_booked: "diary",
  appointment_moved: "diary",
  appointment_cancelled: "diary",
  lab_result: "clinical",
  paid_online: "money",
  bill_voided: "money",
  staff_joined: "people",
  role_changed: "people",
  account_locked: "people",
};

/** "just now", "4 min ago", "2 h ago", then the date. */
export function sinceThen(value: string, now: Date = new Date()): string {
  const then = new Date(value);
  const minutes = Math.floor((now.getTime() - then.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24 && then.getDate() === now.getDate()) return `${hours} h ago`;
  return then.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** Today, Yesterday, or the date, for grouping a list by day. */
export function dayHeading(value: string, now: Date = new Date()): string {
  const day = new Date(value);
  const start = (moment: Date) =>
    new Date(moment.getFullYear(), moment.getMonth(), moment.getDate()).getTime();
  const apart = Math.round((start(now) - start(day)) / 86_400_000);
  if (apart === 0) return "Today";
  if (apart === 1) return "Yesterday";
  return day.toLocaleDateString("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "long",
    ...(day.getFullYear() === now.getFullYear() ? {} : { year: "numeric" }),
  });
}

export function byDay<T extends { created_at: string }>(items: T[]): [string, T[]][] {
  const groups = new Map<string, T[]>();
  for (const item of items) {
    const heading = dayHeading(item.created_at);
    groups.set(heading, [...(groups.get(heading) ?? []), item]);
  }
  return [...groups.entries()];
}
