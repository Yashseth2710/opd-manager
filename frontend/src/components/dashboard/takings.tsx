"use client";

import { useQuery } from "@tanstack/react-query";
import type { Route } from "next";
import Link from "next/link";
import { Panel, Quiet } from "@/components/dashboard/parts";
import { getSummary } from "@/lib/billing";
import { money } from "@/lib/clinic";
import { REFRESH_MS } from "@/lib/dashboard";

/**
 * The money side of the day, for whoever handles it.
 *
 * Reads the same day summary the billing page reads, which is worked out in
 * one place for both, so the figure here and the figure there cannot differ.
 */
export function Takings({ seesReports }: { seesReports: boolean }) {
  const summary = useQuery({
    queryKey: ["bill-summary", null],
    queryFn: () => getSummary(),
    retry: false,
    refetchInterval: REFRESH_MS,
  });

  const day = summary.data;
  return (
    <Panel
      id="money-today"
      title="Money today"
      more={
        seesReports
          ? { href: "/reports", label: "Reports" }
          : { href: "/billing", label: "Billing" }
      }
    >
      {summary.isPending ? (
        <div aria-hidden className="flex gap-px bg-[var(--border)]">
          {Array.from({ length: 3 }, (_, index) => (
            <div key={index} className="flex-1 bg-[var(--surface)] px-5 py-4">
              <span className="block h-3.5 w-20 animate-pulse rounded bg-[var(--surface-sunken)]" />
              <span className="mt-2 block h-6 w-24 animate-pulse rounded bg-[var(--surface-sunken)]" />
            </div>
          ))}
        </div>
      ) : !day ? (
        <Quiet>The day&apos;s takings did not load. The billing page has them too.</Quiet>
      ) : (
        <dl className="grid grid-cols-1 gap-px bg-[var(--border)] sm:grid-cols-3">
          <Figure
            label="Taken so far"
            value={money(day.net, day.currency)}
            note={
              day.online !== "0.00"
                ? `${money(day.online, day.currency)} of it from a link`
                : day.net === "0.00"
                  ? "Nothing yet"
                  : "All of it over the desk"
            }
          />
          <Figure
            label="Billed"
            value={money(day.billed, day.currency)}
            note={
              day.bills_issued === 0
                ? "No bills handed over yet"
                : `${day.bills_issued} ${day.bills_issued === 1 ? "bill" : "bills"} handed over`
            }
          />
          <Figure
            label="Still owed"
            value={money(day.outstanding, day.currency)}
            note={
              day.outstanding_bills === 0 ? (
                "Nothing outstanding"
              ) : (
                <Link
                  href={"/billing?show=to_collect" as Route}
                  className="underline decoration-[var(--border-strong)] underline-offset-4 transition-colors hover:text-[var(--text)]"
                >
                  on {day.outstanding_bills} {day.outstanding_bills === 1 ? "bill" : "bills"},
                  all told
                </Link>
              )
            }
          />
        </dl>
      )}
    </Panel>
  );
}

function Figure({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note: React.ReactNode;
}) {
  return (
    <div className="bg-[var(--surface)] px-5 py-4">
      <dt className="text-[13px] text-[var(--text-muted)]">{label}</dt>
      <dd className="mt-1 font-mono text-[22px] leading-none font-semibold tabular">{value}</dd>
      <dd className="mt-2 text-[13px] leading-snug text-[var(--text-muted)]">{note}</dd>
    </div>
  );
}
