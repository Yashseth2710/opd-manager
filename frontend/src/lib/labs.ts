import { post, request } from "@/lib/api";
import type { DoctorRef, PatientRef } from "@/lib/appointments";

export type LabStatus = "ordered" | "resulted" | "reviewed" | "cancelled";
export type Judgement = "high" | "low" | "abnormal";

/** The tabs of the work list, and what the server calls each. */
export type LabShow = "waiting" | "to_review" | "reviewed" | "cancelled";

export const MAX_VALUES = 40;

export type LabTest = {
  code: string | null;
  name: string;
  also: string[];
  category: string | null;
  prepare: string | null;
  parts: number;
  times_ordered: number;
};

export type LabCatalogue = { categories: Record<string, string>; tests: LabTest[] };

export type ResultValue = {
  name: string;
  value: string;
  unit: string | null;
  low: number | null;
  high: number | null;
  expected: string | null;
};

export type ReportedValue = ResultValue & {
  flag: Judgement | null;
  earlier: { value: string; flag: Judgement | null; reported_on: string } | null;
};

export type LabOrderBrief = {
  id: string;
  order_number: string;
  test_code: string | null;
  test_name: string;
  category: string | null;
  urgent: boolean;
  instructions: string | null;
  status: LabStatus;
  ordered_at: string;
  reported_on: string | null;
  flagged: number;
  consultation_id: string;
};

export type LabOrderListed = LabOrderBrief & { patient: PatientRef; doctor: DoctorRef };

export type LabOrder = LabOrderListed & {
  ordered_by: string | null;
  cancelled_at: string | null;
  cancelled_by: string | null;
  cancel_reason: string | null;
  lab_name: string | null;
  findings: string | null;
  values: ReportedValue[];
  resulted_at: string | null;
  resulted_by: string | null;
  changed_by: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  template: Omit<ResultValue, "value">[];
  ranges_left_out: boolean;
  visit_date: string;
  visit_open: boolean;
  can_enter: boolean;
  can_review: boolean;
  can_cancel: boolean;
  can_remove: boolean;
};

export type LabOrderPage = {
  items: LabOrderListed[];
  total: number;
  counts: Record<LabStatus, number>;
};

export type LabResult = {
  reported_on: string;
  lab_name: string | null;
  findings: string | null;
  values: ResultValue[];
};

export const getLabTests = () => request<LabCatalogue>("/lab-tests");

export const listLabOrders = (
  filters: {
    patient?: string;
    visit?: string;
    doctor?: string;
    /** A doctor's own orders only. */
    mine?: boolean;
    show?: LabShow;
    q?: string;
    limit?: number;
    offset?: number;
  } = {},
) => {
  const params = new URLSearchParams();
  if (filters.patient) params.set("patient_id", filters.patient);
  if (filters.visit) params.set("consultation_id", filters.visit);
  if (filters.doctor) params.set("doctor_id", filters.doctor);
  if (filters.mine) params.set("mine", "true");
  if (filters.show) params.set("show", filters.show);
  if (filters.q?.trim()) params.set("q", filters.q.trim());
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  const query = params.toString();
  return request<LabOrderPage>(`/lab-orders${query ? `?${query}` : ""}`);
};

export const getLabOrder = (id: string) => request<LabOrder>(`/lab-orders/${id}`);

export const orderTest = (body: {
  consultation_id: string;
  test_code?: string;
  test_name?: string;
  urgent: boolean;
}) => post<LabOrder>("/lab-orders", body);

export const removeLabOrder = (id: string) =>
  request<{ removed: boolean }>(`/lab-orders/${id}`, { method: "DELETE" });

export const cancelLabOrder = (id: string, reason: string) =>
  post<LabOrder>(`/lab-orders/${id}/cancel`, { reason });

export const recordResult = (id: string, result: LabResult) =>
  request<LabOrder>(`/lab-orders/${id}/result`, {
    method: "PUT",
    body: JSON.stringify(result),
  });

export const clearResult = (id: string) =>
  request<LabOrder>(`/lab-orders/${id}/result`, { method: "DELETE" });

export const reviewResult = (id: string) => post<LabOrder>(`/lab-orders/${id}/review`, {});

