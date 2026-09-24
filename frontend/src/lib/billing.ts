import { post, request } from "@/lib/api";
import type { DoctorRef, PatientRef } from "@/lib/appointments";

export type InvoiceStatus = "draft" | "unpaid" | "partly_paid" | "paid" | "refunded" | "void";
export type ItemType = "consultation" | "procedure" | "lab" | "medicine" | "other";
export type Method = "cash" | "upi" | "card" | "bank_transfer" | "cheque" | "other";
export type BillShow = "to_collect" | "drafts" | "paid" | "void" | "all";
/** Whether the money was handed over at the desk or paid from a link. */
export type Channel = "desk" | "online";
export type LinkStatus = "open" | "paid" | "cancelled" | "expired";

export const MAX_LINES = 50;

export type Line = {
  item_type: ItemType;
  description: string;
  quantity: number;
  unit_price: string;
};

export type Totals = {
  subtotal: string;
  discount_amount: string;
  tax_percent: string;
  tax_amount: string;
  total: string;
  amount_paid: string;
  refunded_amount: string;
  balance: string;
};

export type InvoiceListed = Totals & {
  id: string;
  invoice_number: string | null;
  status: InvoiceStatus;
  patient: PatientRef;
  doctor: DoctorRef | null;
  headline: string;
  lines: number;
  created_at: string;
  issued_at: string | null;
};

export type Payment = {
  id: string;
  kind: "payment" | "refund";
  amount: string;
  method: Method;
  channel: Channel;
  reference: string | null;
  note: string | null;
  received_at: string;
  received_by: string | null;
};

export type PaymentLink = {
  id: string;
  status: LinkStatus;
  amount: string;
  /** Paid through the link with nothing left on the bill to put it against. */
  excess_amount: string;
  currency: string;
  expires_at: string;
  sent_to: string | null;
  sent_at: string | null;
  opened_at: string | null;
  paid_at: string | null;
  created_at: string;
  created_by: string | null;
};

/** Only the answer that raises a link carries its address; it is not kept. */
export type LinkMade = PaymentLink & { url: string; sent: boolean };

export type Visit = {
  queue_entry_id: string;
  date: string;
  token: number;
  consultation_id: string | null;
};

export type Invoice = InvoiceListed & {
  currency: string;
  items: (Line & { amount: string })[];
  payments: Payment[];
  discount_reason: string | null;
  notes: string | null;
  visit: Visit | null;
  created_by: string | null;
  issued_by: string | null;
  voided_at: string | null;
  voided_by: string | null;
  void_reason: string | null;
  can_edit: boolean;
  can_pay: boolean;
  can_refund: boolean;
  can_void: boolean;
  void_blocked: string | null;
  payment_link: PaymentLink | null;
  can_send_link: boolean;
  online_payments: boolean;
};

export type InvoicePage = {
  items: InvoiceListed[];
  total: number;
  counts: Record<InvoiceStatus, number>;
  /** Still owed on issued bills, for the patient asked about or the clinic. */
  owed: string;
};

export type MethodTotal = {
  method: Method;
  received: string;
  refunded: string;
  net: string;
  count: number;
};

export type DaySummary = {
  date: string;
  currency: string;
  methods: MethodTotal[];
  received: string;
  refunded: string;
  net: string;
  /** Of what came in, the part paid from a link rather than at the desk. */
  online: string;
  bills_issued: number;
  billed: string;
  outstanding: string;
  outstanding_bills: number;
};

export type Unbilled = {
  queue_entry_id: string;
  token: number;
  status: string;
  patient: PatientRef;
  doctor: DoctorRef;
  completed_at: string | null;
};

export type Starting = {
  patient: PatientRef;
  doctor: DoctorRef | null;
  visit: Visit | null;
  currency: string;
  tax_percent: string;
  items: Line[];
  lab_tests: string[];
  existing: string | null;
  existing_number: string | null;
};

