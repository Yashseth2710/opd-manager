"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Plus, Trash2, X } from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import {
  ACCENT_BUTTON,
  Amount,
  FIELD,
  Problem,
  QUIET_BUTTON,
  TextField,
} from "@/components/billing/parts";
import { ApiFailure } from "@/lib/api";
import {
  changeBill,
  discardBill,
  freshKey,
  fromPaise,
  getPastLines,
  issueBill,
  MAX_LINES,
  raiseBill,
  toPaise,
  TYPE_WORDS,
  workOut,
  type Draft,
  type Invoice,
  type ItemType,
  type Line,
} from "@/lib/billing";

type Row = Line & { key: string; price: string; count: string };

let counter = 0;
const nextKey = () => `line-${++counter}`;

function asRow(line: Line): Row {
  return {
    ...line,
    key: nextKey(),
    price: line.unit_price === "" ? "" : fromPaise(toPaise(line.unit_price) ?? 0),
    count: String(line.quantity),
  };
}

const blankRow = (item_type: ItemType = "procedure", description = ""): Row =>
  asRow({ item_type, description, quantity: 1, unit_price: "" });

/** The field a server complaint belongs to, whichever way it was named. */
function fieldOf(name: string): string {
  return name.replace(/^body\./, "");
}

export type EditorContext = {
  patientId: string;
  visitId: string | null;
  currency: string;
  taxPercent: string;
  labTests: string[];
};

/**
 * A bill being written: its lines, a discount if there is one, and a note
 * for the patient. Kept as a draft or issued from here; issuing gives it its
 * number and fixes what it says.
 */
