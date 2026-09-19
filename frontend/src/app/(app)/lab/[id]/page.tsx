"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  Eye,
  Loader2,
  NotebookPen,
  Pencil,
} from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";
import { FlaggedCount, LabStatusChip, ResultTable, Urgent } from "@/components/labs/parts";
import { ResultForm } from "@/components/labs/result-form";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { ApiFailure } from "@/lib/api";
import { shortDate, whenItHappened } from "@/lib/appointments";
import { currentSession } from "@/lib/auth";
import {
  cancelLabOrder,
  clearResult,
  getLabOrder,
  listLabOrders,
  removeLabOrder,
  reviewResult,
  type LabOrder,
} from "@/lib/labs";

export default function LabOrderPage() {
  return (
    <Permitted permission="lab:read">
      <Order />
    </Permitted>
  );
}

function Order() {
  const id = String(useParams().id);
  const queries = useQueryClient();
  const found = useQuery({
    queryKey: ["lab-order", id],
    queryFn: () => getLabOrder(id),
    retry: false,
  });

  if (found.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Opening the order…</span>
      </div>
    );
  }

  if (found.isError) {
    const error = found.error instanceof ApiFailure ? found.error : null;
    const missing = error?.code === "LAB_NOT_FOUND" || error?.status === 422;
    return (
      <Page
        title={missing ? "No such lab order" : "The order did not load"}
        back={{ href: "/lab", label: "Back to the lab list" }}
      >
        <p className="max-w-[54ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
          {missing
            ? "This order does not exist at your clinic. It may have been taken back by the doctor, or opened from an old link."
            : "Something went wrong reaching the server. Try again in a moment."}
        </p>
      </Page>
    );
  }

  const order = found.data;
  // Whatever changed here changes the lists, the patient's record and the
  // doctor's first page too.
  const changed = (next: LabOrder) => {
    queries.setQueryData(["lab-order", id], next);
    for (const key of ["lab-orders", "dashboard"])
      void queries.invalidateQueries({ queryKey: [key] });
  };

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6 lg:py-12">
      <Link
        href="/lab"
        className="mb-5 inline-flex items-center gap-1.5 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
      >
        <ArrowLeft className="size-3.5" />
        Back to the lab list
      </Link>
      <Heading order={order} />
      <div className="mt-6 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_15rem]">
        <div className="flex min-w-0 flex-col gap-6">
          <Report order={order} onChanged={changed} />
        </div>
        <Aside order={order} />
      </div>
    </div>
  );
}

function Heading({ order }: { order: LabOrder }) {
  const patient = order.patient;
  const facts = [patient.age, genderWord(patient.gender), patient.patient_number].filter(
    Boolean,
  );
  return (
    <header className="flex flex-col gap-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[26px] leading-tight font-semibold tracking-tight break-words">
            {order.test_name}
          </h1>
          <p className="mt-1 text-[14px] text-[var(--text-muted)]">
            <span className="font-mono tabular">{order.order_number}</span>, ordered by{" "}
            {order.doctor.display_name} on {shortDate(order.visit_date)}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {order.urgent && <Urgent />}
          <LabStatusChip status={order.status} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
        <Link
          href={`/patients/${patient.id}` as Route}
          className="text-[16px] font-semibold underline-offset-4 hover:underline"
        >
          {patient.full_name}
        </Link>
        <span className="text-[14px] text-[var(--text-muted)] tabular">{facts.join(", ")}</span>
        {patient.allergy_count > 0 && (
          <span className="inline-flex items-center gap-1 text-[13px] font-medium text-[var(--color-state-noshow)]">
            <AlertTriangle className="size-3.5" />
            {patient.allergy_count === 1 ? "1 allergy" : `${patient.allergy_count} allergies`}
          </span>
        )}
      </div>
      {order.instructions && (
        <p className="text-[14px]">
          <span className="text-[var(--text-muted)]">Before the test: </span>
          {order.instructions}
        </p>
      )}
    </header>
  );
}

