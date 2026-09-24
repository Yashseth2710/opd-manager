"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Loader2, Phone, ShieldCheck } from "lucide-react";
import { useParams } from "next/navigation";
import { useState } from "react";
import { ApiFailure } from "@/lib/api";
import { longDate, whenItHappened } from "@/lib/appointments";
import { money } from "@/lib/clinic";
import {
  confirmPayment,
  loadCheckout,
  openBill,
  type CheckoutOptions,
  type Handshake,
  type PayView,
} from "@/lib/pay";

/**
 * A bill, opened from a link, by somebody with no account and no reason to
 * want one. It says who is asking, what for, and how much, and then gets out
 * of the way of the one button that matters.
 */
export default function PayPage() {
  const token = String(useParams().token);
  const queries = useQueryClient();
  // Turned on when the checkout says a payment went through but confirming
  // it did not land. Razorpay tells the clinic separately, so the page waits
  // for that to arrive rather than telling the patient to pay again.
  const [chasing, setChasing] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);

  const bill = useQuery({
    queryKey: ["pay", token],
    queryFn: () => openBill(token),
    retry: false,
    refetchInterval: chasing ? 5000 : false,
  });

  const settle = useMutation({
    mutationFn: (handshake: Handshake) => confirmPayment(token, handshake),
    onSuccess: (next) => {
      setChasing(false);
      setNote(null);
      queries.setQueryData(["pay", token], next);
    },
    onError: () => {
      setChasing(true);
      setNote(
        "We have not been able to confirm that yet. If the money has left your account it will show here within a minute or two — there is no need to pay again.",
      );
    },
  });

  if (bill.isPending) return <Waiting />;
  if (bill.isError) return <Unusable error={bill.error} />;

  const found = bill.data;
  if (found.status === "paid") return <Receipt bill={found} />;
  if (found.status !== "open") return <Closed bill={found} />;

  const pay = async () => {
    if (!found.key_id || !found.order_id || !window) return;
    setNote(null);
    setOpening(true);
    try {
      await loadCheckout();
    } catch {
      setOpening(false);
      setNote("The payment window could not load. Check your connection and try again.");
      return;
    }
    const Checkout = window.Razorpay;
    if (!Checkout) {
      setOpening(false);
      setNote("The payment window could not load. Check your connection and try again.");
      return;
    }

    const options: CheckoutOptions = {
      key: found.key_id,
      amount: Math.round(Number(found.amount) * 100),
      currency: found.currency,
      name: found.clinic,
      description: found.invoice_number ? `Bill ${found.invoice_number}` : "Clinic bill",
      order_id: found.order_id,
      prefill: { name: found.patient_name },
      theme: { color: "#1f3450" },
      handler: (handshake) => settle.mutate(handshake),
      modal: {
        ondismiss: () => {
          setOpening(false);
          setNote("Nothing has been charged. The link still works whenever you are ready.");
        },
      },
    };
    const checkout = new Checkout(options);
    checkout.on("payment.failed", () => {
      setOpening(false);
      setNote("That payment did not go through. Nothing has been charged — try again.");
    });
    checkout.open();
  };

  const busy = opening || settle.isPending;

  return (
    <Stub clinic={found.clinic}>
      <p className="text-[14px] text-[var(--text-muted)]">
        {found.patient_name}
        {found.invoice_number && (
          <>
            {" · "}
            <span className="font-mono">{found.invoice_number}</span>
          </>
        )}
      </p>

      <div className="my-6 text-center">
        <p className="text-[13px] tracking-wide text-[var(--text-muted)]">Amount due</p>
        <p className="font-mono text-[40px] leading-tight font-semibold tabular">
          {money(found.amount, found.currency)}
        </p>
        {found.issued_on && (
          <p className="mt-1 text-[13px] text-[var(--text-muted)]">
            For the visit on {longDate(found.issued_on)}
          </p>
        )}
      </div>

      <button
        type="button"
        onClick={() => void pay()}
        disabled={busy}
        className="flex w-full items-center justify-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-3 text-[16px] font-semibold text-[var(--accent-fg)] transition hover:brightness-105 disabled:opacity-60"
      >
        {busy && <Loader2 className="size-4 animate-spin" />}
        {settle.isPending ? "Confirming" : `Pay ${money(found.amount, found.currency)}`}
      </button>

      <div className="mt-3 flex flex-wrap items-center justify-center gap-1.5">
        {["UPI", "Card", "Net banking", "Wallet"].map((how) => (
          <span
            key={how}
            className="rounded-full border border-[var(--border)] px-2.5 py-0.5 text-[12px] text-[var(--text-muted)]"
          >
            {how}
          </span>
        ))}
      </div>
      <p className="mt-3 text-center text-[13px] leading-relaxed text-[var(--text-muted)]">
        A payment window opens on top of this page. Nothing is charged until you finish it
        there.
      </p>

      {note && (
        <p
          role="status"
          className="mt-4 rounded-[var(--radius-field)] bg-[var(--surface-sunken)] px-3 py-2.5 text-[13px] leading-relaxed"
        >
          {note}
        </p>
      )}

      <Footer bill={found} showExpiry />
    </Stub>
  );
}