export function BillEditor({
  context,
  start,
  bill,
}: {
  context: EditorContext;
  start: Draft;
  /** The draft being changed. Without one, the bill is new. */
  bill?: Invoice;
}) {
  const router = useRouter();
  const queries = useQueryClient();
  const [rows, setRows] = useState<Row[]>(() =>
    start.items.length ? start.items.map(asRow) : [blankRow()],
  );
  const [discount, setDiscount] = useState(
    start.discount_amount && toPaise(start.discount_amount) ? start.discount_amount : "",
  );
  const [reason, setReason] = useState(start.discount_reason ?? "");
  const [notes, setNotes] = useState(start.notes ?? "");
  const [showDiscount, setShowDiscount] = useState(Boolean(discount));
  const [showNotes, setShowNotes] = useState(Boolean(notes));
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  // One attempt at raising this bill. A retry after a dropped connection
  // sends the same key, and the server answers with the bill it made.
  const attempt = useRef(freshKey());
  const sending = useRef(false);

  const lines: Line[] = rows.map((row) => ({
    item_type: row.item_type,
    description: row.description,
    quantity: Number(row.count),
    unit_price: row.price,
  }));
  const worked = workOut(lines, showDiscount ? discount : "0", context.taxPercent);

  // Leaving with changes unsaved asks first.
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const touch = (...answered: string[]) => {
    setDirty(true);
    setProblem(null);
    // A field put right stops saying what was wrong with it.
    if (answered.length)
      setFields((current) =>
        Object.fromEntries(
          Object.entries(current).filter(
            ([name]) => !answered.some((each) => name === each || name.startsWith(`${each}.`)),
          ),
        ),
      );
  };

  const update = (key: string, change: Partial<Row>) => {
    const index = rows.findIndex((row) => row.key === key);
    const parts = { description: "description", price: "unit_price", count: "quantity" };
    touch(
      ...Object.keys(change)
        .filter((part): part is keyof typeof parts => part in parts)
        .map((part) => `items.${index}.${parts[part]}`),
    );
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...change } : row)));
  };

  const addRow = (row: Row = blankRow()) => {
    touch();
    setRows((current) => [...current, row]);
    requestAnimationFrame(() =>
      document.querySelector<HTMLInputElement>(`[data-line="${row.key}"]`)?.focus(),
    );
  };

  const removeRow = (key: string) => {
    // What was wrong is keyed by position, which just moved.
    touch("items");
    setRows((current) =>
      current.length > 1 ? current.filter((row) => row.key !== key) : current,
    );
  };

  /** What is wrong before anything is sent, keyed as the server keys it. */
  const check = (): Record<string, string> => {
    const found: Record<string, string> = {};
    rows.forEach((row, index) => {
      if (!row.description.trim()) found[`items.${index}.description`] = "Say what it is for.";
      if (toPaise(row.price) === null)
        found[`items.${index}.unit_price`] = "Type an amount, like 150 or 99.50.";
      const count = Number(row.count);
      if (!Number.isInteger(count) || count < 1 || count > 999)
        found[`items.${index}.quantity`] = "1 to 999.";
    });
    if (showDiscount && discount.trim()) {
      const off = toPaise(discount);
      if (off === null) found.discount_amount = "Type an amount, like 50.";
      else if (off > worked.subtotal)
        found.discount_amount = "The discount is more than the bill.";
      else if (off > 0 && !reason.trim())
        found.discount_reason = "Say why there is a discount.";
    }
    return found;
  };

  const body = (): Draft => ({
    items: lines.map((line) => ({
      ...line,
      description: line.description.trim(),
      unit_price: fromPaise(toPaise(line.unit_price) ?? 0),
    })),
    discount_amount:
      showDiscount && discount.trim() ? fromPaise(toPaise(discount) ?? 0) : "0.00",
    discount_reason: showDiscount && reason.trim() ? reason.trim() : null,
    notes: notes.trim() || null,
  });

  const save = useMutation({
    mutationFn: async (issue: boolean): Promise<Invoice> => {
      if (bill) {
        const saved = await changeBill(bill.id, body());
        return issue ? issueBill(saved.id) : saved;
      }
      return raiseBill(
        {
          ...body(),
          patient_id: context.patientId,
          queue_entry_id: context.visitId,
          issue,
        },
        attempt.current,
      );
    },
    onSuccess: async (saved) => {
      setDirty(false);
      queries.setQueryData(["bill", saved.id], saved);
      void queries.invalidateQueries({ queryKey: ["bills"] });
      void queries.invalidateQueries({ queryKey: ["queue"] });
      if (bill) {
        await queries.invalidateQueries({ queryKey: ["bill", saved.id] });
      } else {
        router.replace(`/billing/${saved.id}` as Route);
      }
    },
    onError: (error) => {
      if (error instanceof ApiFailure) {
        if (error.fields) {
          setFields(
            Object.fromEntries(
              Object.entries(error.fields).map(([name, words]) => [fieldOf(name), words]),
            ),
          );
        }
        setProblem(error.message);
        if (error.code === "BILLING_ALREADY_BILLED") setDirty(false);
      } else {
        setProblem("That did not go through. Try again.");
      }
    },
    onSettled: () => {
      sending.current = false;
    },
  });

  const discard = useMutation({
    mutationFn: () => discardBill(bill!.id),
    onSuccess: () => {
      setDirty(false);
      void queries.invalidateQueries({ queryKey: ["bills"] });
      router.replace("/billing" as Route);
    },
    onError: (error) =>
      setProblem(error instanceof Error ? error.message : "That did not go through."),
  });

  const submit = (issue: boolean) => {
    if (sending.current) return;
    const found = check();
    setFields(found);
    if (Object.keys(found).length) {
      setProblem("Some details need attention. Each one says what is wrong.");
      requestAnimationFrame(() =>
        document.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus(),
      );
      return;
    }
    sending.current = true;
    setProblem(null);
    save.mutate(issue);
  };

  const already =
    save.error instanceof ApiFailure && save.error.code === "BILLING_ALREADY_BILLED";
  const existing = already
    ? ((save.error as ApiFailure).candidates?.[0] as { id: string } | undefined)
    : undefined;
  const offered = context.labTests.filter(
    (test) => !rows.some((row) => row.description.trim().toLowerCase() === test.toLowerCase()),
  );
  const busy = save.isPending || discard.isPending;

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit(true);
      }}
      className="flex flex-col gap-6"
    >
      <section aria-labelledby="lines-heading" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="lines-heading" className="text-[16px] font-semibold">
            What it is for
          </h2>
          <span className="text-[13px] text-[var(--text-muted)] tabular">
            {rows.length} of {MAX_LINES} lines
          </span>
        </div>
        <ol className="flex flex-col divide-y divide-[var(--border)] rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
          {rows.map((row, index) => (
            <LineRow
              key={row.key}
              row={row}
              index={index}
              amount={worked.lines[index] ?? null}
              currency={context.currency}
              fields={fields}
              removable={rows.length > 1}
              onChange={(change) => update(row.key, change)}
              onRemove={() => removeRow(row.key)}
            />
          ))}
        </ol>
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => addRow()}
            disabled={rows.length >= MAX_LINES}
            className={QUIET_BUTTON}
          >
            <Plus className="size-4" />
            Add a line
          </button>
          {offered.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5 text-[13px]">
              <span className="text-[var(--text-muted)]">Tests ordered at this visit:</span>
              {offered.map((test) => (
                <button
                  key={test}
                  type="button"
                  disabled={rows.length >= MAX_LINES}
                  onClick={() => addRow(blankRow("lab", test))}
                  className="inline-flex items-center gap-1 rounded-full border border-dashed border-[var(--border-strong)] px-2.5 py-1 transition-colors hover:border-solid hover:bg-[var(--surface-sunken)]"
                >
                  <Plus className="size-3" />
                  {test}
                </button>
              ))}
            </div>
          )}
        </div>
      </section>

      <div className="grid gap-6 md:grid-cols-[minmax(0,1fr)_18rem]">
        <div className="flex flex-col gap-4">
          {showDiscount ? (
            <fieldset className="flex flex-col gap-3 rounded-[var(--radius-panel)] border border-[var(--border)] px-4 py-3">
              <legend className="px-1 text-[14px] font-medium">Discount</legend>
              <div className="grid gap-3 sm:grid-cols-[9rem_minmax(0,1fr)]">
                <MoneyField
                  label="Amount off"
                  name="discount_amount"
                  value={discount}
                  error={fields.discount_amount}
                  onChange={(value) => {
                    touch("discount_amount");
                    setDiscount(value);
                  }}
                />
                <TextField
                  label="Why"
                  name="discount_reason"
                  value={reason}
                  error={fields.discount_reason}
                  onChange={(value) => {
                    touch("discount_reason");
                    setReason(value);
                  }}
                  placeholder="Staff family, senior citizen, camp"
                />
              </div>
              <button
                type="button"
                onClick={() => {
                  touch();
                  setShowDiscount(false);
                  setDiscount("");
                  setReason("");
                }}
                className="self-start text-[13px] text-[var(--text-muted)] underline underline-offset-2 hover:text-[var(--text)]"
              >
                No discount
              </button>
            </fieldset>
          ) : (
            <button
              type="button"
              onClick={() => setShowDiscount(true)}
              className="self-start text-[14px] text-[var(--text-muted)] underline underline-offset-2 hover:text-[var(--text)]"
            >
              Give a discount
            </button>
          )}
          {showNotes ? (
            <label className="flex flex-col gap-1.5 text-[13px] font-medium">
              A note on the bill
              <textarea
                name="notes"
                value={notes}
                maxLength={500}
                rows={2}
                onChange={(event) => {
                  touch();
                  setNotes(event.target.value);
                }}
                placeholder="Printed under the sums, for the patient to read."
                className={`${FIELD} resize-y font-normal`}
              />
            </label>
          ) : (
            <button
              type="button"
              onClick={() => setShowNotes(true)}
              className="self-start text-[14px] text-[var(--text-muted)] underline underline-offset-2 hover:text-[var(--text)]"
            >
              Add a note for the patient
            </button>
          )}
        </div>

        <Sums worked={worked} currency={context.currency} taxPercent={context.taxPercent} />
      </div>

      <div className="flex flex-col gap-3 border-t border-[var(--border)] pt-5">
        <Problem>{problem}</Problem>
        {existing && (
          <p className="text-[14px]">
            <a
              href={`/billing/${existing.id}`}
              className="font-medium underline underline-offset-2"
            >
              Open the bill already raised for this visit
            </a>
          </p>
        )}
        {confirmDiscard ? (
          <div role="alert" className="flex flex-wrap items-center gap-3 text-[14px]">
            <span>Throw this draft away? It has no number, so nothing is left behind.</span>
            <button
              type="button"
              autoFocus
              onClick={() => discard.mutate()}
              disabled={busy}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--color-state-noshow)] px-3.5 py-2 font-semibold text-white hover:brightness-110 disabled:opacity-60"
            >
              {discard.isPending && <Loader2 className="size-4 animate-spin" />}
              Yes, delete the draft
            </button>
            <button
              type="button"
              onClick={() => setConfirmDiscard(false)}
              className={QUIET_BUTTON}
            >
              Keep it
            </button>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <button type="submit" disabled={busy || already} className={ACCENT_BUTTON}>
              {save.isPending && save.variables === true && (
                <Loader2 className="size-4 animate-spin" />
              )}
              Issue the bill
            </button>
            <button
              type="button"
              onClick={() => submit(false)}
              disabled={busy || already}
              className={QUIET_BUTTON}
            >
              {save.isPending && save.variables === false && (
                <Loader2 className="size-4 animate-spin" />
              )}
              {bill ? "Save the draft" : "Keep as a draft"}
            </button>
            {bill && (
              <button
                type="button"
                onClick={() => setConfirmDiscard(true)}
                disabled={busy}
                className="ml-auto inline-flex items-center gap-1.5 px-2 py-2 text-[14px] text-[var(--color-state-noshow)] hover:underline disabled:opacity-60"
              >
                <Trash2 className="size-4" />
                Delete the draft
              </button>
            )}
          </div>
        )}
        <p className="text-[13px] text-[var(--text-muted)]">
          Issuing gives the bill its number. After that it stays as it is; a mistake is put
          right by voiding it and raising another.
        </p>
      </div>
    </form>
  );
}

