"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { Amount, BillStatus } from "@/components/billing/parts";
import { shortDate } from "@/lib/appointments";
import { listBills } from "@/lib/billing";
import { localDay } from "@/lib/prescriptions";

const SHOWN = 6;

/** This patient's bills, newest first, and what they still owe. */
export function PatientBills({
  patientId,
  currency,
  mayRaise,
}: {
  patientId: string;
  currency: string;
  mayRaise: boolean;
}) {
  const found = useQuery({
    queryKey: ["bills", "patient", patientId],
    queryFn: () => listBills({ patient: patientId, limit: SHOWN }),
    retry: false,
  });
  const owed = found.data?.owed ?? "0.00";

  return (
    <section
      aria-labelledby="bills-title"
      className="min-w-0 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
    >
      <div className="flex items-center justify-between gap-2">
        <h2 id="bills-title" className="text-[15px] font-semibold">
          Bills
        </h2>
        {mayRaise && (
          <Link
            href={`/billing/new?patient=${patientId}` as Route}
            className="inline-flex items-center gap-1 rounded-[var(--radius-field)] px-2 py-1 text-[13px] font-medium text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
          >
            <Plus className="size-3.5" />
            New bill
          </Link>
        )}
      </div>
      {found.isPending ? (
        <p className="mt-3 inline-flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" /> Looking…
        </p>
      ) : found.isError ? (
        <p className="mt-3 text-[14px] text-[var(--text-muted)]">Bills did not load.</p>
      ) : found.data.items.length === 0 ? (
        <p className="mt-2 text-[14px] leading-relaxed text-[var(--text-muted)]">
          Nothing billed yet.
        </p>
      ) : (
        <>
          {owed !== "0.00" && (
            <p className="mt-2 rounded-[var(--radius-field)] bg-[var(--accent-wash)] px-2.5 py-1.5 text-[14px]">
              Owes <Amount value={owed} currency={currency} className="font-semibold" />
            </p>
          )}
          <ol className="mt-3 flex flex-col gap-1">
            {found.data.items.map((bill) => (
              <li key={bill.id}>
                <Link
                  href={`/billing/${bill.id}` as Route}
                  className="-mx-2 block rounded-[var(--radius-field)] px-2 py-1.5 transition-colors hover:bg-[var(--surface-sunken)]"
                >
                  <span className="flex items-baseline justify-between gap-2 text-[13px] text-[var(--text-muted)]">
                    <span className="font-mono tabular">{bill.invoice_number ?? "Draft"}</span>
                    <span className="tabular">
                      {shortDate(localDay(bill.issued_at ?? bill.created_at))}
                    </span>
                  </span>
                  <span className="flex items-center justify-between gap-2">
                    <Amount
                      value={bill.total}
                      currency={currency}
                      className={`text-[14px] font-medium ${bill.status === "void" ? "text-[var(--text-subtle)] line-through" : ""}`}
                    />
                    <BillStatus status={bill.status} />
                  </span>
                </Link>
              </li>
            ))}
          </ol>
          {found.data.total > SHOWN && (
            <Link
              href={
                `/billing?show=all&q=${encodeURIComponent(found.data.items[0]?.patient.patient_number ?? "")}` as Route
              }
              className="mt-2 inline-block text-[13px] text-[var(--text-muted)] underline underline-offset-2 hover:text-[var(--text)]"
            >
              All {found.data.total} bills
            </Link>
          )}
        </>
      )}
    </section>
  );
}
