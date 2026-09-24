"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Ban, Check, Copy, Link2, Loader2, Mail, Smartphone } from "lucide-react";
import { useEffect, useState } from "react";
import { Amount, Problem, QUIET_BUTTON } from "@/components/billing/parts";
import { ApiFailure } from "@/lib/api";
import { whenItHappened } from "@/lib/appointments";
import {
  cancelPaymentLink,
  LINK_SAID,
  LINK_WORDS,
  sendPaymentLink,
  type Invoice,
  type LinkMade,
  type LinkStatus,
  type PaymentLink,
} from "@/lib/billing";

/**
 * Letting the patient settle the bill themselves.
 *
 * The desk either has the link emailed or reads the address out; either way
 * the money comes back marked online and the bill closes itself. The address
 * is shown once, when it is raised, because only its hash is kept — asking
 * again raises a new one and retires the old.
 */
export function PayOnline({ bill }: { bill: Invoice }) {
  const queries = useQueryClient();
  const [made, setMade] = useState<LinkMade | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const link = bill.payment_link;
  const waiting = link?.status === "open";
  const settled = link?.status === "paid";

  const raise = useMutation({
    mutationFn: (send: boolean) => sendPaymentLink(bill.id, { send, email: null }),
    onSuccess: (next) => {
      setMade(next);
      setProblem(null);
      void queries.invalidateQueries({ queryKey: ["bill", bill.id] });
    },
    onError: (error) =>
      setProblem(
        error instanceof ApiFailure
          ? (error.fields?.email ?? error.message)
          : "That did not go through. Try again.",
      ),
  });

  const callOff = useMutation({
    mutationFn: () => cancelPaymentLink(bill.id),
    onSuccess: (next) => {
      setMade(null);
      setProblem(null);
      queries.setQueryData(["bill", bill.id], next);
      void queries.invalidateQueries({ queryKey: ["bills"] });
    },
  });

  if (!bill.online_payments) return null;
  if (!bill.can_send_link && !link) return null;

  const busy = raise.isPending;

  return (
    <section
      aria-labelledby="online-heading"
      className="flex flex-col gap-4 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-5"
    >
      <div className="flex items-start justify-between gap-3">
        <h2
          id="online-heading"
          className="flex items-center gap-2 text-[16px] font-semibold text-nowrap"
        >
          <Smartphone aria-hidden className="size-4 shrink-0 text-[var(--text-muted)]" />
          Pay from a phone
        </h2>
        {link && <LinkState status={link.status} />}
      </div>

      {settled && link ? (
        <Settled link={link} />
      ) : made ? (
        <Address made={made} />
      ) : waiting && link ? (
        <Waiting link={link} />
      ) : (
        <p className="text-[14px] leading-relaxed text-[var(--text-muted)]">
          {link
            ? `The last link ${LINK_SAID[link.status]}. Send another whenever you like.`
            : "Send the patient a link. They pay by UPI or card on their own phone, and this bill marks itself paid the moment the money lands."}
        </p>
      )}

      <Problem>{problem}</Problem>

      {bill.can_send_link && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => raise.mutate(true)}
            disabled={busy}
            className={QUIET_BUTTON}
          >
            {busy && raise.variables === true ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Mail className="size-4" />
            )}
            {waiting || made ? "Email it again" : "Email the link"}
          </button>
          <button
            type="button"
            onClick={() => raise.mutate(false)}
            disabled={busy}
            className={QUIET_BUTTON}
          >
            {busy && raise.variables === false ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Link2 className="size-4" />
            )}
            {waiting || made ? "New link" : "Copy a link"}
          </button>
          {waiting && (
            <button
              type="button"
              onClick={() => callOff.mutate()}
              disabled={callOff.isPending}
              className="ml-auto inline-flex items-center gap-1.5 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--color-state-noshow)]"
            >
              {callOff.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Ban className="size-4" />
              )}
              Call it off
            </button>
          )}
        </div>
      )}
    </section>
  );
}

const LINK_TONE: Record<LinkStatus, string> = {
  open: "var(--color-state-waiting)",
  paid: "var(--color-state-completed)",
  cancelled: "var(--color-state-cancelled)",
  expired: "var(--color-state-cancelled)",
};

