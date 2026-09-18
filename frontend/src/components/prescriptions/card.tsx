"use client";

import { useMutation } from "@tanstack/react-query";
import { Loader2, Pencil, Printer } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useState } from "react";
import {
  editable,
  PrescriptionLines,
  problemsByRow,
  sendable,
  type EditableLine,
} from "@/components/prescriptions/lines";
import { ApiFailure } from "@/lib/api";
import { shortDate, whenItHappened } from "@/lib/appointments";
import {
  correctPrescription,
  pdfHref,
  spokenDays,
  TIMING_WORDS,
  type Prescription,
  type PrescriptionDetail,
} from "@/lib/prescriptions";

/** The medicines as a table, the way the printed copy lays them out. */
export function MedicineTable({ items }: { items: Prescription["items"] }) {
  if (!items.length) return null;
  return (
    <>
      {/* A phone reads each medicine as a short block rather than scrolling a table. */}
      <ol className="flex flex-col divide-y divide-[var(--border)] border-y border-[var(--border)] sm:hidden">
        {items.map((item, index) => (
          <li key={index} className="flex gap-3 py-2.5">
            <span className="w-4 shrink-0 font-mono text-[12px] leading-6 text-[var(--text-subtle)] tabular">
              {index + 1}
            </span>
            <div className="min-w-0 flex-1 text-[14px]">
              <p className="font-semibold break-words">{item.medicine_name}</p>
              {item.presentation && (
                <p className="text-[13px] text-[var(--text-muted)]">{item.presentation}</p>
              )}
              <p className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5">
                {item.dose && <span className="font-mono tabular">{item.dose}</span>}
                {item.timing && <span>{TIMING_WORDS[item.timing]}</span>}
                {item.duration_days !== null && (
                  <span className="tabular">for {spokenDays(item.duration_days)}</span>
                )}
              </p>
              {item.instructions && (
                <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
                  {item.instructions}
                </p>
              )}
            </div>
          </li>
        ))}
      </ol>
      <div className="hidden overflow-x-auto sm:block">
        <table className="w-full min-w-[34rem] border-collapse text-left text-[14px]">
          <thead>
            <tr className="border-b border-[var(--border-strong)] text-[12px] text-[var(--text-muted)]">
              <th scope="col" className="w-8 py-1.5 pr-2 font-normal">
                <span className="sr-only">Number</span>
              </th>
              <th scope="col" className="py-1.5 pr-3 font-normal">
                Medicine
              </th>
              <th scope="col" className="py-1.5 pr-3 font-normal">
                Dose
              </th>
              <th scope="col" className="py-1.5 pr-3 font-normal">
                When
              </th>
              <th scope="col" className="py-1.5 font-normal">
                For
              </th>
            </tr>
          </thead>
          <tbody>
            {items.map((item, index) => (
              <tr key={index} className="border-b border-[var(--border)] align-top">
                <td className="py-2 pr-2 font-mono text-[12px] text-[var(--text-subtle)] tabular">
                  {index + 1}
                </td>
                <td className="py-2 pr-3">
                  <span className="font-semibold break-words">{item.medicine_name}</span>
                  {item.presentation && (
                    <span className="block text-[13px] text-[var(--text-muted)]">
                      {item.presentation}
                    </span>
                  )}
                  {item.instructions && (
                    <span className="block text-[13px] text-[var(--text-muted)]">
                      {item.instructions}
                    </span>
                  )}
                </td>
                <td className="py-2 pr-3 font-mono whitespace-nowrap tabular">{item.dose}</td>
                <td className="py-2 pr-3 whitespace-nowrap">
                  {item.timing ? TIMING_WORDS[item.timing] : ""}
                </td>
                <td className="py-2 whitespace-nowrap tabular">
                  {spokenDays(item.duration_days)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function PrintLink({ id, number }: { id: string; number: string | null }) {
  return (
    <a
      href={pdfHref(id)}
      target="_blank"
      rel="noopener"
      className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-3.5 py-2 text-[14px] font-semibold text-[var(--accent-fg)] transition hover:brightness-105"
    >
      <Printer className="size-4" />
      Print {number ?? "prescription"}
    </a>
  );
}

/**
 * An issued prescription on the notes screen: what the patient was given,
 * a way to print it, and for the doctor who wrote it, a way to put it right.
 */
export function IssuedPrescription({
  prescription,
  earlier,
  mayCorrect,
  onCorrected,
}: {
  prescription: Prescription;
  earlier: Prescription[];
  mayCorrect: boolean;
  onCorrected: (next: PrescriptionDetail) => void;
}) {
  const [correcting, setCorrecting] = useState(false);
  return (
    <section
      aria-labelledby={`rx-${prescription.id}`}
      className="flex flex-col gap-4 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id={`rx-${prescription.id}`} className="text-[16px] font-semibold">
            Prescription{" "}
            <span className="font-mono text-[15px] font-normal tabular">
              {prescription.number}
            </span>
          </h2>
          <p className="text-[13px] text-[var(--text-muted)]">
            Issued {prescription.issued_at ? whenItHappened(prescription.issued_at) : ""}
            {prescription.replaces &&
              `, in place of ${prescription.replaces.number ?? "an earlier one"}`}
            {prescription.correction_reason && `: ${prescription.correction_reason}`}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {mayCorrect && !correcting && (
            <button
              type="button"
              onClick={() => setCorrecting(true)}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
            >
              <Pencil className="size-4" />
              Correct it
            </button>
          )}
          <PrintLink id={prescription.id} number={prescription.number} />
        </div>
      </div>

      {correcting ? (
        <CorrectionForm
          prescription={prescription}
          onCancel={() => setCorrecting(false)}
          onDone={(next) => {
            setCorrecting(false);
            onCorrected(next);
          }}
        />
      ) : (
        <>
          <MedicineTable items={prescription.items} />
          {prescription.instructions && (
            <div>
              <p className="text-[12px] text-[var(--text-muted)]">Advice on the prescription</p>
              <p className="max-w-[75ch] text-[15px] leading-relaxed whitespace-pre-wrap">
                {prescription.instructions}
              </p>
            </div>
          )}
          {prescription.follow_up_date && (
            <p className="text-[14px]">
              Printed with a follow-up on{" "}
              <strong className="font-semibold">
                {shortDate(prescription.follow_up_date)}
              </strong>
              .
            </p>
          )}
        </>
      )}

      {earlier.length > 0 && (
        <div className="border-t border-[var(--border)] pt-3">
          <p className="text-[12px] text-[var(--text-muted)]">Replaced</p>
          <ul className="mt-1 flex flex-col gap-1 text-[14px]">
            {earlier.map((old) => (
              <li key={old.id}>
                <Link
                  href={`/prescriptions/${old.id}` as Route}
                  className="font-mono underline underline-offset-2 tabular"
                >
                  {old.number}
                </Link>
                <span className="text-[var(--text-muted)]">
                  , issued {old.issued_at ? whenItHappened(old.issued_at) : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function CorrectionForm({
  prescription,
  onCancel,
  onDone,
}: {
  prescription: Prescription;
  onCancel: () => void;
  onDone: (next: PrescriptionDetail) => void;
}) {
  const [lines, setLines] = useState<EditableLine[]>(() => editable(prescription.items));
  const [instructions, setInstructions] = useState(prescription.instructions ?? "");
  const [reason, setReason] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);

  const send = useMutation({
    mutationFn: () =>
      correctPrescription(prescription.id, {
        medicines: sendable(lines),
        instructions: instructions.trim() || null,
        reason: reason.trim(),
      }),
    onSuccess: onDone,
    onError: (error) => {
      if (error instanceof ApiFailure) {
        setFields(error.fields ?? {});
        setProblem(error.message);
      } else {
        setProblem("That did not go through. Try again in a moment.");
      }
    },
  });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setFields({});
        if (!sendable(lines).length) {
          setProblem("A corrected prescription needs at least one medicine.");
          return;
        }
        if (!reason.trim()) {
          setProblem("Say what was wrong with the original.");
          return;
        }
        setProblem(null);
        if (!send.isPending) send.mutate();
      }}
      className="flex flex-col gap-4"
    >
      <p className="max-w-[65ch] text-[14px] text-[var(--text-muted)]">
        This issues a new prescription with its own number. {prescription.number} stays on
        record, marked as replaced, in case a copy of it turns up at a pharmacy.
      </p>
      <PrescriptionLines
        lines={lines}
        onChange={setLines}
        problems={problemsByRow(lines, fields)}
        disabled={send.isPending}
      />
      <label className="flex flex-col gap-1">
        <span className="text-[13px] font-medium">Advice on the prescription</span>
        <textarea
          value={instructions}
          maxLength={2000}
          rows={2}
          disabled={send.isPending}
          onChange={(event) => setInstructions(event.target.value)}
          className="w-full max-w-[75ch] resize-y rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] outline-none [field-sizing:content] focus:border-[var(--focus-ring)]"
        />
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-[13px] font-medium">What was wrong with the original</span>
        <input
          value={reason}
          maxLength={200}
          disabled={send.isPending}
          placeholder="Wrong strength written for paracetamol"
          aria-invalid={Boolean(fields.reason)}
          onChange={(event) => setReason(event.target.value)}
          className="w-full max-w-[60ch] rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] outline-none focus:border-[var(--focus-ring)]"
        />
      </label>
      {problem && (
        <p role="alert" className="text-[14px] text-[var(--color-state-noshow)]">
          {problem}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={send.isPending}
          className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-3.5 py-2 text-[14px] font-semibold text-[var(--primary-fg)] hover:brightness-110 disabled:opacity-60"
        >
          {send.isPending && <Loader2 className="size-4 animate-spin" />}
          Issue the correction
        </button>
        <button
          type="button"
          onClick={onCancel}
          disabled={send.isPending}
          className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] hover:bg-[var(--surface-sunken)]"
        >
          Keep the original
        </button>
      </div>
    </form>
  );
}