function genderWord(gender: string | null): string | null {
  if (!gender) return null;
  return { male: "Male", female: "Female", other: "Other" }[gender] ?? gender;
}

function Report({
  order,
  onChanged,
}: {
  order: LabOrder;
  onChanged: (order: LabOrder) => void;
}) {
  const [correcting, setCorrecting] = useState(false);

  if (order.status === "cancelled") {
    return (
      <section className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-5 py-4">
        <h2 className="text-[15px] font-semibold">Cancelled</h2>
        <p className="mt-1 text-[15px]">{order.cancel_reason}</p>
        <p className="mt-1 text-[13px] text-[var(--text-muted)]">
          {order.cancelled_by ?? "Somebody"}
          {order.cancelled_at ? `, ${whenItHappened(order.cancelled_at)}` : ""}
        </p>
      </section>
    );
  }

  if (order.status === "ordered" || correcting) {
    if (!order.can_enter) {
      return (
        <>
          <section className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-5 py-6 text-center">
            <p className="text-[15px] text-[var(--text-muted)]">
              Waiting for the report. The desk types it in when it comes back.
            </p>
          </section>
          <TakeBack order={order} onChanged={onChanged} />
        </>
      );
    }
    return (
      <>
        <section
          aria-labelledby="report-title"
          className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-5"
        >
          <h2 id="report-title" className="mb-4 text-[17px] font-semibold">
            {correcting ? "Put the report right" : "Type in the report"}
          </h2>
          <ResultForm
            // A fresh form each time, so what was typed before a save is not
            // carried into the next correction.
            key={`${order.id}-${order.resulted_at ?? "new"}-${correcting}`}
            order={order}
            onSaved={(saved) => {
              setCorrecting(false);
              onChanged(saved);
            }}
            onCancel={correcting ? () => setCorrecting(false) : undefined}
          />
        </section>
        {!correcting && <TakeBack order={order} onChanged={onChanged} />}
      </>
    );
  }

  return (
    <>
      <section
        aria-labelledby="report-title"
        className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
      >
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <h2 id="report-title" className="text-[17px] font-semibold">
            Report of {order.reported_on ? shortDate(order.reported_on) : ""}
          </h2>
          <span className="flex items-center gap-3">
            <FlaggedCount count={order.flagged} />
            {order.lab_name && (
              <span className="text-[13px] text-[var(--text-muted)]">{order.lab_name}</span>
            )}
          </span>
        </div>
        <ResultTable values={order.values} />
        {order.findings && (
          <p
            className={`max-w-[75ch] text-[15px] leading-relaxed break-words whitespace-pre-wrap ${
              order.values.length ? "mt-4 border-t border-[var(--border)] pt-3" : ""
            }`}
          >
            {order.findings}
          </p>
        )}
        <p className="mt-4 text-[12px] text-[var(--text-muted)]">
          Typed in by {order.resulted_by ?? "somebody"}
          {order.resulted_at ? `, ${whenItHappened(order.resulted_at)}` : ""}
          {order.changed_by ? `. Last put right by ${order.changed_by}.` : "."}
          {order.reviewed_at &&
            ` Seen by ${order.reviewed_by ?? "the doctor"}, ${whenItHappened(order.reviewed_at)}.`}
        </p>
      </section>
      <ReportActions
        order={order}
        onChanged={onChanged}
        onCorrect={() => setCorrecting(true)}
      />
    </>
  );
}

