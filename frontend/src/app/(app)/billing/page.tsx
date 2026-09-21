"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Loader2, Plus, Search } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Amount, BillStatus } from "@/components/billing/parts";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { longDate, shortDate, whenItHappened } from "@/lib/appointments";
import { currentSession } from "@/lib/auth";
import {
  getSummary,
  getUnbilled,
  listBills,
  METHOD_WORDS,
  type BillShow,
  type DaySummary,
  type InvoiceListed,
  type InvoiceStatus,
  type Unbilled,
} from "@/lib/billing";
import { localDay } from "@/lib/prescriptions";

const PAGE = 25;

export default function BillingPage() {
  return (
    <Permitted permission="billing:read">
      <Suspense fallback={<Looking />}>
        <Billing />
      </Suspense>
    </Permitted>
  );
}

function Looking({ words = "Finding the bills…" }: { words?: string }) {
  return (
    <div className="flex min-h-[20vh] items-center justify-center gap-3 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">{words}</span>
    </div>
  );
}

const TABS: { value: BillShow; label: string; counts: InvoiceStatus[] }[] = [
  { value: "to_collect", label: "To collect", counts: ["unpaid", "partly_paid"] },
  { value: "drafts", label: "Drafts", counts: ["draft"] },
  { value: "paid", label: "Paid", counts: [] },
  { value: "void", label: "Void", counts: [] },
  { value: "all", label: "All", counts: [] },
];

function shift(day: string, by: number): string {
  const moved = new Date(`${day}T00:00:00`);
  moved.setDate(moved.getDate() + by);
  return localDay(new Date(moved.getTime() - moved.getTimezoneOffset() * 60_000).toISOString());
}