/** The clinic's own bill stub, torn along the top the way a paper one is. */
function Stub({
  clinic,
  eyebrow = "You are paying",
  children,
}: {
  clinic: string;
  eyebrow?: string;
  children: React.ReactNode;
}) {
  return (
    <article className="overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] shadow-[0_1px_2px_rgb(15_20_26/0.06)]">
      <header className="bg-[var(--rail)] px-6 py-5">
        <p className="text-[13px] text-[var(--rail-text)]">{eyebrow}</p>
        <h1 className="text-[20px] leading-tight font-semibold tracking-tight text-white">
          {clinic}
        </h1>
      </header>
      <div className="border-t border-dashed border-[var(--border-strong)] px-6 py-6">
        {children}
      </div>
    </article>
  );
}

function Footer({ bill, showExpiry = false }: { bill: PayView; showExpiry?: boolean }) {
  return (
    <div className="mt-6 flex flex-col gap-2 border-t border-[var(--border)] pt-4 text-[13px] text-[var(--text-muted)]">
      {showExpiry && <p>This link works until {whenItHappened(bill.expires_at)}.</p>}
      {bill.clinic_phone && (
        <p className="flex items-start gap-1.5">
          <Phone aria-hidden className="mt-[3px] size-3.5 shrink-0" />
          {/* One flex item, so the sentence wraps inside itself rather than
              breaking apart around the link. */}
          <span>
            Anything wrong? Call the clinic on{" "}
            <a
              href={`tel:${bill.clinic_phone}`}
              className="whitespace-nowrap underline underline-offset-2"
            >
              {bill.clinic_phone}
            </a>
          </span>
        </p>
      )}
      <p className="flex items-start gap-1.5">
        <ShieldCheck aria-hidden className="mt-[3px] size-3.5 shrink-0" />
        <span>Payment is handled by Razorpay. The clinic never sees your card details.</span>
      </p>
    </div>
  );
}

function Waiting() {
  return (
    <div className="flex items-center justify-center gap-3 py-20 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">Opening your bill…</span>
    </div>
  );
}

function Receipt({ bill }: { bill: PayView }) {
  return (
    <Stub clinic={bill.clinic} eyebrow="You paid">
      <div className="flex flex-col items-center gap-3 py-2 text-center">
        <CircleCheck
          aria-hidden
          className="size-10 text-[var(--color-state-completed)]"
          strokeWidth={1.5}
        />
        <div>
          <h2 className="text-[20px] font-semibold">Paid</h2>
          <p className="mt-1 text-[15px] text-[var(--text-muted)]">
            {money(bill.amount, bill.currency)}
            {bill.paid_at && `, ${whenItHappened(bill.paid_at)}`}
          </p>
        </div>
        {bill.invoice_number && (
          <p className="font-mono text-[13px] text-[var(--text-subtle)]">
            {bill.invoice_number}
          </p>
        )}
        <p className="max-w-[32ch] text-[14px] leading-relaxed text-[var(--text-muted)]">
          Nothing more is owed on this bill. The clinic has it on record — you can close this
          page.
        </p>
      </div>
      <Footer bill={bill} />
    </Stub>
  );
}

function Closed({ bill }: { bill: PayView }) {
  const said =
    bill.status === "expired"
      ? "This link has expired. If something is still owed, ask the clinic to send you a new one."
      : "This link is no longer active. It may have been settled at the clinic, or replaced by a newer one.";
  return (
    <Stub clinic={bill.clinic} eyebrow="A bill from">
      <h2 className="text-[18px] font-semibold">Nothing to pay here</h2>
      <p className="mt-2 max-w-[38ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
        {said}
      </p>
      <Footer bill={bill} />
    </Stub>
  );
}

/** A link that was never real, or one the server could not look up. */
function Unusable({ error }: { error: unknown }) {
  const missing =
    error instanceof ApiFailure &&
    (error.code === "PAYMENT_LINK_NOT_FOUND" || error.status === 404);
  return (
    <article className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-6 py-8">
      <h1 className="text-[19px] font-semibold">
        {missing ? "That link is not valid" : "This did not load"}
      </h1>
      <p className="mt-2 max-w-[40ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
        {missing
          ? "Check you copied the whole address, or ask the clinic to send it again. Nothing has been charged."
          : "Something went wrong reaching the clinic. Try again in a moment — nothing has been charged."}
      </p>
    </article>
  );
}