function ReportActions({
  order,
  onChanged,
  onCorrect,
}: {
  order: LabOrder;
  onChanged: (order: LabOrder) => void;
  onCorrect: () => void;
}) {
  const [clearing, setClearing] = useState(false);
  const review = useMutation({
    mutationFn: () => reviewResult(order.id),
    onSuccess: onChanged,
  });
  const clear = useMutation({
    mutationFn: () => clearResult(order.id),
    onSuccess: (next) => {
      setClearing(false);
      onChanged(next);
    },
  });
  const failure = review.error ?? clear.error;

  if (!order.can_review && !order.can_enter) {
    return order.status === "resulted" ? (
      <p className="text-[14px] text-[var(--text-muted)]">
        Waiting for {order.doctor.display_name} to look at it.
      </p>
    ) : null;
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        {order.can_review && (
          <button
            type="button"
            onClick={() => review.mutate()}
            disabled={review.isPending}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2.5 text-[15px] font-semibold text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-60"
          >
            {review.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Eye className="size-4" />
            )}
            Mark as seen
          </button>
        )}
        {order.can_enter && (
          <button
            type="button"
            onClick={onCorrect}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
          >
            <Pencil className="size-4" />
            Put the report right
          </button>
        )}
        {order.can_enter && !clearing && (
          <button
            type="button"
            onClick={() => setClearing(true)}
            className="rounded-[var(--radius-field)] px-3.5 py-2 text-[14px] text-[var(--text-muted)] underline-offset-4 transition-colors hover:text-[var(--text)] hover:underline"
          >
            Typed against the wrong test?
          </button>
        )}
      </div>
      {order.can_review && (
        <p className="text-[13px] text-[var(--text-muted)]">
          Once you mark it as seen, the report stays as it is.
        </p>
      )}
      {clearing && (
        <div
          role="alert"
          className="rounded-[var(--radius-field)] border border-[color-mix(in_srgb,var(--color-state-noshow)_45%,transparent)] bg-[color-mix(in_srgb,var(--color-state-noshow)_8%,transparent)] px-4 py-3 text-[14px]"
        >
          <p className="font-medium">Take this report off the order?</p>
          <p className="mt-1 text-[var(--text-muted)]">
            The order goes back to waiting for its report, and what was typed in is removed.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              autoFocus
              onClick={() => clear.mutate()}
              disabled={clear.isPending}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--color-state-noshow)] px-3.5 py-2 text-[14px] font-semibold text-white hover:brightness-110 disabled:opacity-60"
            >
              {clear.isPending && <Loader2 className="size-4 animate-spin" />}
              Yes, take it off
            </button>
            <button
              type="button"
              onClick={() => setClearing(false)}
              className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] hover:bg-[var(--surface-sunken)]"
            >
              Keep it
            </button>
          </div>
        </div>
      )}
      {failure && (
        <p role="alert" className="text-[14px] text-[var(--color-state-noshow)]">
          {failure instanceof ApiFailure
            ? failure.message
            : "That did not go through. Try again in a moment."}
        </p>
      )}
    </div>
  );
}

