"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useId, useRef, useState } from "react";
import {
  ACCENT_BUTTON,
  Amount,
  DANGER_BUTTON,
  FIELD,
  Problem,
  QUIET_BUTTON,
  TextField,
} from "@/components/billing/parts";
import { ApiFailure } from "@/lib/api";
import { money } from "@/lib/clinic";
import {
  freshKey,
  fromPaise,
  giveBack,
  METHOD_WORDS,
  REFERENCE_WORDS,
  takePayment,
  toPaise,
  voidBill,
  type Invoice,
  type Method,
} from "@/lib/billing";

const METHODS = Object.entries(METHOD_WORDS) as [Method, string][];

function useSettled(bill: Invoice) {
  const queries = useQueryClient();
  return (next: Invoice) => {
    queries.setQueryData(["bill", bill.id], next);
    void queries.invalidateQueries({ queryKey: ["bills"] });
    void queries.invalidateQueries({ queryKey: ["bill-summary"] });
    void queries.invalidateQueries({ queryKey: ["queue"] });
  };
}

function MethodChoice({
  value,
  onChange,
  name,
}: {
  value: Method;
  onChange: (method: Method) => void;
  name: string;
}) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="mb-1.5 text-[13px] font-medium">How</legend>
      <div className="flex flex-wrap gap-1.5">
        {METHODS.map(([method, words]) => (
          <label
            key={method}
            className="cursor-pointer rounded-full border border-[var(--border-strong)] px-3 py-1.5 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] has-[:checked]:border-[var(--primary)] has-[:checked]:bg-[var(--primary)] has-[:checked]:text-[var(--primary-fg)] has-[:focus-visible]:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_35%,transparent)]"
          >
            <input
              type="radio"
              name={name}
              value={method}
              checked={value === method}
              onChange={() => onChange(method)}
              className="sr-only"
            />
            {words}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function RupeeInput({
  label,
  name,
  value,
  onChange,
  error,
  hint,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  hint?: React.ReactNode;
}) {
  const id = useId();
  const said = error ?? hint;
  return (
    <div className="flex flex-col gap-1.5 text-[13px] font-medium">
      <label htmlFor={id}>{label}</label>
      <span className="relative">
        <span
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 font-normal text-[var(--text-subtle)]"
        >
          ₹
        </span>
        <input
          id={id}
          name={name}
          value={value}
          inputMode="decimal"
          autoComplete="off"
          aria-invalid={Boolean(error)}
          aria-describedby={said ? `${id}-said` : undefined}
          onChange={(event) => onChange(event.target.value)}
          className={`${FIELD} pl-7 font-mono text-[17px] font-normal tabular`}
        />
      </span>
      {said && (
        <span
          id={`${id}-said`}
          className={`font-normal ${error ? "text-[var(--color-state-noshow)]" : "text-[var(--text-muted)]"}`}
        >
          {said}
        </span>
      )}
    </div>
  );
}

/**
 * Money coming in against the bill: all that is owed unless the patient is
 * paying part now, by whichever way they paid. For cash, what was handed
 * over can be typed in to see the change to give.
 *
 * Keyed by the balance where it is used, so that once money comes in, from
 * here or another desk, it starts again from what is now owed.
 */
export function TakePayment({ bill }: { bill: Invoice }) {
  const settled = useSettled(bill);
  const [amount, setAmount] = useState(bill.balance);
  const [method, setMethod] = useState<Method>("cash");
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [handed, setHanded] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const attempt = useRef(freshKey());
  const sending = useRef(false);

  const take = useMutation({
    mutationFn: () =>
      takePayment(
        bill.id,
        {
          amount: fromPaise(toPaise(amount) ?? 0),
          method,
          reference: REFERENCE_WORDS[method] && reference.trim() ? reference.trim() : null,
          note: note.trim() || null,
        },
        attempt.current,
      ),
    onSuccess: (next) => {
      attempt.current = freshKey();
      setReference("");
      setNote("");
      setFields({});
      settled(next);
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.fields) setFields(error.fields);
      // Refused outright, so the next try is a new attempt. A dropped
      // connection keeps the key, in case the first one landed.
      if (error instanceof ApiFailure && error.status >= 400 && error.status < 500)
        attempt.current = freshKey();
    },
    onSettled: () => {
      sending.current = false;
    },
  });

  const owed = toPaise(bill.balance) ?? 0;
  const taking = toPaise(amount);
  const given = method === "cash" ? toPaise(handed) : null;
  const change = given !== null && taking !== null && given >= taking ? given - taking : null;
  const referenceWords = REFERENCE_WORDS[method];

  const submit = () => {
    if (sending.current) return;
    const found: Record<string, string> = {};
    if (taking === null || taking <= 0) found.amount = "Type what is being paid, like 500.";
    else if (taking > owed)
      found.amount = `${money(fromPaise(owed), bill.currency)} is all that is owed on this bill.`;
    setFields(found);
    if (Object.keys(found).length) return;
    sending.current = true;
    take.mutate();
  };

  return (
    <form
      noValidate
      aria-labelledby="take-heading"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="flex flex-col gap-4"
    >
      <h2 id="take-heading" className="text-[16px] font-semibold">
        Take payment
      </h2>
      <RupeeInput
        label="Amount"
        name="amount"
        value={amount}
        onChange={setAmount}
        error={fields.amount}
        hint={
          taking !== null && taking > 0 && taking < owed
            ? `Part of it. ${money(fromPaise(owed - taking), bill.currency)} will still be owed.`
            : null
        }
      />
      <MethodChoice value={method} onChange={setMethod} name="method" />
      {referenceWords && (
        <label className="flex flex-col gap-1.5 text-[13px] font-medium">
          {referenceWords}
          <input
            name="reference"
            value={reference}
            maxLength={60}
            autoComplete="off"
            onChange={(event) => setReference(event.target.value)}
            placeholder="Optional"
            className={`${FIELD} font-normal`}
          />
        </label>
      )}
      {method === "cash" && (
        <RupeeInput
          label="Cash handed over"
          name="handed"
          value={handed}
          onChange={setHanded}
          hint={
            change !== null ? (
              <span className="text-[var(--text)]">
                Give back <Amount value={fromPaise(change)} currency={bill.currency} />
              </span>
            ) : (
              "Optional, to work out the change."
            )
          }
        />
      )}
      <label className="flex flex-col gap-1.5 text-[13px] font-medium">
        Note
        <input
          name="note"
          value={note}
          maxLength={200}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Optional, such as who paid"
          className={`${FIELD} font-normal`}
        />
      </label>
      <Problem>
        {take.error && !Object.keys(fields).length
          ? take.error instanceof ApiFailure
            ? take.error.message
            : "That did not go through. Try again."
          : null}
      </Problem>
      <button type="submit" disabled={take.isPending} className={`${ACCENT_BUTTON} py-2.5`}>
        {take.isPending && <Loader2 className="size-4 animate-spin" />}
        Take{" "}
        {taking !== null && taking > 0 ? (
          <Amount value={fromPaise(taking)} currency={bill.currency} />
        ) : (
          "payment"
        )}
      </button>
    </form>
  );
}

/** Money going back to the patient. The clinic admin's to give. */
export function GiveBack({ bill, onDone }: { bill: Invoice; onDone: () => void }) {
  const settled = useSettled(bill);
  const held = (toPaise(bill.amount_paid) ?? 0) - (toPaise(bill.refunded_amount) ?? 0);
  const [amount, setAmount] = useState(fromPaise(held));
  const [method, setMethod] = useState<Method>("cash");
  const [reason, setReason] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const attempt = useRef(freshKey());

  const give = useMutation({
    mutationFn: () =>
      giveBack(
        bill.id,
        {
          amount: fromPaise(toPaise(amount) ?? 0),
          method,
          reason: reason.trim(),
          reference: null,
        },
        attempt.current,
      ),
    onSuccess: (next) => {
      settled(next);
      onDone();
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.fields) setFields(error.fields);
      if (error instanceof ApiFailure && error.status >= 400 && error.status < 500)
        attempt.current = freshKey();
    },
  });

  const submit = () => {
    const found: Record<string, string> = {};
    const giving = toPaise(amount);
    if (giving === null || giving <= 0) found.amount = "Type what is being given back.";
    else if (giving > held)
      found.amount = `${money(fromPaise(held), bill.currency)} is all that has been taken on this bill.`;
    if (!reason.trim()) found.reason = "Say why, for whoever reads the bill later.";
    setFields(found);
    if (!Object.keys(found).length) give.mutate();
  };

  return (
    <form
      noValidate
      aria-labelledby="refund-heading"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      className="flex flex-col gap-4 rounded-[var(--radius-panel)] border border-[var(--border-strong)] px-4 py-4"
    >
      <h2 id="refund-heading" className="text-[16px] font-semibold">
        Give money back
      </h2>
      <RupeeInput
        label="Amount"
        name="refund_amount"
        value={amount}
        onChange={setAmount}
        error={fields.amount}
      />
      <MethodChoice value={method} onChange={setMethod} name="refund_method" />
      <TextField
        label="Why"
        name="reason"
        value={reason}
        error={fields.reason}
        onChange={setReason}
        placeholder="Test not done, charged twice"
      />
      <p className="text-[13px] text-[var(--text-muted)]">
        Once money has gone back, the bill takes no more payments.
      </p>
      <Problem>
        {give.error && !Object.keys(fields).length
          ? give.error instanceof ApiFailure
            ? give.error.message
            : "That did not go through. Try again."
          : null}
      </Problem>
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={give.isPending} className={DANGER_BUTTON}>
          {give.isPending && <Loader2 className="size-4 animate-spin" />}
          Give it back
        </button>
        <button type="button" onClick={onDone} className={QUIET_BUTTON}>
          Not now
        </button>
      </div>
    </form>
  );
}

/** Cancelling an issued bill. It keeps its number and says why. */
export function VoidBill({ bill, onDone }: { bill: Invoice; onDone: () => void }) {
  const settled = useSettled(bill);
  const [reason, setReason] = useState("");
  const [missing, setMissing] = useState(false);

  const cancel = useMutation({
    mutationFn: () => voidBill(bill.id, reason.trim()),
    onSuccess: (next) => {
      settled(next);
      onDone();
    },
  });

  return (
    <form
      noValidate
      aria-labelledby="void-heading"
      onSubmit={(event) => {
        event.preventDefault();
        if (!reason.trim()) {
          setMissing(true);
          return;
        }
        cancel.mutate();
      }}
      className="flex flex-col gap-3 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--color-state-noshow)_45%,transparent)] px-4 py-4"
    >
      <h2 id="void-heading" className="text-[16px] font-semibold">
        Void {bill.invoice_number}?
      </h2>
      <p className="text-[14px] text-[var(--text-muted)]">
        It stays on record, marked void, and nothing is owed on it. A visit it was for can be
        billed again.
      </p>
      <TextField
        label="Why"
        name="void_reason"
        value={reason}
        autoFocus
        error={missing ? "Say why it is being voided." : null}
        onChange={(value) => {
          setMissing(false);
          setReason(value);
        }}
        placeholder="Wrong patient, raised twice"
      />
      <Problem>
        {cancel.error instanceof ApiFailure
          ? cancel.error.message
          : cancel.error
            ? "That did not go through. Try again."
            : null}
      </Problem>
      <div className="flex flex-wrap gap-2">
        <button type="submit" disabled={cancel.isPending} className={DANGER_BUTTON}>
          {cancel.isPending && <Loader2 className="size-4 animate-spin" />}
          Void the bill
        </button>
        <button type="button" onClick={onDone} className={QUIET_BUTTON}>
          Keep it
        </button>
      </div>
    </form>
  );
}