function Sums({
  worked,
  currency,
  taxPercent,
}: {
  worked: ReturnType<typeof workOut>;
  currency: string;
  taxPercent: string;
}) {
  const rate = Number(taxPercent);
  return (
    <dl
      aria-label="What the bill comes to"
      className="flex flex-col gap-1.5 self-start rounded-[var(--radius-panel)] bg-[var(--surface-sunken)] px-4 py-3 text-[14px]"
    >
      {(worked.discount > 0 || worked.tax > 0) && (
        <SumRow label="Subtotal" value={fromPaise(worked.subtotal)} currency={currency} />
      )}
      {worked.discount > 0 && (
        <SumRow label="Discount" value={fromPaise(-worked.discount)} currency={currency} />
      )}
      {rate > 0 && (
        <SumRow label={`Tax at ${rate}%`} value={fromPaise(worked.tax)} currency={currency} />
      )}
      <div className="mt-1 flex items-baseline justify-between gap-4 border-t border-[var(--border-strong)] pt-2">
        <dt className="font-semibold">Total</dt>
        <dd>
          <Amount
            value={fromPaise(worked.total)}
            currency={currency}
            className="text-[20px] font-semibold"
          />
        </dd>
      </div>
    </dl>
  );
}

function SumRow({
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
      <dt className="text-[var(--text-muted)]">{label}</dt>
      <dd>
        <Amount value={value} currency={currency} />
      </dd>
    </div>
  );
}

