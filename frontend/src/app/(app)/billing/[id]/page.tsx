"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, CircleCheck, Loader2, Printer, RotateCcw, Ban } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useState } from "react";
import { BillEditor } from "@/components/billing/editor";
import { GiveBack, TakePayment, VoidBill } from "@/components/billing/money";
import { ACCENT_BUTTON, Amount, BillStatus, QUIET_BUTTON } from "@/components/billing/parts";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { ApiFailure } from "@/lib/api";
import { longDate, shortDate, whenItHappened } from "@/lib/appointments";
import { billPdfHref, getBill, METHOD_WORDS, TYPE_WORDS, type Invoice } from "@/lib/billing";
import { localDay } from "@/lib/prescriptions";

export default function BillPage() {
  return (
    <Permitted permission="billing:read">
      <Bill />
    </Permitted>
  );
}

function Bill() {
  const id = String(useParams().id);
  const bill = useQuery({
    queryKey: ["bill", id],
    queryFn: () => getBill(id),
    retry: false,
  });

  if (bill.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Opening the bill…</span>
      </div>
    );
  }

  if (bill.isError) {
    const missing =
      bill.error instanceof ApiFailure && bill.error.code === "BILLING_INVOICE_NOT_FOUND";
    return (
      <Page
        title={missing ? "No such bill" : "That bill did not load"}
        back={{ href: "/billing" as Route, label: "Back to billing" }}
      >
        <p className="max-w-[54ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
          {missing
            ? "This bill does not exist at your clinic. A draft that was thrown away is gone for good."
            : "Something went wrong reaching the server. Try again in a moment."}
        </p>
      </Page>
    );
  }

  const found = bill.data;
  return found.status === "draft" ? <DraftBill bill={found} /> : <IssuedBill bill={found} />;
}

function WhoFor({ bill }: { bill: Invoice }) {
  return (
    <p className="flex flex-wrap items-baseline gap-x-2 text-[15px]">
      <Link
        href={`/patients/${bill.patient.id}` as Route}
        className="font-medium underline-offset-2 hover:underline"
      >
        {bill.patient.full_name}
      </Link>
      <span className="font-mono text-[13px] text-[var(--text-subtle)]">
        {bill.patient.patient_number}
      </span>
      {bill.visit && (
        <span className="text-[14px] text-[var(--text-muted)]">
          for the visit on {shortDate(bill.visit.date)}, token {bill.visit.token}
          {bill.doctor && ` with ${bill.doctor.display_name}`}
        </span>
      )}
    </p>
  );
}

function DraftBill({ bill }: { bill: Invoice }) {
  if (!bill.can_edit) {
    return (
      <Page title="Draft bill" back={{ href: "/billing" as Route, label: "Back to billing" }}>
        <WhoFor bill={bill} />
        <p className="mt-4 text-[15px] text-[var(--text-muted)]">
          This bill is still a draft. The desk issues it before it can be paid.
        </p>
      </Page>
    );
  }
  return (
    <Page
      title="Draft bill"
      blurb="Nothing is numbered yet. Change anything, then issue it."
      back={{ href: "/billing" as Route, label: "Back to billing" }}
    >
      <div className="mb-6">
        <WhoFor bill={bill} />
      </div>
      <BillEditor
        bill={bill}
        context={{
          patientId: bill.patient.id,
          visitId: bill.visit?.queue_entry_id ?? null,
          currency: bill.currency,
          taxPercent: bill.tax_percent,
          labTests: [],
        }}
        start={{
          items: bill.items,
          discount_amount: bill.discount_amount,
          discount_reason: bill.discount_reason,
          notes: bill.notes,
        }}
      />
    </Page>
  );
}

