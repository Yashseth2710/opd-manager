import { request } from "@/lib/api";
import type { DoctorRef } from "@/lib/appointments";
import type { MethodTotal } from "@/lib/billing";

export type Range = "today" | "week" | "month" | "this_month" | "last_month" | "custom";

export type Span = {
  range: Range;
  first_day: string;
  last_day: string;
  days: number;
  label: string;
};

export type DayLine = {
  date: string;
  seen: number;
  walk_ins: number;
  no_shows: number;
  registered: number;
  collected: string;
};

export type DoctorLine = {
  doctor: DoctorRef;
  seen: number;
  no_shows: number;
  average_minutes: number | null;
  billed: string;
  collected: string;
};

export type HourLine = { hour: number; seen: number };
export type TestLine = { name: string; times: number };
export type ChargeLine = { description: string; times: number; amount: string };

export type Report = {
  span: Span;
  view: "clinic" | "doctor" | "unlinked";
  doctor: DoctorRef | null;
  currency: string;
  seen: number;
  walk_ins: number;
  no_shows: number;
  new_patients: number;
  per_patient: string;
  before: { seen: number; collected: string };
  methods: MethodTotal[];
  received: string;
  refunded: string;
  net: string;
  online: string;
  bills_issued: number;
  billed: string;
  outstanding: string;
  outstanding_bills: number;
  days: DayLine[];
  doctors: DoctorLine[];
  hours: HourLine[];
  tests: TestLine[];
  charges: ChargeLine[];
};

/** What the chips along the top offer, in the order they are shown. */
export const RANGES: { value: Range; label: string }[] = [
  { value: "today", label: "Today" },
  { value: "week", label: "Last 7 days" },
  { value: "month", label: "Last 30 days" },
  { value: "this_month", label: "This month" },
  { value: "last_month", label: "Last month" },
  { value: "custom", label: "Choose dates" },
];

export function asked(range: Range, from: string, to: string): string {
  const params = new URLSearchParams({ range });
  if (range === "custom") {
    params.set("from", from);
    params.set("to", to);
  }
  return params.toString();
}

export const getReport = (range: Range, from: string, to: string) =>
  request<Report>(`/reports/summary?${asked(range, from, to)}`);

/** Opened in a new tab, which the browser saves rather than renders. */
export const dayBookHref = (range: Range, from: string, to: string) =>
  `/api/v1/reports/day-book.csv?${asked(range, from, to)}`;

/** How a figure moved against the stretch of the same length before it. */
export function movement(now: number, before: number): { words: string; up: boolean } | null {
  if (before === 0) return null;
  const share = Math.round(((now - before) / before) * 100);
  if (share === 0) return null;
  return { words: `${share > 0 ? "+" : ""}${share}%`, up: share > 0 };
}