function MoneyField({
  label,
  name,
  value,
  error,
  onChange,
}: {
  label: string;
  name: string;
  value: string;
  error?: string;
  onChange: (value: string) => void;
}) {
  const id = useId();
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
          aria-describedby={error ? `${id}-error` : undefined}
          onChange={(event) => onChange(event.target.value)}
          placeholder="0.00"
          className={`${FIELD} pl-7 font-mono font-normal tabular`}
        />
      </span>
      {error && (
        <span id={`${id}-error`} className="font-normal text-[var(--color-state-noshow)]">
          {error}
        </span>
      )}
    </div>
  );
}

const TYPES = Object.entries(TYPE_WORDS) as [ItemType, string][];

function LineRow({
  row,
  index,
  amount,
  currency,
  fields,
  removable,
  onChange,
  onRemove,
}: {
  row: Row;
  index: number;
  amount: number | null;
  currency: string;
  fields: Record<string, string>;
  removable: boolean;
  onChange: (change: Partial<Row>) => void;
  onRemove: () => void;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [asked, setAsked] = useState("");
  const said = row.description.trim();

  useEffect(() => {
    const timer = setTimeout(() => setAsked(said), 200);
    return () => clearTimeout(timer);
  }, [said]);

  const past = useQuery({
    queryKey: ["bill-lines", asked],
    queryFn: () => getPastLines(asked),
    enabled: open,
    staleTime: 60_000,
    retry: false,
  });
  const offers = (past.data ?? []).filter(
    (each) => each.description.toLowerCase() !== said.toLowerCase(),
  );

  const problem = (part: string) => fields[`items.${index}.${part}`];
  const number = index + 1;

  return (
    <li className="@container px-3 py-3 sm:px-4">
      <div className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-2 @xl:grid-cols-[minmax(0,1fr)_9.75rem_4rem_8rem_6.5rem_auto] @xl:items-start">
        <div className="relative">
          <label htmlFor={`${id}-what`} className="sr-only">
            Line {number}, what it is for
          </label>
          <input
            id={`${id}-what`}
            data-line={row.key}
            role="combobox"
            aria-expanded={open && offers.length > 0}
            aria-controls={`${id}-offers`}
            aria-autocomplete="list"
            aria-invalid={Boolean(problem("description"))}
            value={row.description}
            maxLength={120}
            autoComplete="off"
            onFocus={() => setOpen(true)}
            onBlur={() => setTimeout(() => setOpen(false), 150)}
            onKeyDown={(event) => {
              if (event.key === "Escape") setOpen(false);
            }}
            onChange={(event) => {
              setOpen(true);
              onChange({ description: event.target.value });
            }}
            placeholder={number === 1 ? "Consultation, dressing, injection…" : "What it is for"}
            className={FIELD}
          />
          {open && offers.length > 0 && (
            <ul
              id={`${id}-offers`}
              role="listbox"
              aria-label="Charged before"
              className="absolute top-full right-0 left-0 z-20 mt-1 max-h-64 overflow-auto rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface-raised)] py-1 shadow-lg"
            >
              {offers.map((offer) => (
                <li key={offer.description} role="option" aria-selected={false}>
                  <button
                    type="button"
                    onMouseDown={(event) => event.preventDefault()}
                    onClick={() => {
                      setOpen(false);
                      onChange({
                        description: offer.description,
                        item_type: offer.item_type,
                        price: offer.unit_price,
                      });
                    }}
                    className="flex w-full items-baseline justify-between gap-3 px-3 py-2 text-left text-[14px] hover:bg-[var(--surface-sunken)]"
                  >
                    <span className="min-w-0 truncate">{offer.description}</span>
                    <Amount
                      value={offer.unit_price}
                      currency={currency}
                      className="shrink-0 text-[13px] text-[var(--text-muted)]"
                    />
                  </button>
                </li>
              ))}
            </ul>
          )}
          {problem("description") && (
            <p className="mt-1 text-[13px] text-[var(--color-state-noshow)]">
              {problem("description")}
            </p>
          )}
        </div>

        <div className="col-span-2 grid grid-cols-[minmax(0,1fr)_3.25rem_6.75rem] gap-2 @xl:contents">
          <label className="flex flex-col gap-1 text-[12px] text-[var(--text-muted)] @xl:gap-0">
            <span className="@xl:sr-only">Kind</span>
            <select
              aria-label={`Line ${number}, kind`}
              value={row.item_type}
              onChange={(event) => onChange({ item_type: event.target.value as ItemType })}
              className={`${FIELD} px-2 text-[14px] @xl:px-3`}
            >
              {TYPES.map(([value, words]) => (
                <option key={value} value={value}>
                  {words}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[12px] text-[var(--text-muted)] @xl:gap-0">
            <span className="@xl:sr-only">Qty</span>
            <input
              aria-label={`Line ${number}, how many`}
              value={row.count}
              inputMode="numeric"
              aria-invalid={Boolean(problem("quantity"))}
              onChange={(event) => onChange({ count: event.target.value.replace(/\D/g, "") })}
              className={`${FIELD} px-1 text-center font-mono tabular`}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12px] text-[var(--text-muted)] @xl:gap-0">
            <span className="@xl:sr-only">Rate</span>
            <span className="relative">
              <span
                aria-hidden
                className="pointer-events-none absolute top-1/2 left-2.5 -translate-y-1/2 text-[var(--text-subtle)]"
              >
                ₹
              </span>
              <input
                aria-label={`Line ${number}, rate`}
                value={row.price}
                inputMode="decimal"
                autoComplete="off"
                aria-invalid={Boolean(problem("unit_price"))}
                onChange={(event) => onChange({ price: event.target.value })}
                placeholder="0.00"
                className={`${FIELD} pl-6 text-right font-mono tabular`}
              />
            </span>
          </label>
        </div>

        <div className="col-span-2 flex items-center justify-between gap-2 @xl:contents">
          <span className="text-[13px] text-[var(--text-muted)] @xl:sr-only">Amount</span>
          <span
            className="text-right text-[15px] @xl:pt-2"
            aria-label={`Line ${number} comes to`}
          >
            {amount === null ? (
              <span className="text-[var(--text-subtle)]">—</span>
            ) : (
              <Amount value={fromPaise(amount)} currency={currency} />
            )}
          </span>
        </div>

        <button
          type="button"
          onClick={onRemove}
          disabled={!removable}
          aria-label={`Take line ${number} off`}
          title="Take this line off"
          className="col-start-2 row-start-1 grid size-9 place-items-center rounded-[var(--radius-field)] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)] disabled:invisible @xl:col-start-auto @xl:row-start-auto"
        >
          <X className="size-4" />
        </button>
      </div>
      {(problem("unit_price") || problem("quantity")) && (
        <p className="mt-1 text-[13px] text-[var(--color-state-noshow)]">
          {problem("unit_price") ?? `How many: ${problem("quantity")}`}
        </p>
      )}
    </li>
  );
}