function Billing() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const mayRaise = session.data?.permissions.includes("billing:create") ?? false;
  const currency = session.data?.organization?.currency ?? "INR";

  const asked = params.get("show");
  const show: BillShow = TABS.some((tab) => tab.value === asked)
    ? (asked as BillShow)
    : "to_collect";
  const searched = params.get("q") ?? "";
  const today = localDay(new Date().toISOString());
  const day = params.get("day") ?? today;
  const past = day !== today;
  const [typed, setTyped] = useState(searched);

  const choose = (key: "show" | "q" | "day", value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    const query = next.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}` as Route, { scroll: false });
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      if (typed.trim() !== searched) choose("q", typed.trim());
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typed]);

  const bills = useInfiniteQuery({
    queryKey: ["bills", "list", { show, q: searched, day: past ? day : null }],
    queryFn: ({ pageParam }) =>
      listBills({
        show,
        q: searched,
        // Looking back at a day, the bills are that day's.
        from: past ? day : undefined,
        to: past ? day : undefined,
        limit: PAGE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const shown = pages.reduce((sum, page) => sum + page.items.length, 0);
      return shown < last.total ? shown : undefined;
    },
    retry: false,
    refetchInterval: 60_000,
  });

  const items = bills.data?.pages.flatMap((page) => page.items) ?? [];
  const total = bills.data?.pages[0]?.total ?? 0;
  const counts = bills.data?.pages[0]?.counts;

  return (
    <Page
      title="Billing"
      blurb="What came in, what is still owed, and who was seen without a bill."
      action={
        mayRaise && (
          <Link
            href={"/billing/new" as Route}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--accent-fg)] transition hover:brightness-105"
          >
            <Plus className="size-4" />
            New bill
          </Link>
        )
      }
    >
      <Takings
        day={day}
        today={today}
        currency={currency}
        onDay={(next) => choose("day", next === today ? "" : next)}
        onOwed={() => choose("show", "")}
      />

      {day === today && <NotBilled mayRaise={mayRaise} />}

      <section aria-labelledby="bills-heading" className="mt-10">
        <h2 id="bills-heading" className={past ? "mb-3 text-[16px] font-semibold" : "sr-only"}>
          {past ? `Bills from ${longDate(day)}` : "Bills"}
        </h2>
        <div className="mb-5 flex flex-col gap-3">
          <div role="tablist" aria-label="Which bills" className="flex flex-wrap gap-1.5">
            {TABS.map((tab) => {
              const active = show === tab.value;
              const count = tab.counts.reduce(
                (sum, status) => sum + (counts?.[status] ?? 0),
                0,
              );
              return (
                <button
                  key={tab.value}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => choose("show", tab.value === "to_collect" ? "" : tab.value)}
                  className={`rounded-full border px-3.5 py-1.5 text-[14px] transition-colors ${
                    active
                      ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-fg)]"
                      : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
                  }`}
                >
                  {tab.label}
                  {count > 0 && <span className="ml-1.5 tabular opacity-80">{count}</span>}
                </button>
              );
            })}
          </div>
          <label className="relative block max-w-md">
            <span className="sr-only">Search by patient, phone or bill number</span>
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[var(--text-subtle)]"
            />
            <input
              type="search"
              value={typed}
              maxLength={100}
              onChange={(event) => setTyped(event.target.value)}
              placeholder="Patient, phone or bill number"
              className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] py-2 pr-3 pl-9 text-[15px] outline-none placeholder:text-[var(--text-subtle)] focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)]"
            />
          </label>
        </div>

        {bills.isPending ? (
          <Looking />
        ) : bills.isError ? (
          <p className="text-[15px] text-[var(--text-muted)]">
            The bills did not load. Try again in a moment.
          </p>
        ) : items.length === 0 ? (
          <Empty
            show={show}
            searched={searched}
            none={Object.values(counts ?? {}).every((count) => count === 0)}
          />
        ) : (
          <>
            <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
              {items.map((item) => (
                <Row key={item.id} item={item} currency={currency} />
              ))}
            </ul>
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-[13px] text-[var(--text-muted)]">
              <span className="tabular">
                {items.length === total ? `${total} in all` : `${items.length} of ${total}`}
              </span>
              {bills.hasNextPage && (
                <button
                  type="button"
                  onClick={() => void bills.fetchNextPage()}
                  disabled={bills.isFetchingNextPage}
                  className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] text-[var(--text)] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-60"
                >
                  {bills.isFetchingNextPage && <Loader2 className="size-4 animate-spin" />}
                  Show more
                </button>
              )}
            </div>
          </>
        )}
      </section>
    </Page>
  );
}

/**
 * The day's money, the way the drawer is counted at closing: what came in
 * by each way of paying, less anything given back.
 */
function Takings({
  day,
  today,
  currency,
  onDay,
  onOwed,
}: {
  day: string;
  today: string;
  currency: string;
  onDay: (day: string) => void;
  onOwed: () => void;
}) {
  const summary = useQuery({
    queryKey: ["bill-summary", day],
    queryFn: () => getSummary(day),
    retry: false,
    refetchInterval: day === today ? 30_000 : false,
  });

  return (
    <section
      aria-labelledby="takings-heading"
      className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] px-5 py-3">
        <h2 id="takings-heading" className="text-[15px] font-semibold">
          {day === today ? "Taken today" : `Taken on ${longDate(day)}`}
        </h2>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onDay(shift(day, -1))}
            aria-label="The day before"
            className="grid size-8 place-items-center rounded-[var(--radius-field)] text-[var(--text-muted)] hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
          >
            <ChevronLeft className="size-4" />
          </button>
          <input
            type="date"
            value={day}
            max={today}
            aria-label="Day"
            onChange={(event) => event.target.value && onDay(event.target.value)}
            className="rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-1 text-[13px] tabular"
          />
          <button
            type="button"
            onClick={() => onDay(shift(day, 1))}
            disabled={day >= today}
            aria-label="The day after"
            className="grid size-8 place-items-center rounded-[var(--radius-field)] text-[var(--text-muted)] hover:bg-[var(--surface-sunken)] hover:text-[var(--text)] disabled:invisible"
          >
            <ChevronRight className="size-4" />
          </button>
        </div>
      </div>

      {summary.isPending ? (
        <Looking words="Counting…" />
      ) : summary.isError ? (
        <p className="px-5 py-6 text-[15px] text-[var(--text-muted)]">
          The day&apos;s takings did not load. Try again in a moment.
        </p>
      ) : (
        <Counted summary={summary.data} currency={currency} onOwed={onOwed} />
      )}
    </section>
  );
}

function Counted({
  summary,
  currency,
  onOwed,
}: {
  summary: DaySummary;
  currency: string;
  onOwed: () => void;
}) {
  const money = summary.currency || currency;
  return (
    <div className="grid gap-6 px-5 py-5 md:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="flex flex-col gap-1">
        <p className="text-[13px] text-[var(--text-muted)]">In the drawer and the bank</p>
        <Amount
          value={summary.net}
          currency={money}
          className="text-[34px] leading-tight font-semibold tracking-tight"
        />
        <p className="text-[14px] text-[var(--text-muted)]">
          {summary.bills_issued === 0
            ? "No bills issued."
            : `${summary.bills_issued} ${summary.bills_issued === 1 ? "bill" : "bills"} issued, coming to `}
          {summary.bills_issued > 0 && <Amount value={summary.billed} currency={money} />}
          {summary.bills_issued > 0 && "."}
        </p>
        {summary.outstanding_bills > 0 && (
          <button
            type="button"
            onClick={onOwed}
            className="mt-2 self-start rounded-[var(--radius-field)] bg-[var(--accent-wash)] px-2.5 py-1 text-left text-[14px] transition hover:brightness-95"
          >
            <Amount value={summary.outstanding} currency={money} className="font-semibold" />{" "}
            still owed on {summary.outstanding_bills}{" "}
            {summary.outstanding_bills === 1 ? "bill" : "bills"}
          </button>
        )}
      </div>

      {summary.methods.length === 0 ? (
        <p className="self-center text-[14px] text-[var(--text-muted)]">
          Nothing taken yet. Payments appear here by how they were paid, for counting the
          drawer.
        </p>
      ) : (
        <table className="self-start text-[14px]">
          <caption className="sr-only">By how it was paid</caption>
          <thead className="sr-only">
            <tr>
              <th scope="col">How</th>
              <th scope="col">Payments</th>
              <th scope="col">Amount</th>
            </tr>
          </thead>
          <tbody>
            {summary.methods.map((each) => (
              <tr
                key={each.method}
                className="border-b border-dotted border-[var(--border-strong)]"
              >
                <th scope="row" className="py-1.5 pr-3 text-left font-medium">
                  {METHOD_WORDS[each.method]}
                  {each.refunded !== "0.00" && (
                    <span className="block text-[12px] font-normal text-[var(--text-muted)]">
                      after <Amount value={each.refunded} currency={money} /> given back
                    </span>
                  )}
                </th>
                <td className="py-1.5 pr-3 text-right text-[13px] text-[var(--text-muted)] tabular">
                  {each.count} {each.count === 1 ? "payment" : "payments"}
                </td>
                <td className="py-1.5 text-right">
                  <Amount value={each.net} currency={money} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** Patients the doctors have seen today who have no bill yet. */
function NotBilled({ mayRaise }: { mayRaise: boolean }) {
  const unbilled = useQuery({
    queryKey: ["bills", "unbilled"],
    queryFn: () => getUnbilled(),
    retry: false,
    refetchInterval: 30_000,
  });
  const items = unbilled.data?.items ?? [];
  if (items.length === 0) return null;

  return (
    <section aria-labelledby="unbilled-heading" className="mt-8">
      <h2
        id="unbilled-heading"
        className="mb-3 flex items-baseline gap-2 text-[16px] font-semibold"
      >
        Seen today, not billed yet
        <span className="text-[14px] font-normal text-[var(--text-muted)] tabular">
          {items.length}
        </span>
      </h2>
      <ul className="divide-y divide-[var(--border)] rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)]">
        {items.map((item) => (
          <UnbilledRow key={item.queue_entry_id} item={item} mayRaise={mayRaise} />
        ))}
      </ul>
    </section>
  );
}

function UnbilledRow({ item, mayRaise }: { item: Unbilled; mayRaise: boolean }) {
  return (
    <li className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-2.5">
      <span className="grid size-8 shrink-0 place-items-center rounded-[var(--radius-field)] bg-[var(--surface-sunken)] font-mono text-[14px] font-semibold tabular">
        {item.token}
      </span>
      <span className="min-w-0 flex-1">
        <Link
          href={`/patients/${item.patient.id}` as Route}
          className="block truncate text-[15px] font-medium underline-offset-2 hover:underline"
        >
          {item.patient.full_name}
        </Link>
        <span className="block truncate text-[13px] text-[var(--text-muted)]">
          {item.doctor.display_name}
          {item.completed_at && `, done ${whenItHappened(item.completed_at).split(", ").pop()}`}
        </span>
      </span>
      {mayRaise && (
        <Link
          href={`/billing/new?visit=${item.queue_entry_id}` as Route}
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-1.5 text-[14px] font-medium transition hover:bg-[var(--surface-sunken)]"
        >
          Bill
        </Link>
      )}
    </li>
  );
}

function Row({ item, currency }: { item: InvoiceListed; currency: string }) {
  const part = item.status === "partly_paid";
  return (
    <li>
      <Link
        href={`/billing/${item.id}` as Route}
        className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1 px-4 py-3 transition-colors hover:bg-[var(--surface-sunken)] focus-visible:bg-[var(--surface-sunken)]"
      >
        <span className="min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="truncate text-[15px] font-medium">{item.patient.full_name}</span>
            <span className="font-mono text-[12px] text-[var(--text-subtle)] tabular">
              {item.invoice_number ?? "Not numbered yet"}
            </span>
          </span>
          <span className="block truncate text-[14px] text-[var(--text-muted)]">
            {item.headline}
            {`, ${shortDate(localDay(item.issued_at ?? item.created_at))}`}
          </span>
        </span>
        <span className="flex flex-col items-end gap-1">
          <Amount
            value={item.total}
            currency={currency}
            className={`text-[15px] ${item.status === "void" ? "text-[var(--text-subtle)] line-through" : ""}`}
          />
          <span className="flex items-center gap-2">
            {part && (
              <span className="text-[12px] text-[var(--text-muted)]">
                <Amount value={item.balance} currency={currency} /> left
              </span>
            )}
            <BillStatus status={item.status} />
          </span>
        </span>
      </Link>
    </li>
  );
}

function Empty({
  show,
  searched,
  none,
}: {
  show: BillShow;
  searched: string;
  /** The clinic has no bills at all yet. */
  none: boolean;
}) {
  const words = searched
    ? `No bill matches “${searched}”.`
    : none
      ? "No bills yet. Bill a patient from the list of those seen today, or start one with New bill."
      : {
          to_collect: "Nothing is owed. Every bill issued has been paid.",
          drafts: "No drafts. A bill kept as a draft waits here until it is issued.",
          paid: "No bills have been paid yet.",
          void: "No bills have been voided.",
          all: "No bills yet. Bill a patient from the list of those seen today, or start one with New bill.",
        }[show];
  return (
    <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-10 text-center">
      <p className="text-[15px] text-[var(--text-muted)]">{words}</p>
    </div>
  );
}