export type PastLine = {
  item_type: ItemType;
  description: string;
  unit_price: string;
  times: number;
};

export type Draft = {
  items: Line[];
  discount_amount: string;
  discount_reason: string | null;
  notes: string | null;
};

/** A key for one attempt at something that takes money, sent again on a retry. */
export function freshKey(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

const keyed = (key: string) => ({ "Idempotency-Key": key });

export const listBills = (
  filters: {
    show?: BillShow;
    patient?: string;
    q?: string;
    from?: string;
    to?: string;
    limit?: number;
    offset?: number;
  } = {},
) => {
  const params = new URLSearchParams();
  if (filters.show) params.set("show", filters.show);
  if (filters.patient) params.set("patient_id", filters.patient);
  if (filters.q?.trim()) params.set("q", filters.q.trim());
  if (filters.from) params.set("from", filters.from);
  if (filters.to) params.set("to", filters.to);
  if (filters.limit) params.set("limit", String(filters.limit));
  if (filters.offset) params.set("offset", String(filters.offset));
  const query = params.toString();
  return request<InvoicePage>(`/invoices${query ? `?${query}` : ""}`);
};

export const getSummary = (date?: string) =>
  request<DaySummary>(`/invoices/summary${date ? `?date=${date}` : ""}`);

export const getUnbilled = (date?: string) =>
  request<{ date: string; items: Unbilled[] }>(
    `/invoices/unbilled${date ? `?date=${date}` : ""}`,
  );

export const getStarting = (known: { visit?: string | null; patient?: string | null }) => {
  const params = new URLSearchParams();
  if (known.visit) params.set("queue_entry_id", known.visit);
  else if (known.patient) params.set("patient_id", known.patient);
  return request<Starting>(`/invoices/start?${params}`);
};

export const getPastLines = (typed: string) =>
  request<PastLine[]>(
    `/invoices/lines${typed.trim() ? `?q=${encodeURIComponent(typed.trim())}` : ""}`,
  );

export const getBill = (id: string) => request<Invoice>(`/invoices/${id}`);

export const raiseBill = (
  body: Draft & { patient_id: string; queue_entry_id: string | null; issue: boolean },
  key: string,
) =>
  request<Invoice>("/invoices", {
    method: "POST",
    body: JSON.stringify(body),
    headers: keyed(key),
  });

export const changeBill = (id: string, draft: Partial<Draft>) =>
  request<Invoice>(`/invoices/${id}`, { method: "PATCH", body: JSON.stringify(draft) });

export const discardBill = (id: string) =>
  request<{ removed: boolean }>(`/invoices/${id}`, { method: "DELETE" });

export const issueBill = (id: string) => post<Invoice>(`/invoices/${id}/issue`, {});

export const voidBill = (id: string, reason: string) =>
  post<Invoice>(`/invoices/${id}/void`, { reason });

export const takePayment = (
  id: string,
  body: { amount: string; method: Method; reference: string | null; note: string | null },
  key: string,
) =>
  request<Invoice>(`/invoices/${id}/payments`, {
    method: "POST",
    body: JSON.stringify(body),
    headers: keyed(key),
  });

export const giveBack = (
  id: string,
  body: { amount: string; method: Method; reason: string; reference: string | null },
  key: string,
) =>
  request<Invoice>(`/invoices/${id}/refunds`, {
    method: "POST",
    body: JSON.stringify(body),
    headers: keyed(key),
  });

export const sendPaymentLink = (id: string, body: { send: boolean; email: string | null }) =>
  post<LinkMade>(`/invoices/${id}/payment-link`, body);

export const cancelPaymentLink = (id: string) =>
  request<Invoice>(`/invoices/${id}/payment-link`, { method: "DELETE" });

/** Opened in a new tab, where the browser's own viewer prints it. */
export const billPdfHref = (id: string) => `/api/v1/invoices/${id}/pdf`;

export const STATUS_WORDS: Record<InvoiceStatus, string> = {
  draft: "Draft",
  unpaid: "Unpaid",
  partly_paid: "Part paid",
  paid: "Paid",
  refunded: "Refunded",
  void: "Void",
};

export const STATUS_TONE: Record<InvoiceStatus, string> = {
  draft: "var(--color-state-scheduled)",
  unpaid: "var(--color-state-waiting)",
  partly_paid: "var(--color-state-confirmed)",
  paid: "var(--color-state-completed)",
  refunded: "var(--color-state-cancelled)",
  void: "var(--color-state-cancelled)",
};

/** For the badge beside the heading, where there is room for one word. */
export const LINK_WORDS: Record<LinkStatus, string> = {
  open: "Waiting",
  paid: "Paid",
  // Either the desk called it off, or the bill stopped owing anything and
  // the link closed itself. "Closed" covers both without claiming which.
  cancelled: "Closed",
  expired: "Expired",
};

/** For a sentence, where "was expired" would read like nobody wrote it. */
export const LINK_SAID: Record<LinkStatus, string> = {
  open: "is waiting to be paid",
  paid: "was paid",
  cancelled: "was closed",
  expired: "expired",
};

export const METHOD_WORDS: Record<Method, string> = {
  cash: "Cash",
  upi: "UPI",
  card: "Card",
  bank_transfer: "Bank transfer",
  cheque: "Cheque",
  other: "Other",
};

export const TYPE_WORDS: Record<ItemType, string> = {
  consultation: "Consultation",
  procedure: "Procedure",
  lab: "Test",
  medicine: "Medicine",
  other: "Other",
};

/** What the reference box asks for, by how the money came. */
export const REFERENCE_WORDS: Record<Method, string | null> = {
  cash: null,
  upi: "UPI reference",
  card: "Last four digits or slip number",
  bank_transfer: "Transaction reference",
  cheque: "Cheque number",
  other: "Reference",
};

// --- Sums, in whole paise ----------------------------------------------------------
//
// The server works every bill out and its figures are the ones kept. These
// are for the running total shown while a bill is being typed, done in whole
// paise so the screen agrees with what comes back to the last digit.

const AMOUNT = /^\d{1,8}(\.\d{0,2})?$/;

/** "120.5" as 12050 paise, or null for anything that is not an amount. */
export function toPaise(typed: string): number | null {
  const clean = typed.replaceAll(",", "").replace(/^₹/, "").trim();
  if (!clean || !AMOUNT.test(clean)) return null;
  const [whole, fraction = ""] = clean.split(".");
  return Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
}

export function fromPaise(paise: number): string {
  const sign = paise < 0 ? "-" : "";
  const size = Math.abs(paise);
  return `${sign}${Math.floor(size / 100)}.${String(size % 100).padStart(2, "0")}`;
}

export type Worked = {
  lines: (number | null)[];
  subtotal: number;
  discount: number;
  tax: number;
  total: number;
};

/** The bill as the server will work it out, half up on the tax. */
export function workOut(lines: Line[], discount: string, taxPercent: string): Worked {
  const amounts = lines.map((line) => {
    const price = toPaise(line.unit_price);
    return price === null || !Number.isInteger(line.quantity) ? null : price * line.quantity;
  });
  const subtotal = amounts.reduce<number>((sum, each) => sum + (each ?? 0), 0);
  const off = Math.min(toPaise(discount) ?? 0, subtotal);
  const rate = Math.round(Number(taxPercent) * 100) || 0;
  const tax = Math.floor(((subtotal - off) * rate + 5000) / 10000);
  return { lines: amounts, subtotal, discount: off, tax, total: subtotal - off + tax };
}

/** "2026-27": bill numbers start again each April, with the financial year. */
export function financialYear(day: Date = new Date()): string {
  const start = day.getMonth() >= 3 ? day.getFullYear() : day.getFullYear() - 1;
  return `${start}-${String((start + 1) % 100).padStart(2, "0")}`;
}
