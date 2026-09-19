"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Loader2, Search } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { FlaggedCount, LabStatusChip, Urgent } from "@/components/labs/parts";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { shortDate } from "@/lib/appointments";
import { currentSession } from "@/lib/auth";
import { listLabOrders, type LabOrderListed, type LabShow, type LabStatus } from "@/lib/labs";
import { localDay } from "@/lib/prescriptions";

const PAGE = 25;

export default function LabPage() {
  return (
    <Permitted permission="lab:read">
      <Suspense fallback={<Looking />}>
        <LabList />
      </Suspense>
    </Permitted>
  );
}

function Looking() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center gap-3 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">Finding the tests…</span>
    </div>
  );
}

const TABS: { value: LabShow; label: string; counts: LabStatus }[] = [
  { value: "waiting", label: "Waiting for reports", counts: "ordered" },
  { value: "to_review", label: "Back, not seen", counts: "resulted" },
  { value: "reviewed", label: "Seen", counts: "reviewed" },
  { value: "cancelled", label: "Cancelled", counts: "cancelled" },
];

function LabList() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const isDoctor = session.data?.role === "doctor";

  const asked = params.get("show");
  const show: LabShow = TABS.some((tab) => tab.value === asked)
    ? (asked as LabShow)
    : "waiting";
  // A doctor starts on their own orders; anyone can widen it to the clinic's.
  const everyone = !isDoctor || params.get("whose") === "everyone";
  const searched = params.get("q") ?? "";
  const [typed, setTyped] = useState(searched);

  const choose = (key: "show" | "whose" | "q", value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    const query = next.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}` as Route, { scroll: false });
  };

  // Searches once the typing pauses.
  useEffect(() => {
    const timer = setTimeout(() => {
      if (typed.trim() !== searched) choose("q", typed.trim());
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typed]);

  const orders = useInfiniteQuery({
    queryKey: ["lab-orders", "list", { show, everyone, q: searched }],
    queryFn: ({ pageParam }) =>
      listLabOrders({
        show,
        mine: !everyone,
        q: searched,
        limit: PAGE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const shown = pages.reduce((sum, page) => sum + page.items.length, 0);
      return shown < last.total ? shown : undefined;
    },
    enabled: session.isSuccess,
    retry: false,
    refetchInterval: 60_000,
  });

  const items = orders.data?.pages.flatMap((page) => page.items) ?? [];
  const total = orders.data?.pages[0]?.total ?? 0;
  const counts = orders.data?.pages[0]?.counts;

  return (
    <Page
      title="Lab"
      blurb={
        isDoctor && !everyone
          ? "Tests you ordered: what is still out, and what has come back for you to look at."
          : "Tests the doctors have ordered: what is still out, and what has come back. Open one to type its report in."
      }
    >
      <div className="mb-5 flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div role="tablist" aria-label="Which tests" className="flex flex-wrap gap-1.5">
            {TABS.map((tab) => {
              const active = show === tab.value;
              const count = counts?.[tab.counts] ?? 0;
              return (
                <button
                  key={tab.value}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => choose("show", tab.value === "waiting" ? "" : tab.value)}
                  className={`rounded-full border px-3.5 py-1.5 text-[14px] transition-colors ${
                    active
                      ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-fg)]"
                      : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
                  }`}
                >
                  {tab.label}
                  {count > 0 && tab.value !== "cancelled" && (
                    <span className="ml-1.5 tabular opacity-80">{count}</span>
                  )}
                </button>
              );
            })}
          </div>
          {isDoctor && (
            <div role="group" aria-label="Whose tests" className="flex gap-1 text-[14px]">
              {(
                [
                  ["", "Mine"],
                  ["everyone", "Everyone's"],
                ] as const
              ).map(([value, label]) => {
                const active = (params.get("whose") ?? "") === value;
                return (
                  <button
                    key={label}
                    type="button"
                    aria-pressed={active}
                    onClick={() => choose("whose", value)}
                    className={`rounded-[var(--radius-field)] px-2.5 py-1 transition-colors ${
                      active
                        ? "bg-[var(--surface-sunken)] font-medium"
                        : "text-[var(--text-muted)] hover:text-[var(--text)]"
                    }`}
                  >
                    {label}
                  </button>
                );
              })}
            </div>
          )}
        </div>
        <label className="relative block max-w-md">
          <span className="sr-only">Search by patient, number or test</span>
          <Search
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[var(--text-subtle)]"
          />
          <input
            type="search"
            value={typed}
            maxLength={100}
            onChange={(event) => setTyped(event.target.value)}
            placeholder="Patient, phone, LAB number or test"
            className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] py-2 pr-3 pl-9 text-[15px] outline-none placeholder:text-[var(--text-subtle)] focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)]"
          />
        </label>
      </div>

      {orders.isPending ? (
        <Looking />
      ) : orders.isError ? (
        <p className="text-[15px] text-[var(--text-muted)]">
          The tests did not load. Try again in a moment.
        </p>
      ) : items.length === 0 ? (
        <Empty show={show} searched={searched} mine={!everyone} />
      ) : (
        <>
          <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
            {items.map((item) => (
              <Row key={item.id} item={item} />
            ))}
          </ul>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-[13px] text-[var(--text-muted)]">
            <span className="tabular">
              {items.length === total ? `${total} in all` : `${items.length} of ${total}`}
            </span>
            {orders.hasNextPage && (
              <button
                type="button"
                onClick={() => void orders.fetchNextPage()}
                disabled={orders.isFetchingNextPage}
                className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] text-[var(--text)] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-60"
              >
                {orders.isFetchingNextPage && <Loader2 className="size-4 animate-spin" />}
                Show more
              </button>
            )}
          </div>
        </>
      )}
    </Page>
  );
}

/** "Today", "Yesterday", "4 days ago", for how long a test has been out. */
function outFor(orderedAt: string): string {
  const day = localDay(orderedAt);
  const days = Math.round(
    (new Date(`${localDay(new Date().toISOString())}T00:00:00`).getTime() -
      new Date(`${day}T00:00:00`).getTime()) /
      86_400_000,
  );
  if (days <= 0) return "Ordered today";
  if (days === 1) return "Ordered yesterday";
  return `Ordered ${days} days ago`;
}

function Row({ item }: { item: LabOrderListed }) {
  const waiting = item.status === "ordered";
  return (
    <li>
      <Link
        href={`/lab/${item.id}` as Route}
        className="grid grid-cols-1 gap-x-4 gap-y-1 px-4 py-3 transition-colors hover:bg-[var(--surface-sunken)] focus-visible:bg-[var(--surface-sunken)] sm:grid-cols-[minmax(0,1fr)_auto]"
      >
        <span className="min-w-0">
          <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="text-[15px] font-medium break-words">{item.test_name}</span>
            <span className="font-mono text-[12px] text-[var(--text-subtle)] tabular">
              {item.order_number}
            </span>
          </span>
          <span className="block truncate text-[14px] text-[var(--text-muted)]">
            {item.patient.full_name}
            <span className="tabular">, {item.patient.patient_number}</span>
            {`, ${item.doctor.display_name}`}
          </span>
        </span>
        <span className="flex flex-wrap items-center gap-2 text-[13px] sm:justify-end">
          {item.urgent && <Urgent />}
          <FlaggedCount count={item.flagged} />
          <span className="text-[var(--text-muted)] tabular">
            {waiting
              ? outFor(item.ordered_at)
              : item.reported_on
                ? `Report of ${shortDate(item.reported_on)}`
                : shortDate(localDay(item.ordered_at))}
          </span>
          {!waiting && <LabStatusChip status={item.status} />}
        </span>
      </Link>
    </li>
  );
}

function Empty({ show, searched, mine }: { show: LabShow; searched: string; mine: boolean }) {
  const words = searched
    ? `Nothing here matches “${searched}”.`
    : {
        waiting: mine
          ? "Nothing you ordered is waiting for a report."
          : "No tests are waiting for a report. Tests appear here as soon as a doctor orders them.",
        to_review: mine
          ? "Nothing has come back for you to look at."
          : "No reports are waiting for a doctor to look at them.",
        reviewed: "No reports have been marked as seen yet.",
        cancelled: "No tests have been cancelled.",
      }[show];
  return (
    <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-10 text-center">
      <p className="text-[15px] text-[var(--text-muted)]">{words}</p>
    </div>
  );
}