/** The same badge shape a bill's own status wears, so it reads the same way. */
function LinkState({ status }: { status: LinkStatus }) {
  const tone = LINK_TONE[status];
  return (
    <span
      className="inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-medium whitespace-nowrap text-[var(--text)]"
      style={{
        borderColor: `color-mix(in srgb, ${tone} 50%, transparent)`,
        background: `color-mix(in srgb, ${tone} 12%, transparent)`,
      }}
    >
      <span aria-hidden className="size-1.5 rounded-full" style={{ background: tone }} />
      {LINK_WORDS[status]}
    </span>
  );
}

/** Raised just now, and the one time its address is shown. */
function Address({ made }: { made: LinkMade }) {
  return (
    <div className="flex flex-col gap-2.5">
      <p className="text-[14px]">
        {made.sent_to && made.sent ? (
          <>
            <Amount value={made.amount} currency={made.currency} /> sent to{" "}
            <span className="font-medium">{made.sent_to}</span>.
          </>
        ) : made.sent_to ? (
          <>That did not send to {made.sent_to}. Read the link out instead.</>
        ) : (
          <>Read this out to the patient, or paste it into a message.</>
        )}
      </p>
      <CopyLink url={made.url} />
      <p className="text-[13px] leading-relaxed text-[var(--text-muted)]">
        Shown once, so copy it now — a new one can always be raised. It works until{" "}
        {whenItHappened(made.expires_at)}.
      </p>
    </div>
  );
}

/** Sent, not yet paid. What the desk wants to know is whether to chase. */
function Waiting({ link }: { link: PaymentLink }) {
  return (
    <div className="flex flex-col gap-2">
      <p className="text-[15px]">
        <Amount value={link.amount} currency={link.currency} className="font-semibold" />{" "}
        <span className="text-[var(--text-muted)]">waiting to be paid</span>
      </p>
      <dl className="flex flex-col gap-1 text-[13px]">
        <Fact
          label={link.sent_to ? "Sent to" : "Raised"}
          value={
            link.sent_to
              ? `${link.sent_to}, ${whenItHappened(link.sent_at ?? link.created_at)}`
              : whenItHappened(link.created_at)
          }
        />
        <Fact
          label="Opened"
          value={link.opened_at ? whenItHappened(link.opened_at) : "Not yet"}
        />
        <Fact label="Works until" value={whenItHappened(link.expires_at)} />
      </dl>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <dt className="w-[5.5rem] shrink-0 text-[var(--text-muted)]">{label}</dt>
      <dd className="min-w-0 break-words">{value}</dd>
    </div>
  );
}

function Settled({ link }: { link: PaymentLink }) {
  const spare = link.excess_amount !== "0.00";
  return (
    <div className="flex flex-col gap-2.5 text-[14px]">
      <p className="flex items-start gap-2">
        <Check
          aria-hidden
          className="mt-0.5 size-4 shrink-0 text-[var(--color-state-completed)]"
        />
        <span>
          <Amount value={link.amount} currency={link.currency} /> paid online
          {link.paid_at && ` ${whenItHappened(link.paid_at)}`}. Nobody here had to handle it.
        </span>
      </p>
      {spare && (
        <p
          role="alert"
          className="rounded-[var(--radius-field)] border border-[color-mix(in_srgb,var(--color-state-noshow)_35%,transparent)] bg-[color-mix(in_srgb,var(--color-state-noshow)_8%,transparent)] px-3 py-2.5 text-[13px] leading-relaxed"
        >
          <Amount value={link.excess_amount} currency={link.currency} /> of that had nowhere to
          go on this bill, because it was settled at the desk first. The clinic is holding it —
          give it back from the Razorpay dashboard.
        </p>
      )}
    </div>
  );
}

/** The address, readable and one press away from the clipboard. */
function CopyLink({ url }: { url: string }) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timer = setTimeout(() => setCopied(false), 2000);
    return () => clearTimeout(timer);
  }, [copied]);

  // Stacked rather than side by side: the panel is a narrow column, and an
  // address squeezed into what a button leaves over cannot be read out.
  return (
    <div className="flex flex-col gap-2">
      <input
        readOnly
        value={url}
        aria-label="Payment link"
        onFocus={(event) => event.currentTarget.select()}
        className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface-sunken)] px-3 py-2 font-mono text-[12px] outline-none focus:border-[var(--focus-ring)]"
      />
      <button
        type="button"
        onClick={() => {
          void navigator.clipboard?.writeText(url).then(() => setCopied(true));
        }}
        className={`${QUIET_BUTTON} self-start`}
      >
        {copied ? (
          <Check className="size-4 text-[var(--color-state-completed)]" />
        ) : (
          <Copy className="size-4" />
        )}
        {copied ? "Copied" : "Copy the link"}
      </button>
    </div>
  );
}