export const STATUS_WORDS: Record<LabStatus, string> = {
  ordered: "Waiting for the report",
  resulted: "Report back",
  reviewed: "Seen by the doctor",
  cancelled: "Cancelled",
};

export const STATUS_TONE: Record<LabStatus, string> = {
  ordered: "var(--color-state-waiting)",
  resulted: "var(--color-state-consulting)",
  reviewed: "var(--color-state-completed)",
  cancelled: "var(--color-state-cancelled)",
};

/** "12–15", "up to 200", "40 and above", or nothing to show. */
export function rangeWords(value: Pick<ResultValue, "low" | "high" | "expected">): string {
  const { low, high } = value;
  if (low !== null && high !== null) return `${low}–${high}`;
  if (high !== null) return `up to ${high}`;
  if (low !== null) return `${low} and above`;
  return value.expected ?? "";
}

export const FLAG_WORDS: Record<Judgement, string> = {
  high: "High",
  low: "Low",
  abnormal: "Not normal",
};

/** Whether a test typed into the box is one on the list, by name or a name it goes by. */
export function findTest(tests: LabTest[], typed: string): LabTest | undefined {
  const wanted = typed.trim().replace(/\s+/g, " ").toLowerCase();
  if (!wanted) return undefined;
  return tests.find(
    (test) =>
      test.name.toLowerCase() === wanted ||
      test.also.some((other) => other.toLowerCase() === wanted),
  );
}

/**
 * The tests that match what is typed: names that start with it first, then
 * names that contain it, then the short names a test goes by. With nothing
 * typed, the ones this clinic orders most.
 */
export function matchTests(tests: LabTest[], typed: string, limit = 8): LabTest[] {
  const wanted = typed.trim().replace(/\s+/g, " ").toLowerCase();
  if (!wanted) {
    return tests
      .filter((test) => test.times_ordered > 0)
      .sort((a, b) => b.times_ordered - a.times_ordered)
      .slice(0, limit);
  }
  const score = (test: LabTest): number | null => {
    const name = test.name.toLowerCase();
    const others = test.also.map((other) => other.toLowerCase());
    if (name.startsWith(wanted)) return 0;
    if (others.some((other) => other.startsWith(wanted))) return 1;
    if (name.includes(wanted)) return 2;
    if (others.some((other) => other.includes(wanted))) return 3;
    return null;
  };
  return tests
    .map((test) => ({ test, rank: score(test) }))
    .filter((each): each is { test: LabTest; rank: number } => each.rank !== null)
    .sort((a, b) => a.rank - b.rank || b.test.times_ordered - a.test.times_ordered)
    .slice(0, limit)
    .map((each) => each.test);
}

// The same judgement the server makes, so a value typed in is marked as it
// is typed. The server's is the one that is kept.
const NUMBER = /^([<>]=?|≤|≥)?\s*(-?\d+(?:\.\d+)?)$/;
const SAME: Record<string, string[]> = {
  negative: ["negative", "nil", "absent", "not detected", "none", "neg", "-ve", "not seen"],
  "non-reactive": ["non-reactive", "non reactive", "nonreactive", "nr"],
};

function plain(word: string): string {
  const said = word.toLowerCase().replaceAll(".", "").trim().replace(/\s+/g, " ");
  for (const [meaning, ways] of Object.entries(SAME)) {
    if (ways.includes(said)) return meaning;
  }
  return said;
}

export function judge(value: Pick<ResultValue, "value" | "low" | "high" | "expected">) {
  const typed = value.value.replaceAll(",", "").trim();
  const match = NUMBER.exec(typed);
  const { low, high } = value;
  if (match) {
    const bound = match[1];
    const figure = Number(match[2]);
    if (bound === "<" || bound === "<=" || bound === "≤")
      return low !== null && figure <= low ? ("low" as const) : null;
    if (bound === ">" || bound === ">=" || bound === "≥")
      return high !== null && figure >= high ? ("high" as const) : null;
    if (high !== null && figure > high) return "high" as const;
    if (low !== null && figure < low) return "low" as const;
    return null;
  }
  if (value.expected && typed && plain(typed) !== plain(value.expected))
    return "abnormal" as const;
  return null;
}