function IssuedBill({ bill }: { bill: Invoice }) {
  const [acting, setActing] = useState<"refund" | "void" | null>(null);
  const settled = bill.status === "paid" && bill.refunded_amount === "0.00";

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-10 lg:py-14">
      <Link
        href={"/billing" as Route}
        className="mb-6 inline-flex items-center gap-1.5 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
      >
        <ArrowLeft className="size-3.5" />
        Back to billing
      </Link>

      <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[26px] leading-tight font-semibold tracking-tight">
            <span>
              Bill <span className="font-mono text-[23px] tabular">{bill.invoice_number}</span>
            </span>
            <BillStatus status={bill.status} />
          </h1>
          <div className="mt-1.5">
            <WhoFor bill={bill} />
          </div>
        </div>
        <a
          href={billPdfHref(bill.id)}
          target="_blank"
          rel="noopener"
          className={settled ? ACCENT_BUTTON : QUIET_BUTTON}
        >
          <Printer className="size-4" />
          Print
        </a>
      </header>

      {bill.status === "void" && (
        <p
          role="status"
          className="mb-6 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--color-state-noshow)_40%,transparent)] bg-[color-mix(in_srgb,var(--color-state-noshow)_7%,transparent)] px-4 py-3 text-[15px]"
        >
          <span className="font-semibold">Voided</span>
          {bill.voided_at && ` ${whenItHappened(bill.voided_at)}`}
          {bill.voided_by && ` by ${bill.voided_by}`}
          {bill.void_reason && `: ${bill.void_reason}`}. Nothing is owed on it.
        </p>
      )}

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_21rem]">
        <Paper bill={bill} />

        <aside className="flex flex-col gap-5">
          {bill.can_pay && (
            <div className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-5">
              <TakePayment key={bill.balance} bill={bill} />
            </div>
          )}
          {settled && (
            <div className="flex items-start gap-3 rounded-[var(--radius-panel)] bg-[color-mix(in_srgb,var(--color-state-completed)_10%,transparent)] px-4 py-4">
              <CircleCheck
                aria-hidden
                className="mt-0.5 size-5 shrink-0 text-[var(--color-state-completed)]"
              />
              <div className="text-[15px]">
                <p className="font-semibold">Paid in full</p>
                <p className="text-[14px] text-[var(--text-muted)]">
                  The printed bill doubles as the receipt.
                </p>
              </div>
            </div>
          )}
          {bill.refunded_amount !== "0.00" && bill.status !== "void" && (
            <p className="text-[14px] text-[var(--text-muted)]">
              <Amount value={bill.refunded_amount} currency={bill.currency} /> has been given
              back, so this bill takes no more payments.
            </p>
          )}

          {acting === "refund" && <GiveBack bill={bill} onDone={() => setActing(null)} />}
          {acting === "void" && <VoidBill bill={bill} onDone={() => setActing(null)} />}

          {acting === null && (bill.can_refund || bill.can_void || bill.void_blocked) && (
            <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-4">
              {bill.can_refund && (
                <button
                  type="button"
                  onClick={() => setActing("refund")}
                  className="inline-flex items-center gap-2 self-start text-[14px] text-[var(--text-muted)] hover:text-[var(--text)]"
                >
                  <RotateCcw className="size-4" />
                  Give money back
                </button>
              )}
              {bill.can_void && (
                <button
                  type="button"
                  onClick={() => setActing("void")}
                  className="inline-flex items-center gap-2 self-start text-[14px] text-[var(--color-state-noshow)] hover:underline"
                >
                  <Ban className="size-4" />
                  Void this bill
                </button>
              )}
              {bill.void_blocked && !bill.can_void && (
                <p className="text-[13px] text-[var(--text-muted)]">{bill.void_blocked}</p>
              )}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

/** The bill laid out as it prints: what was charged, then what came in. */
function Paper({ bill }: { bill: Invoice }) {
  const discounted = bill.discount_amount !== "0.00";
  const taxed = bill.tax_amount !== "0.00";
  const voided = bill.status === "void";

  return (
    <article
      aria-label={`Bill ${bill.invoice_number}`}
      className="relative overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]"
    >
      <div className="flex flex-wrap justify-between gap-3 border-b border-dashed border-[var(--border-strong)] px-5 py-4 text-[14px]">
        <div>
          <p className="text-[13px] text-[var(--text-muted)]">Issued</p>
          <p>
            {bill.issued_at ? longDate(localDay(bill.issued_at)) : "Not yet"}
            {bill.issued_by && (
              <span className="text-[var(--text-muted)]"> by {bill.issued_by}</span>
            )}
          </p>
        </div>
        {bill.doctor && (
          <div className="sm:text-right">
            <p className="text-[13px] text-[var(--text-muted)]">Seen by</p>
            <p>{bill.doctor.display_name}</p>
          </div>
        )}
      </div>

      {/* A phone has no room for four columns, so each line stacks. */}
      <ul className="divide-y divide-[var(--border)] border-y border-[var(--border)] text-[14px] sm:hidden">
        {bill.items.map((item, index) => (
          <li
            key={index}
            className={`grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 px-5 py-2.5 ${voided ? "text-[var(--text-muted)]" : ""}`}
          >
            <span className="min-w-0">
              <span className="block">{item.description}</span>
              <span className="text-[12px] text-[var(--text-subtle)]">
                {TYPE_WORDS[item.item_type]}
                {item.quantity > 1 && (
                  <>
                    , {item.quantity} at{" "}
                    <Amount value={item.unit_price} currency={bill.currency} />
                  </>
                )}
              </span>
            </span>
            <Amount value={item.amount} currency={bill.currency} />
          </li>
        ))}
      </ul>
      <div className="hidden sm:block">
        <table className="w-full text-[14px]">
          <caption className="sr-only">What was charged</caption>
          <thead>
            <tr className="text-left text-[12px] text-[var(--text-muted)]">
              <th scope="col" className="px-5 pt-3 pb-2 font-medium">
                Item
              </th>
              <th scope="col" className="px-2 pt-3 pb-2 text-right font-medium">
                Qty
              </th>
              <th scope="col" className="px-2 pt-3 pb-2 text-right font-medium">
                Rate
              </th>
              <th scope="col" className="px-5 pt-3 pb-2 text-right font-medium">
                Amount
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--border)] border-y border-[var(--border)]">
            {bill.items.map((item, index) => (
              <tr key={index} className={voided ? "text-[var(--text-muted)]" : undefined}>
                <td className="px-5 py-2.5">
                  <span className="block">{item.description}</span>
                  <span className="text-[12px] text-[var(--text-subtle)]">
                    {TYPE_WORDS[item.item_type]}
                  </span>
                </td>
                <td className="px-2 py-2.5 text-right font-mono tabular">{item.quantity}</td>
                <td className="px-2 py-2.5 text-right">
                  <Amount value={item.unit_price} currency={bill.currency} />
                </td>
                <td className="px-5 py-2.5 text-right">
                  <Amount value={item.amount} currency={bill.currency} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <dl className="ml-auto flex max-w-sm flex-col gap-1.5 px-5 py-4 text-[14px]">
        {(discounted || taxed) && (
          <Figure label="Subtotal" value={bill.subtotal} currency={bill.currency} />
        )}
        {discounted && (
          <Figure
            label={`Discount${bill.discount_reason ? `, ${bill.discount_reason}` : ""}`}
            value={`-${bill.discount_amount}`}
            currency={bill.currency}
          />
        )}
        {taxed && (
          <Figure
            label={`Tax at ${Number(bill.tax_percent)}%`}
            value={bill.tax_amount}
            currency={bill.currency}
          />
        )}
        <div className="flex items-baseline justify-between gap-4 border-t border-[var(--border-strong)] pt-2">
          <dt className="font-semibold">Total</dt>
          <dd>
            <Amount
              value={bill.total}
              currency={bill.currency}
              className={`text-[20px] font-semibold ${voided ? "line-through decoration-[var(--color-state-noshow)] decoration-2" : ""}`}
            />
          </dd>
        </div>
        {!voided && bill.amount_paid !== "0.00" && (
          <Figure label="Paid" value={bill.amount_paid} currency={bill.currency} />
        )}
        {bill.refunded_amount !== "0.00" && (
          <Figure
            label="Given back"
            value={`-${bill.refunded_amount}`}
            currency={bill.currency}
          />
        )}
        {!voided && bill.balance !== "0.00" && bill.refunded_amount === "0.00" && (
          <div className="flex items-baseline justify-between gap-4 rounded-[var(--radius-field)] bg-[var(--accent-wash)] px-2 py-1.5">
            <dt className="font-semibold">Still to pay</dt>
            <dd>
              <Amount
                value={bill.balance}
                currency={bill.currency}
                className="text-[17px] font-semibold"
              />
            </dd>
          </div>
        )}
      </dl>

      {bill.payments.length > 0 && (
        <section
          aria-labelledby="received-heading"
          className="border-t border-dashed border-[var(--border-strong)] px-5 py-4"
        >
          <h2 id="received-heading" className="mb-2 text-[14px] font-semibold">
            Money in and out
          </h2>
          <ul className="flex flex-col gap-2 text-[14px]">
            {bill.payments.map((payment) => {
              const back = payment.kind === "refund";
              return (
                <li
                  key={payment.id}
                  className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-4"
                >
                  <span className="min-w-0">
                    {back ? "Given back" : "Received"}, {METHOD_WORDS[payment.method]}
                    {payment.reference && (
                      <span className="font-mono text-[13px] text-[var(--text-muted)]">
                        {" "}
                        {payment.reference}
                      </span>
                    )}
                    <span className="block text-[13px] text-[var(--text-muted)]">
                      {whenItHappened(payment.received_at)}
                      {payment.received_by && `, ${payment.received_by}`}
                      {payment.note && `. ${payment.note}`}
                    </span>
                  </span>
                  <Amount
                    value={back ? `-${payment.amount}` : payment.amount}
                    currency={bill.currency}
                    className={back ? "text-[var(--color-state-noshow)]" : undefined}
                  />
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {bill.notes && (
        <p className="border-t border-dashed border-[var(--border-strong)] px-5 py-4 text-[14px] whitespace-pre-line">
          <span className="block text-[13px] text-[var(--text-muted)]">Note</span>
          {bill.notes}
        </p>
      )}
    </article>
  );
}

function Figure({
  label,
  value,
  currency,
}: {
  label: string;
  value: string;
  currency: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <dt className="min-w-0 text-[var(--text-muted)]">{label}</dt>
      <dd className="shrink-0">
        <Amount value={value} currency={currency} />
      </dd>
    </div>
  );
}
