"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { ChevronDown, Loader2 } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useState } from "react";
import { FlaggedCount, LabStatusChip, ResultTable, Urgent } from "@/components/labs/parts";
import { shortDate } from "@/lib/appointments";
import { getLabOrder, listLabOrders, type LabOrderListed } from "@/lib/labs";
import { localDay } from "@/lib/prescriptions";

const SHOWN = 10;

/**
 * Every test this patient has had ordered, newest first. A report opens in
 * place, with last time's figures beside this time's, so a doctor can follow
 * a sugar or a haemoglobin without leaving the record.
 */
export function PatientLabs({ patientId }: { patientId: string }) {
  const orders = useInfiniteQuery({
    queryKey: ["lab-orders", "patient", patientId],
    queryFn: ({ pageParam }) =>
      listLabOrders({ patient: patientId, limit: SHOWN, offset: pageParam }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const shown = pages.reduce((sum, page) => sum + page.items.length, 0);
      return shown < last.total ? shown : undefined;
    },
    retry: false,
  });
  const items = orders.data?.pages.flatMap((page) => page.items) ?? [];

  return (
    <section
      aria-labelledby="labs-title"
      className="min-w-0 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
    >
      <h2 id="labs-title" className="text-[15px] font-semibold">
        Lab tests
      </h2>
      {orders.isPending ? (
        <p className="mt-3 inline-flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" /> Looking…
        </p>
      ) : orders.isError ? (
        <p className="mt-3 text-[14px] text-[var(--text-muted)]">Lab tests did not load.</p>
      ) : items.length === 0 ? (
        <p className="mt-2 text-[14px] leading-relaxed text-[var(--text-muted)]">
          None ordered yet. The doctor orders tests from the visit&apos;s notes.
        </p>
      ) : (
        <>
          <ol className="-mx-2 mt-2 flex flex-col">
            {items.map((item) => (
              <Entry key={item.id} item={item} />
            ))}
          </ol>
          {orders.hasNextPage && (
            <button
              type="button"
              onClick={() => void orders.fetchNextPage()}
              disabled={orders.isFetchingNextPage}
              className="mt-2 inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[13px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-60"
            >
              {orders.isFetchingNextPage && <Loader2 className="size-3.5 animate-spin" />}
              Show earlier tests
            </button>
          )}
        </>
      )}
    </section>
  );
}

function Entry({ item }: { item: LabOrderListed }) {
  const [open, setOpen] = useState(false);
  const hasReport = item.status === "resulted" || item.status === "reviewed";
  const full = useQuery({
    queryKey: ["lab-order", item.id],
    queryFn: () => getLabOrder(item.id),
    enabled: open,
    retry: false,
  });
  const day = item.reported_on ?? localDay(item.ordered_at);

  const summary = (
    <>
      <span className="w-20 shrink-0 text-[13px] text-[var(--text-muted)] tabular">
        {shortDate(day)}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-medium break-words">{item.test_name}</span>
        <span className="mt-0.5 flex flex-wrap items-center gap-2">
          {item.urgent && item.status === "ordered" && <Urgent />}
          <FlaggedCount count={item.flagged} />
          {item.status !== "reviewed" && <LabStatusChip status={item.status} />}
        </span>
      </span>
    </>
  );

  if (!hasReport) {
    return (
      <li>
        <Link
          href={`/lab/${item.id}` as Route}
          className="flex items-start gap-3 rounded-[var(--radius-field)] px-2 py-2 transition-colors hover:bg-[var(--surface-sunken)]"
        >
          {summary}
        </Link>
      </li>
    );
  }

  return (
    <li className="rounded-[var(--radius-field)]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start gap-3 rounded-[var(--radius-field)] px-2 py-2 text-left transition-colors hover:bg-[var(--surface-sunken)]"
      >
        {summary}
        <ChevronDown
          aria-hidden
          className={`mt-1 size-4 shrink-0 text-[var(--text-muted)] transition-transform motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
        />
        <span className="sr-only">{open ? "Hide the report" : "Show the report"}</span>
      </button>
      {open && (
        <div className="mx-2 mb-2 border-l-2 border-[var(--border-strong)] pl-3">
          {full.isPending ? (
            <Loader2 className="size-4 animate-spin text-[var(--text-muted)]" />
          ) : full.isError ? (
            <p className="text-[14px] text-[var(--text-muted)]">The report did not load.</p>
          ) : (
            <div className="flex flex-col gap-2">
              <ResultTable values={full.data.values} />
              {full.data.findings && (
                <p className="max-w-[70ch] text-[14px] leading-relaxed break-words whitespace-pre-wrap">
                  {full.data.findings}
                </p>
              )}
              <Link
                href={`/lab/${item.id}` as Route}
                className="w-fit text-[13px] underline underline-offset-2"
              >
                Open the report
              </Link>
            </div>
          )}
        </div>
      )}
    </li>
  );
}