/** Calling a test off, or taking it back while the patient is still in the room. */
function TakeBack({
  order,
  onChanged,
}: {
  order: LabOrder;
  onChanged: (order: LabOrder) => void;
}) {
  const router = useRouter();
  const queries = useQueryClient();
  const [asking, setAsking] = useState(false);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const cancel = useMutation({
    mutationFn: () => cancelLabOrder(order.id, reason.trim()),
    onSuccess: (next) => {
      setAsking(false);
      onChanged(next);
    },
    onError: (error) =>
      setProblem(
        error instanceof ApiFailure ? error.message : "That did not go through. Try again.",
      ),
  });
  const remove = useMutation({
    mutationFn: () => removeLabOrder(order.id),
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: ["lab-orders"] });
      router.replace(`/consultations/${order.consultation_id}` as Route);
    },
    onError: (error) =>
      setProblem(
        error instanceof ApiFailure ? error.message : "That did not go through. Try again.",
      ),
  });

  if (order.can_remove) {
    return (
      <div className="flex flex-col gap-2">
        <button
          type="button"
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          className="w-fit rounded-[var(--radius-field)] px-0 text-[14px] text-[var(--text-muted)] underline underline-offset-4 hover:text-[var(--text)]"
        >
          {remove.isPending ? "Taking it back…" : "Take this test back"}
        </button>
        {problem && (
          <p role="alert" className="text-[14px] text-[var(--color-state-noshow)]">
            {problem}
          </p>
        )}
      </div>
    );
  }
  if (!order.can_cancel) return null;

  return asking ? (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (!reason.trim()) {
          setProblem("Say why it is not being done.");
          return;
        }
        if (!cancel.isPending) cancel.mutate();
      }}
      className="flex flex-col gap-2 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
    >
      <label htmlFor="cancel-reason" className="text-[14px] font-medium">
        Why is it not being done?
      </label>
      <input
        id="cancel-reason"
        autoFocus
        value={reason}
        maxLength={200}
        placeholder="Had it done elsewhere last week"
        onChange={(event) => {
          setReason(event.target.value);
          setProblem(null);
        }}
        aria-invalid={Boolean(problem)}
        className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] outline-none focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)] aria-invalid:border-[var(--color-state-noshow)]"
      />
      {problem && (
        <p role="alert" className="text-[13px] text-[var(--color-state-noshow)]">
          {problem}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={cancel.isPending}
          className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--color-state-noshow)] px-3.5 py-2 text-[14px] font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {cancel.isPending && <Loader2 className="size-4 animate-spin" />}
          Cancel the test
        </button>
        <button
          type="button"
          onClick={() => {
            setAsking(false);
            setProblem(null);
          }}
          className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] hover:bg-[var(--surface-sunken)]"
        >
          Keep it
        </button>
      </div>
    </form>
  ) : (
    <button
      type="button"
      onClick={() => setAsking(true)}
      className="w-fit text-[14px] text-[var(--text-muted)] underline underline-offset-4 hover:text-[var(--text)]"
    >
      Not being done? Cancel the test
    </button>
  );
}

/** Who asked for it and when, and the rest of the visit's tests to move between. */
function Aside({ order }: { order: LabOrder }) {
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const mayReadNotes = session.data?.permissions.includes("consultation:read") ?? false;
  const siblings = useQuery({
    queryKey: ["lab-orders", "visit", order.consultation_id],
    queryFn: () => listLabOrders({ visit: order.consultation_id, limit: 100 }),
    retry: false,
  });
  const others = (siblings.data?.items ?? []).filter((each) => each.id !== order.id);

  return (
    <aside className="flex flex-col gap-5 lg:sticky lg:top-6 lg:self-start">
      <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-[14px]">
        <dt className="text-[var(--text-muted)]">Ordered</dt>
        <dd>{whenItHappened(order.ordered_at)}</dd>
        {order.ordered_by && (
          <>
            <dt className="text-[var(--text-muted)]">By</dt>
            <dd>{order.ordered_by}</dd>
          </>
        )}
      </dl>
      {mayReadNotes && (
        <Link
          href={`/consultations/${order.consultation_id}` as Route}
          className="inline-flex w-fit items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
        >
          <NotebookPen className="size-4" />
          The visit&apos;s notes
        </Link>
      )}
      {others.length > 0 && (
        <section aria-labelledby="same-visit" className="flex flex-col gap-2">
          <h2 id="same-visit" className="text-[14px] font-semibold">
            Also ordered at this visit
          </h2>
          <ul className="flex flex-col gap-1">
            {others.map((each) => (
              <li key={each.id}>
                <Link
                  href={`/lab/${each.id}` as Route}
                  className="flex items-center justify-between gap-2 rounded-[var(--radius-field)] px-2 py-1.5 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
                >
                  <span className="min-w-0 truncate">{each.test_name}</span>
                  {each.status === "ordered" ? (
                    <span className="shrink-0 text-[12px] text-[var(--text-muted)]">
                      waiting
                    </span>
                  ) : each.status === "cancelled" ? (
                    <span className="shrink-0 text-[12px] text-[var(--text-subtle)]">
                      cancelled
                    </span>
                  ) : (
                    <Check
                      aria-label="Report in"
                      className="size-4 shrink-0 text-[var(--color-state-completed)]"
                    />
                  )}
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}
    </aside>
  );
}
