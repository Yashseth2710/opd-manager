"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarPlus,
  Check,
  ChevronDown,
  CloudOff,
  Loader2,
  Lock,
  Plus,
  Star,
  X,
} from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { VisitTests } from "@/components/labs/visit-tests";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { IssuedPrescription, MedicineTable } from "@/components/prescriptions/card";
import {
  editable,
  PrescriptionLines,
  problemsByRow,
  sendable,
  type EditableLine,
} from "@/components/prescriptions/lines";
import { Token } from "@/components/queue/token";
import { VisitVitals } from "@/components/vitals/visit-vitals";
import { ApiFailure } from "@/lib/api";
import { bookingHref, shortDate, whenItHappened } from "@/lib/appointments";
import { currentSession } from "@/lib/auth";
import {
  addAddendum,
  DIAGNOSIS_LIMIT,
  daysAfter,
  daysBetween,
  FOLLOW_UP_CHOICES,
  finishNotes,
  getConsultation,
  listConsultations,
  saveNotes,
  SECTION_LIMITS,
  TEXT_SECTIONS,
  type Consultation,
  type ConsultationSummary,
  type Diagnosis,
  type NoteChanges,
  type TextSection,
} from "@/lib/consultations";
import { todayISO } from "@/lib/doctors";
import { getPatient, type Allergy } from "@/lib/patients";

export default function ConsultationPage() {
  return (
    <Permitted permission="consultation:read">
      <Notes />
    </Permitted>
  );
}

const SECTION_WORDS: Record<TextSection, { title: string; hint: string }> = {
  chief_complaint: {
    title: "Complaint",
    hint: "What brought them in, in their words.",
  },
  history: {
    title: "History",
    hint: "How it started and how it has gone, and anything relevant from before.",
  },
  examination: {
    title: "Examination",
    hint: "What you found.",
  },
  advice: {
    title: "Advice and plan",
    hint: "What you told them to do, and what happens next.",
  },
};

// A pause this long in typing is taken as a moment to save.
const SAVE_AFTER_MS = 900;
const RETRY_AFTER_MS = 5_000;

function Notes() {
  const id = String(useParams().id);
  const queries = useQueryClient();
  // Bumped to throw away what is on screen and start again from the server.
  const [generation, setGeneration] = useState(0);

  const notes = useQuery({
    queryKey: ["consultation", id],
    queryFn: () => getConsultation(id),
    retry: false,
    // A refetch while somebody is typing would be ignored by the editor
    // anyway, and would make a finished-elsewhere check look like a reload.
    refetchOnWindowFocus: false,
  });

  if (notes.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Opening the notes…</span>
      </div>
    );
  }

  if (notes.isError) {
    const error = notes.error instanceof ApiFailure ? notes.error : null;
    // An address that is not an id at all is as missing as one that matches nothing.
    const missing = error?.code === "CONSULT_NOT_FOUND" || error?.status === 422;
    const title = missing
      ? "No such notes"
      : error?.code === "CONSULT_NOT_OWNER"
        ? "Not yours to read"
        : "The notes did not load";
    const words = missing
      ? "These notes do not exist at your clinic. They may have been opened from an old link."
      : error?.code === "CONSULT_NOT_OWNER"
        ? error.message
        : "Something went wrong reaching the server. Try again in a moment.";
    return (
      <Page title={title} back={{ href: "/consultations", label: "Back to notes" }}>
        <p className="max-w-[54ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
          {words}
        </p>
      </Page>
    );
  }

  const record = notes.data;
  const reload = async () => {
    await queries.refetchQueries({ queryKey: ["consultation", id], exact: true });
    setGeneration((value) => value + 1);
  };

  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:py-10">
      <BackLink record={record} />
      <PatientBar record={record} />
      <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_19rem]">
        <div className="min-w-0">
          {record.can_edit ? (
            <Editor key={`${record.id}-${generation}`} initial={record} onReload={reload} />
          ) : (
            <Finished record={record} />
          )}
        </div>
        <EarlierVisits record={record} />
      </div>
    </div>
  );
}

function BackLink({ record }: { record: Consultation }) {
  const fromToday = record.visit_date === todayISO() && record.status === "draft";
  return (
    <Link
      href={fromToday ? (`/queue?doctor=${record.doctor.id}` as Route) : "/consultations"}
      className="mb-5 inline-flex items-center gap-1.5 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
    >
      <ArrowLeft className="size-3.5" />
      {fromToday ? "Back to the queue" : "Back to notes"}
    </Link>
  );
}

// --- Who is in front of the doctor ------------------------------------------

function PatientBar({ record }: { record: Consultation }) {
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const patient = useQuery({
    queryKey: ["patient", record.patient.id],
    queryFn: () => getPatient(record.patient.id),
    retry: false,
    enabled: record.patient.allergy_count > 0,
  });
  const facts = [
    record.patient.age,
    record.patient.gender ? genderWord(record.patient.gender) : null,
    record.patient.patient_number,
  ].filter(Boolean);

  return (
    <header className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-3 px-5 py-4">
        {record.token !== null && (
          <Token
            number={record.token}
            status={record.status === "draft" ? "in_consultation" : "completed"}
            size="lg"
          />
        )}
        <div className="min-w-[min(100%,14rem)] flex-1">
          <h1 className="text-[22px] leading-tight font-semibold tracking-tight break-words">
            <Link
              href={`/patients/${record.patient.id}` as Route}
              className="underline-offset-4 hover:underline"
            >
              {record.patient.full_name}
            </Link>
            {record.patient.preferred_name && (
              <span className="ml-2 text-[15px] font-normal text-[var(--text-muted)]">
                goes by {record.patient.preferred_name}
              </span>
            )}
          </h1>
          <p className="mt-0.5 text-[14px] text-[var(--text-muted)] tabular">
            {facts.join(", ")}
          </p>
        </div>
        <div className="flex w-full flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-[var(--text-muted)] sm:w-auto sm:flex-col sm:items-end">
          <StatusChip record={record} />
          <span>
            {record.doctor.display_name}, {shortDate(record.visit_date)}
          </span>
        </div>
      </div>
      <AllergyStrip
        count={record.patient.allergy_count}
        allergies={patient.data?.allergies}
        failed={patient.isError}
      />
      {record.queue_entry_id && session.data?.permissions.includes("vitals:read") && (
        <VisitVitals
          entryId={record.queue_entry_id}
          patientName={record.patient.full_name}
          mayRecord={session.data.permissions.includes("vitals:record")}
          open={record.status === "draft"}
        />
      )}
    </header>
  );
}

function genderWord(gender: string): string {
  return { male: "Male", female: "Female", other: "Other" }[gender] ?? gender;
}

function StatusChip({ record }: { record: Consultation }) {
  const done = record.status === "completed";
  const tone = done ? "var(--color-state-completed)" : "var(--color-state-waiting)";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[12px] font-medium text-[var(--text)]"
      style={{
        borderColor: `color-mix(in srgb, ${tone} 50%, transparent)`,
        background: `color-mix(in srgb, ${tone} 12%, transparent)`,
      }}
    >
      {done ? (
        <Lock className="size-3" />
      ) : (
        <span className="size-1.5 rounded-full" style={{ background: tone }} />
      )}
      {done ? "Finished" : "Draft"}
    </span>
  );
}

const SEVERITY_ORDER = { severe: 0, moderate: 1, mild: 2 } as const;

/**
 * Allergies sit where the doctor cannot miss them, in the one strip of this
 * screen that is coloured for danger. None recorded is said too, quietly,
 * because an empty space reads the same as a list that failed to load.
 */
function AllergyStrip({
  count,
  allergies,
  failed,
}: {
  count: number;
  allergies: Allergy[] | undefined;
  failed: boolean;
}) {
  if (count === 0) {
    return (
      <p className="border-t border-[var(--border)] px-5 py-2.5 text-[13px] text-[var(--text-muted)]">
        No allergies recorded.
      </p>
    );
  }
  const sorted = allergies
    ? [...allergies].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity])
    : null;
  return (
    <div
      role="note"
      aria-label="Allergies"
      className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-t border-[color-mix(in_srgb,var(--color-state-noshow)_35%,transparent)] bg-[color-mix(in_srgb,var(--color-state-noshow)_9%,transparent)] px-5 py-2.5 text-[14px]"
    >
      <span className="inline-flex items-center gap-1.5 font-semibold text-[var(--color-state-noshow)]">
        <AlertTriangle className="size-4" />
        Allergic to
      </span>
      {sorted ? (
        sorted.map((allergy) => (
          <span key={allergy.id} className="inline-flex items-baseline gap-1">
            <span className="font-medium">{allergy.substance}</span>
            <span className="text-[12px] text-[var(--text-muted)]">
              {allergy.severity}
              {allergy.reaction ? `, ${allergy.reaction}` : ""}
            </span>
          </span>
        ))
      ) : (
        <span className="text-[var(--text-muted)]">
          {failed
            ? `${count} recorded. Open the patient's record to see them.`
            : `${count} recorded…`}
        </span>
      )}
    </div>
  );
}

// --- Writing --------------------------------------------------------------------

type Draft = {
  chief_complaint: string;
  history: string;
  examination: string;
  advice: string;
  diagnoses: Diagnosis[];
  follow_up_date: string | null;
  medicines: EditableLine[];
  prescription_instructions: string;
};

function draftOf(record: Consultation): Draft {
  const prescription = record.prescriptions.find((each) => each.status === "draft");
  return {
    medicines: editable(prescription?.items ?? []),
    prescription_instructions: prescription?.instructions ?? "",
    chief_complaint: record.chief_complaint ?? "",
    history: record.history ?? "",
    examination: record.examination ?? "",
    advice: record.advice ?? "",
    diagnoses: record.diagnoses,
    follow_up_date: record.follow_up_date,
  };
}

function sameDiagnoses(a: Diagnosis[], b: Diagnosis[]): boolean {
  return (
    a.length === b.length &&
    a.every((each, index) => {
      const other = b[index];
      return (
        other !== undefined &&
        each.label === other.label &&
        each.is_primary === other.is_primary
      );
    })
  );
}

/** What differs between the screen and the last copy the server has. */
function changesBetween(current: Draft, stored: Draft): NoteChanges {
  const changes: NoteChanges = {};
  for (const section of TEXT_SECTIONS) {
    // Whitespace at the ends is trimmed by the server, so it is not a change
    // worth a save of its own.
    if (current[section].trim() !== stored[section].trim()) changes[section] = current[section];
  }
  if (!sameDiagnoses(current.diagnoses, stored.diagnoses))
    changes.diagnoses = current.diagnoses;
  if (current.follow_up_date !== stored.follow_up_date)
    changes.follow_up_date = current.follow_up_date;
  const lines = sendable(current.medicines);
  if (JSON.stringify(lines) !== JSON.stringify(sendable(stored.medicines)))
    changes.medicines = lines;
  if (current.prescription_instructions.trim() !== stored.prescription_instructions.trim())
    changes.prescription_instructions = current.prescription_instructions;
  return changes;
}

type SaveState =
  | { kind: "saved"; at: string }
  | { kind: "unsaved" }
  | { kind: "saving" }
  | { kind: "offline" }
  | { kind: "signed-out" }
  | { kind: "refused"; message: string }
  | { kind: "conflict" }
  | { kind: "gone"; message: string };

function Editor({
  initial,
  onReload,
}: {
  initial: Consultation;
  onReload: () => Promise<void>;
}) {
  const queries = useQueryClient();
  const id = initial.id;
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const mayBook = session.data?.permissions.includes("appointment:create") ?? false;
  const mayOrder = session.data?.permissions.includes("lab:create") ?? false;

  const [draft, setDraft] = useState<Draft>(() => draftOf(initial));
  const [state, setState] = useState<SaveState>({ kind: "saved", at: initial.updated_at });
  const [fields, setFields] = useState<Record<string, string>>({});
  const [confirming, setConfirming] = useState(false);
  const [finishProblem, setFinishProblem] = useState<string | null>(null);

  const stored = useRef<Draft>(draftOf(initial));
  const version = useRef(initial.version);
  const savedAt = useRef(initial.updated_at);
  const latest = useRef(draft);
  const inFlight = useRef<Promise<boolean> | null>(null);
  const stuck = useRef(false);

  useEffect(() => {
    latest.current = draft;
  }, [draft]);

  const flush = useCallback(async (): Promise<boolean> => {
    // One save at a time: the next one has to name the version the last one
    // produced.
    while (inFlight.current) await inFlight.current;
    if (stuck.current) return false;
    const snapshot = latest.current;
    const changes = changesBetween(snapshot, stored.current);
    if (Object.keys(changes).length === 0) return true;

    setState({ kind: "saving" });
    const attempt = (async () => {
      try {
        const next = await saveNotes(id, version.current, changes);
        version.current = next.version;
        savedAt.current = next.updated_at;
        stored.current = { ...stored.current, ...pickSent(snapshot, changes) };
        queries.setQueryData(["consultation", id], next);
        setFields({});
        const more = Object.keys(changesBetween(latest.current, stored.current)).length > 0;
        setState(more ? { kind: "unsaved" } : { kind: "saved", at: next.updated_at });
        return true;
      } catch (error) {
        if (!(error instanceof ApiFailure) || error.status === 0 || error.status >= 500) {
          setState({ kind: "offline" });
        } else if (error.code === "CONSULT_EDITED_ELSEWHERE") {
          stuck.current = true;
          setState({ kind: "conflict" });
        } else if (error.code === "CONSULT_ALREADY_COMPLETED") {
          stuck.current = true;
          setState({
            kind: "gone",
            message:
              "These notes were finished in another window, so this copy can no longer be saved.",
          });
        } else if (error.fields) {
          setFields(error.fields);
          setState({
            kind: "refused",
            message: Object.values(error.fields)[0] ?? error.message,
          });
        } else if (error.status === 401) {
          setState({ kind: "signed-out" });
        } else {
          stuck.current = true;
          setState({ kind: "gone", message: error.message });
        }
        return false;
      }
    })();
    inFlight.current = attempt;
    try {
      return await attempt;
    } finally {
      inFlight.current = null;
    }
  }, [id, queries]);

  // Saves a moment after the typing stops.
  useEffect(() => {
    if (Object.keys(changesBetween(draft, stored.current)).length === 0) return;
    const timer = setTimeout(() => void flush(), SAVE_AFTER_MS);
    return () => clearTimeout(timer);
  }, [draft, flush]);

  // Keeps trying while the connection is down, without waiting for a keystroke.
  useEffect(() => {
    if (state.kind !== "offline" && state.kind !== "signed-out") return;
    const timer = setTimeout(() => void flush(), RETRY_AFTER_MS);
    return () => clearTimeout(timer);
  }, [state, flush]);

  // Leaving with unsaved words gets the browser's own warning. Moving within
  // the app saves on the way out instead.
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      const unsaved =
        inFlight.current !== null ||
        Object.keys(changesBetween(latest.current, stored.current)).length > 0;
      if (unsaved) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => {
      window.removeEventListener("beforeunload", warn);
      void flush();
    };
  }, [flush]);

  // Ctrl+S or Cmd+S saves now rather than opening the browser's save dialog.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
        event.preventDefault();
        void flush();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [flush]);

  const finish = useMutation({
    mutationFn: async () => {
      if (!(await flush())) throw new Error("unsaved");
      return finishNotes(id, version.current);
    },
    onSuccess: (done) => {
      setConfirming(false);
      queries.setQueryData(["consultation", id], done);
      for (const key of [
        "queue",
        "consultations",
        "appointments",
        "appointment",
        "patient-appointments",
        // Finishing the visit closes its readings to correction.
        "vitals",
        // And turns taking a test back into cancelling it.
        "lab-orders",
      ])
        void queries.invalidateQueries({ queryKey: [key] });
    },
    onError: (error) => {
      setConfirming(false);
      if (error instanceof ApiFailure) {
        // The sentence says what stopped it; the fields point at where.
        setFinishProblem(error.message);
        if (error.fields) setFields(error.fields);
      } else {
        setFinishProblem(
          "The latest changes are not saved yet, so the notes were not finished.",
        );
      }
    },
  });

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setFinishProblem(null);
    const next = { ...latest.current, [key]: value };
    latest.current = next;
    setDraft(next);
    // Said at once rather than after the pause that sets a save off, so the
    // screen never claims to be saved while it holds words the server has
    // not seen. Typing something back the way it was is saved again.
    const pending = Object.keys(changesBetween(next, stored.current)).length > 0;
    setState((current) =>
      current.kind === "saved" || current.kind === "unsaved" || current.kind === "refused"
        ? pending
          ? { kind: "unsaved" }
          : { kind: "saved", at: savedAt.current }
        : current,
    );
  };

  const locked = state.kind === "conflict" || state.kind === "gone";

  return (
    <div className="flex flex-col gap-7">
      {/* Stays in view down a long note, so saving and finishing are never a scroll away. */}
      {/* Anything that needs the doctor's attention lives here too, rather than at
          the top of a page they may be far down. */}
      <div className="sticky top-0 z-10 -mx-2 flex flex-col gap-3 border-b border-[var(--border)] bg-[var(--background)] px-2 py-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <SaveStatus state={state} />
          <button
            type="button"
            onClick={() => {
              setFinishProblem(null);
              setConfirming(true);
            }}
            disabled={locked || finish.isPending}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2.5 text-[15px] font-semibold text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-60"
          >
            <Check className="size-4" />
            Finish visit
          </button>
        </div>

        {state.kind === "conflict" && (
          <Banner tone="var(--color-state-waiting)">
            <p>
              These notes were changed in another window, so this one has stopped saving.
              Loading the latest replaces what is on this screen, so copy anything you still
              need first.
            </p>
            <button
              type="button"
              onClick={() => void onReload()}
              className="mt-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-1.5 text-[13px] font-medium hover:bg-[var(--surface-sunken)]"
            >
              Load the latest
            </button>
          </Banner>
        )}
        {state.kind === "gone" && (
          <Banner tone="var(--color-state-noshow)">
            <p>{state.message}</p>
            <button
              type="button"
              onClick={() => void onReload()}
              className="mt-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-1.5 text-[13px] font-medium hover:bg-[var(--surface-sunken)]"
            >
              Show the notes as they are
            </button>
          </Banner>
        )}

        {confirming && (
          <Banner tone="var(--color-state-consulting)">
            <p className="font-medium">Finish this visit and lock the notes?</p>
            <p className="mt-1 text-[var(--text-muted)]">
              {initial.token !== null ? `Token ${initial.token} will be marked as seen. ` : ""}
              Anything you think of later can still be added underneath as an addendum.
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <button
                type="button"
                autoFocus
                onClick={() => finish.mutate()}
                disabled={finish.isPending}
                className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-3.5 py-2 text-[14px] font-semibold text-[var(--primary-fg)] hover:brightness-110 disabled:opacity-60"
              >
                {finish.isPending && <Loader2 className="size-4 animate-spin" />}
                Yes, finish
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={finish.isPending}
                className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] hover:bg-[var(--surface-sunken)]"
              >
                Keep writing
              </button>
            </div>
          </Banner>
        )}
        {finishProblem && (
          <p role="alert" className="text-[14px] text-[var(--color-state-noshow)]">
            {finishProblem}
          </p>
        )}
      </div>

      <fieldset disabled={locked || finish.isPending} className="flex min-w-0 flex-col gap-7">
        <legend className="sr-only">Consultation notes</legend>
        {(["chief_complaint", "history", "examination"] as const).map((section) => (
          <Section
            key={section}
            section={section}
            value={draft[section]}
            error={fields[section]}
            onChange={(value) => set(section, value)}
            onBlur={() => void flush()}
          />
        ))}
        <DiagnosisField
          diagnoses={draft.diagnoses}
          error={
            fields.diagnoses ??
            Object.entries(fields).find(([key]) => key.startsWith("diagnoses."))?.[1]
          }
          onChange={(value) => set("diagnoses", value)}
        />
        {mayOrder && (
          <VisitTests visitId={initial.id} canOrder disabled={locked || finish.isPending} />
        )}
        <Section
          section="advice"
          value={draft.advice}
          error={fields.advice}
          onChange={(value) => set("advice", value)}
          onBlur={() => void flush()}
        />
        <section aria-labelledby="notes-prescription" className="flex flex-col gap-3">
          <div>
            <h2 id="notes-prescription" className="text-[15px] font-semibold">
              Prescription
            </h2>
            <p className="text-[13px] text-[var(--text-muted)]">
              Issued with its own number when the visit is finished, and printable from then.
            </p>
          </div>
          <PrescriptionLines
            lines={draft.medicines}
            onChange={(value) => set("medicines", value)}
            problems={problemsByRow(draft.medicines, fields)}
          />
          <div className="flex flex-col gap-1.5">
            <label htmlFor="notes-rx-advice" className="text-[14px] font-medium">
              Advice printed on the prescription
            </label>
            <textarea
              id="notes-rx-advice"
              value={draft.prescription_instructions}
              maxLength={2000}
              rows={2}
              placeholder="Plenty of fluids. Come back sooner if the fever does not settle."
              onChange={(event) => set("prescription_instructions", event.target.value)}
              onBlur={() => void flush()}
              className={`${FIELD_CLASS} max-w-[75ch] min-h-[4rem] resize-y [field-sizing:content]`}
            />
          </div>
        </section>
        <FollowUpField
          visit={initial.visit_date}
          value={draft.follow_up_date}
          error={fields.follow_up_date}
          onChange={(value) => set("follow_up_date", value)}
        />
      </fieldset>

      {draft.follow_up_date && !fields.follow_up_date && mayBook && (
        <p className="text-[13px] text-[var(--text-muted)]">
          The follow-up can be booked once the visit is finished, or now from the{" "}
          <Link
            href={
              bookingHref({
                patient: initial.patient.id,
                doctor: initial.doctor.id,
                date: draft.follow_up_date,
              }) as Route
            }
            className="underline underline-offset-2"
          >
            booking page
          </Link>
          .
        </p>
      )}
    </div>
  );
}

function pickSent(snapshot: Draft, changes: NoteChanges): Partial<Draft> {
  const sent: Partial<Draft> = {};
  for (const key of Object.keys(changes) as (keyof Draft)[]) {
    // Stored as the server keeps it, so the next comparison is fair.
    (sent as Record<string, unknown>)[key] =
      typeof snapshot[key] === "string" ? (snapshot[key] as string).trim() : snapshot[key];
  }
  return sent;
}

function SaveStatus({ state }: { state: SaveState }) {
  let body: React.ReactNode;
  let tone = "var(--text-muted)";
  switch (state.kind) {
    case "saved":
      body = (
        <>
          <Check className="size-3.5" /> Saved at{" "}
          {new Date(state.at).toLocaleTimeString("en-IN", {
            hour: "numeric",
            minute: "2-digit",
          })}
        </>
      );
      break;
    case "unsaved":
      body = <>Unsaved changes</>;
      break;
    case "saving":
      body = (
        <>
          <Loader2 className="size-3.5 animate-spin" /> Saving…
        </>
      );
      break;
    case "offline":
      tone = "var(--color-marigold-600)";
      body = (
        <>
          <CloudOff className="size-3.5" /> Not saved. The server cannot be reached, trying
          again…
        </>
      );
      break;
    case "signed-out":
      tone = "var(--color-marigold-600)";
      body = (
        <>
          <CloudOff className="size-3.5" /> Not saved. Your session has ended: sign in again in
          another tab and this page will save what is on it.
        </>
      );
      break;
    case "refused":
      tone = "var(--color-state-noshow)";
      body = <>Not saved. {state.message}</>;
      break;
    case "conflict":
    case "gone":
      tone = "var(--color-state-noshow)";
      body = <>Not saving</>;
      break;
  }
  return (
    <p
      role="status"
      aria-live="polite"
      className="inline-flex items-center gap-1.5 text-[13px]"
      style={{ color: tone }}
    >
      {body}
      <span className="ml-2 hidden text-[12px] text-[var(--text-subtle)] sm:inline">
        Saves as you type. Ctrl+S saves now.
      </span>
    </p>
  );
}

function Banner({ tone, children }: { tone: string; children: React.ReactNode }) {
  return (
    <div
      role="alert"
      className="rounded-[var(--radius-field)] border px-4 py-3 text-[14px] leading-relaxed"
      style={{
        borderColor: `color-mix(in srgb, ${tone} 45%, transparent)`,
        background: `color-mix(in srgb, ${tone} 8%, transparent)`,
      }}
    >
      {children}
    </div>
  );
}

const FIELD_CLASS =
  "w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3.5 py-2.5 text-[15px] leading-relaxed transition-[border-color,box-shadow] outline-none placeholder:text-[var(--text-subtle)] focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)] disabled:opacity-70 aria-invalid:border-[var(--color-state-noshow)]";

function Section({
  section,
  value,
  error,
  onChange,
  onBlur,
}: {
  section: TextSection;
  value: string;
  error?: string;
  onChange: (value: string) => void;
  onBlur: () => void;
}) {
  const words = SECTION_WORDS[section];
  const limit = SECTION_LIMITS[section];
  const near = value.length > limit * 0.85;
  const inputId = `notes-${section}`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={inputId} className="text-[15px] font-semibold">
        {words.title}
      </label>
      <p id={`${inputId}-hint`} className="-mt-1 text-[13px] text-[var(--text-muted)]">
        {words.hint}
      </p>
      <textarea
        id={inputId}
        value={value}
        maxLength={limit}
        rows={section === "chief_complaint" ? 2 : 4}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onBlur}
        aria-describedby={`${inputId}-hint${error ? ` ${inputId}-error` : ""}`}
        aria-invalid={Boolean(error)}
        className={`${FIELD_CLASS} max-w-[75ch] resize-y [field-sizing:content] ${
          section === "chief_complaint" ? "min-h-[3.5rem]" : "min-h-[7rem]"
        }`}
      />
      {near && (
        <p className="text-[12px] text-[var(--text-muted)] tabular">
          {value.length.toLocaleString("en-IN")} of {limit.toLocaleString("en-IN")} characters
        </p>
      )}
      {error && (
        <p id={`${inputId}-error`} className="text-[13px] text-[var(--color-state-noshow)]">
          {error}
        </p>
      )}
    </div>
  );
}

function DiagnosisField({
  diagnoses,
  error,
  onChange,
}: {
  diagnoses: Diagnosis[];
  error?: string;
  onChange: (value: Diagnosis[]) => void;
}) {
  const [typed, setTyped] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const full = diagnoses.length >= DIAGNOSIS_LIMIT;

  const add = () => {
    const label = typed.trim().replace(/\s+/g, " ");
    if (!label) return;
    const listed = diagnoses.find((each) => each.label.toLowerCase() === label.toLowerCase());
    if (listed) {
      setProblem(`${listed.label} is already listed.`);
      return;
    }
    // The first one written is the main one until the doctor says otherwise.
    onChange([...diagnoses, { label, is_primary: diagnoses.length === 0 }]);
    setTyped("");
    setProblem(null);
  };

  const makeMain = (index: number) =>
    onChange(diagnoses.map((each, at) => ({ ...each, is_primary: at === index })));

  const remove = (index: number) => {
    const left = diagnoses.filter((_, at) => at !== index);
    // Taking away the main one hands the star to whichever is now first.
    const lead = left.some((each) => each.is_primary) ? -1 : 0;
    onChange(left.map((each, at) => (at === lead ? { ...each, is_primary: true } : each)));
  };

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor="notes-diagnosis" className="text-[15px] font-semibold">
        Diagnosis
      </label>
      <p id="notes-diagnosis-hint" className="-mt-1 text-[13px] text-[var(--text-muted)]">
        One at a time. The starred one is the main reason for the visit.
      </p>
      {diagnoses.length > 0 && (
        <ul className="flex max-w-[75ch] flex-col gap-1.5" aria-label="Diagnoses">
          {diagnoses.map((diagnosis, index) => (
            <li
              key={diagnosis.label}
              className="flex min-w-0 items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border)] bg-[var(--surface)] py-1.5 pr-1.5 pl-2"
            >
              <button
                type="button"
                onClick={() => makeMain(index)}
                aria-pressed={diagnosis.is_primary}
                aria-label={
                  diagnosis.is_primary
                    ? `${diagnosis.label} is the main diagnosis`
                    : `Make ${diagnosis.label} the main diagnosis`
                }
                title={diagnosis.is_primary ? "Main diagnosis" : "Make this the main one"}
                className="grid size-7 shrink-0 place-items-center rounded-[6px] transition-colors hover:bg-[var(--surface-sunken)]"
              >
                <Star
                  className="size-4"
                  style={{
                    color: diagnosis.is_primary
                      ? "var(--color-marigold-500)"
                      : "var(--text-subtle)",
                    fill: diagnosis.is_primary ? "var(--color-marigold-400)" : "none",
                  }}
                />
              </button>
              <span className="min-w-0 flex-1 text-[15px] break-words">
                {diagnosis.label}
                {diagnosis.is_primary && (
                  <span className="ml-2 text-[12px] text-[var(--text-muted)]">main</span>
                )}
              </span>
              <button
                type="button"
                onClick={() => remove(index)}
                aria-label={`Remove ${diagnosis.label}`}
                className="grid size-7 shrink-0 place-items-center rounded-[6px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
              >
                <X className="size-4" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {full ? (
        <p className="text-[13px] text-[var(--text-muted)]">
          That is {DIAGNOSIS_LIMIT}, as many as one visit takes.
        </p>
      ) : (
        <div className="flex max-w-[75ch] gap-2">
          <input
            id="notes-diagnosis"
            value={typed}
            maxLength={200}
            placeholder={diagnoses.length ? "Add another" : "For example, acute bronchitis"}
            onChange={(event) => {
              setTyped(event.target.value);
              setProblem(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                add();
              }
            }}
            aria-describedby="notes-diagnosis-hint"
            aria-invalid={Boolean(problem ?? error)}
            className={`${FIELD_CLASS} min-w-0 flex-1 py-2`}
          />
          <button
            type="button"
            onClick={add}
            disabled={!typed.trim()}
            className="inline-flex shrink-0 items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 text-[14px] font-medium transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-50"
          >
            <Plus className="size-4" />
            Add
          </button>
        </div>
      )}
      {(problem ?? error) && (
        <p role="alert" className="text-[13px] text-[var(--color-state-noshow)]">
          {problem ?? error}
        </p>
      )}
    </div>
  );
}

function spokenGap(days: number): string {
  if (days === 7) return "1 week";
  if (days % 7 === 0 && days <= 28) return `${days / 7} weeks`;
  if (days === 30) return "1 month";
  return days === 1 ? "1 day" : `${days} days`;
}

function FollowUpField({
  visit,
  value,
  error,
  onChange,
}: {
  visit: string;
  value: string | null;
  error?: string;
  onChange: (value: string | null) => void;
}) {
  const gap = value ? daysBetween(visit, value) : null;
  const chip = (active: boolean) =>
    `rounded-full border px-3 py-1.5 text-[14px] transition-colors ${
      active
        ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-fg)]"
        : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
    }`;
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="text-[15px] font-semibold">Follow-up</legend>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          aria-pressed={value === null}
          onClick={() => onChange(null)}
          className={chip(value === null)}
        >
          None
        </button>
        {FOLLOW_UP_CHOICES.map((days) => (
          <button
            key={days}
            type="button"
            aria-pressed={gap === days}
            onClick={() => onChange(daysAfter(visit, days))}
            className={chip(gap === days)}
          >
            {spokenGap(days)}
          </button>
        ))}
        <label className="inline-flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <span className="whitespace-nowrap">or on</span>
          <input
            type="date"
            value={value ?? ""}
            min={daysAfter(visit, 1)}
            max={daysAfter(visit, 365)}
            onChange={(event) => onChange(event.target.value || null)}
            aria-label="Follow-up date"
            aria-invalid={Boolean(error)}
            className={`${FIELD_CLASS} w-auto py-1.5 text-[14px]`}
          />
        </label>
      </div>
      {value && !error && gap !== null && gap > 0 && (
        <p className="text-[14px]">
          Come back on <strong className="font-semibold">{shortDate(value)}</strong>, in{" "}
          {spokenGap(gap)}.
        </p>
      )}
      {error && <p className="text-[13px] text-[var(--color-state-noshow)]">{error}</p>}
    </fieldset>
  );
}

// --- Reading finished notes -------------------------------------------------------

function Finished({ record }: { record: Consultation }) {
  const queries = useQueryClient();
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const mayBook = session.data?.permissions.includes("appointment:create") ?? false;
  const mayPrescribe = session.data?.permissions.includes("prescription:create") ?? false;
  const mayReadLab = session.data?.permissions.includes("lab:read") ?? false;
  const draft = record.status === "draft";
  const today = todayISO();
  const standing = record.prescriptions.find((each) => each.status === "issued");
  const being = record.prescriptions.find((each) => each.status === "draft");
  const replaced = record.prescriptions.filter((each) => each.status === "replaced");

  return (
    <div className="flex flex-col gap-7">
      {draft ? (
        <Banner tone="var(--color-state-waiting)">
          {record.doctor.display_name} is still writing these notes. This is the latest save.
        </Banner>
      ) : (
        <p className="inline-flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <Lock className="size-3.5" />
          Finished {record.completed_at ? whenItHappened(record.completed_at) : ""}. Anything
          new goes underneath as an addendum.
        </p>
      )}

      <WrittenNote record={record} />

      {standing && (
        <IssuedPrescription
          prescription={standing}
          earlier={replaced}
          mayCorrect={mayPrescribe && record.can_add_addendum}
          onCorrected={() => {
            void queries.invalidateQueries({ queryKey: ["consultation", record.id] });
            void queries.invalidateQueries({ queryKey: ["prescriptions"] });
            void queries.invalidateQueries({ queryKey: ["queue"] });
          }}
        />
      )}
      {draft && being && (being.items.length > 0 || being.instructions) && (
        <section className="flex flex-col gap-3">
          <h2 className="text-[13px] font-semibold text-[var(--text-muted)]">
            Prescription being written
          </h2>
          <MedicineTable items={being.items} />
          {being.instructions && (
            <p className="max-w-[75ch] text-[15px] whitespace-pre-wrap">{being.instructions}</p>
          )}
        </section>
      )}

      {mayReadLab && <VisitTests visitId={record.id} canOrder={false} />}

      {record.follow_up_date && (
        <div className="flex flex-wrap items-center gap-3 rounded-[var(--radius-field)] border border-[var(--border)] bg-[var(--surface)] px-4 py-3">
          <p className="min-w-0 flex-1 text-[15px]">
            Follow up on{" "}
            <strong className="font-semibold">{shortDate(record.follow_up_date)}</strong>
            {`, ${spokenGap(daysBetween(record.visit_date, record.follow_up_date))} after the visit.`}
          </p>
          {mayBook && !draft && record.follow_up_date >= today && (
            <Link
              href={
                bookingHref({
                  patient: record.patient.id,
                  doctor: record.doctor.id,
                  date: record.follow_up_date,
                }) as Route
              }
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-3.5 py-2 text-[14px] font-semibold text-[var(--accent-fg)] transition hover:brightness-105"
            >
              <CalendarPlus className="size-4" />
              Book the follow-up
            </Link>
          )}
        </div>
      )}

      {!draft && <Addenda record={record} />}
    </div>
  );
}

function WrittenNote({ record }: { record: Consultation }) {
  const sections: { title: string; body: React.ReactNode }[] = [];
  const text = (section: TextSection) => record[section];
  for (const section of ["chief_complaint", "history", "examination"] as const) {
    if (text(section))
      sections.push({ title: SECTION_WORDS[section].title, body: text(section) });
  }
  if (record.diagnoses.length) {
    sections.push({
      title: record.diagnoses.length > 1 ? "Diagnoses" : "Diagnosis",
      body: (
        <ul className="flex flex-col gap-1">
          {record.diagnoses.map((diagnosis) => (
            <li key={diagnosis.label} className="flex items-baseline gap-2">
              {diagnosis.is_primary ? (
                <Star
                  aria-label="Main diagnosis"
                  className="size-3.5 shrink-0 translate-y-0.5"
                  style={{
                    color: "var(--color-marigold-500)",
                    fill: "var(--color-marigold-400)",
                  }}
                />
              ) : (
                <span aria-hidden className="size-3.5 shrink-0" />
              )}
              <span>{diagnosis.label}</span>
            </li>
          ))}
        </ul>
      ),
    });
  }
  if (record.advice) sections.push({ title: SECTION_WORDS.advice.title, body: record.advice });

  if (!sections.length) {
    return (
      <p className="text-[15px] text-[var(--text-muted)]">Nothing has been written yet.</p>
    );
  }
  return (
    <dl className="flex flex-col gap-6">
      {sections.map((section) => (
        <div key={section.title} className="flex flex-col gap-1.5">
          <dt className="text-[13px] font-semibold text-[var(--text-muted)]">
            {section.title}
          </dt>
          <dd className="max-w-[75ch] text-[15px] leading-relaxed break-words whitespace-pre-wrap">
            {section.body}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Addenda({ record }: { record: Consultation }) {
  const queries = useQueryClient();
  const [writing, setWriting] = useState(false);
  const [body, setBody] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const add = useMutation({
    mutationFn: () => addAddendum(record.id, body),
    onSuccess: (next) => {
      queries.setQueryData(["consultation", record.id], next);
      void queries.invalidateQueries({ queryKey: ["consultations"] });
      setBody("");
      setWriting(false);
      setProblem(null);
    },
    onError: (error) =>
      setProblem(
        error instanceof ApiFailure
          ? ((error.fields ? Object.values(error.fields)[0] : undefined) ?? error.message)
          : "That did not go through. Try again in a moment.",
      ),
  });

  if (!record.addenda.length && !record.can_add_addendum) return null;

  return (
    <section
      aria-labelledby="addenda-title"
      className="flex flex-col gap-3 border-t border-[var(--border)] pt-6"
    >
      <h2 id="addenda-title" className="text-[16px] font-semibold">
        Added afterwards
      </h2>
      {record.addenda.length > 0 ? (
        <ol className="flex flex-col gap-3">
          {record.addenda.map((addendum) => (
            <li
              key={addendum.id}
              className="rounded-[var(--radius-field)] border-l-[3px] border-[var(--border-strong)] bg-[var(--surface-sunken)] py-2.5 pr-4 pl-3.5"
            >
              <p className="max-w-[75ch] text-[15px] leading-relaxed break-words whitespace-pre-wrap">
                {addendum.body}
              </p>
              <p className="mt-1 text-[12px] text-[var(--text-muted)]">
                {addendum.written_by ?? "Unknown"}, {whenItHappened(addendum.created_at)}
              </p>
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-[14px] text-[var(--text-muted)]">Nothing added since the visit.</p>
      )}

      {record.can_add_addendum &&
        (writing ? (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              if (!body.trim()) {
                setProblem("Write the addendum first.");
                return;
              }
              if (!add.isPending) add.mutate();
            }}
            className="flex flex-col gap-2"
          >
            <label htmlFor="addendum" className="text-[14px] font-medium">
              Addendum
            </label>
            <textarea
              id="addendum"
              autoFocus
              value={body}
              maxLength={5000}
              rows={3}
              onChange={(event) => {
                setBody(event.target.value);
                setProblem(null);
              }}
              aria-invalid={Boolean(problem)}
              aria-describedby="addendum-hint"
              className={`${FIELD_CLASS} max-w-[75ch] resize-y [field-sizing:content] min-h-[5rem]`}
            />
            <p id="addendum-hint" className="text-[12px] text-[var(--text-muted)]">
              Dated and signed with your name. It cannot be changed once added.
            </p>
            {problem && (
              <p role="alert" className="text-[13px] text-[var(--color-state-noshow)]">
                {problem}
              </p>
            )}
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={add.isPending}
                className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-3.5 py-2 text-[14px] font-semibold text-[var(--primary-fg)] hover:brightness-110 disabled:opacity-60"
              >
                {add.isPending && <Loader2 className="size-4 animate-spin" />}
                Add it
              </button>
              <button
                type="button"
                onClick={() => {
                  setWriting(false);
                  setBody("");
                  setProblem(null);
                }}
                className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] hover:bg-[var(--surface-sunken)]"
              >
                Cancel
              </button>
            </div>
          </form>
        ) : (
          <button
            type="button"
            onClick={() => setWriting(true)}
            className="inline-flex w-fit items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] font-medium transition-colors hover:bg-[var(--surface-sunken)]"
          >
            <Plus className="size-4" />
            Add an addendum
          </button>
        ))}
    </section>
  );
}

// --- The same patient's other visits ------------------------------------------

function EarlierVisits({ record }: { record: Consultation }) {
  const visits = useQuery({
    queryKey: ["consultations", { patient: record.patient.id }],
    queryFn: () => listConsultations({ patient: record.patient.id, limit: 20 }),
    retry: false,
  });
  const others = (visits.data?.items ?? []).filter((visit) => visit.id !== record.id);

  return (
    <aside
      aria-labelledby="earlier-title"
      className="flex flex-col gap-3 lg:sticky lg:top-6 lg:self-start"
    >
      <h2 id="earlier-title" className="text-[15px] font-semibold">
        Earlier visits
      </h2>
      {visits.isPending ? (
        <p className="inline-flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" /> Looking…
        </p>
      ) : visits.isError ? (
        <p className="text-[14px] text-[var(--text-muted)]">Earlier visits did not load.</p>
      ) : others.length === 0 ? (
        <p className="text-[14px] leading-relaxed text-[var(--text-muted)]">
          {`This is the first visit with ${record.doctor.display_name} that has notes.`}
        </p>
      ) : (
        <ol className="flex flex-col gap-2">
          {others.map((visit) => (
            <EarlierVisit key={visit.id} visit={visit} />
          ))}
        </ol>
      )}
    </aside>
  );
}

function EarlierVisit({ visit }: { visit: ConsultationSummary }) {
  const [open, setOpen] = useState(false);
  const full = useQuery({
    queryKey: ["consultation", visit.id],
    queryFn: () => getConsultation(visit.id),
    enabled: open,
    retry: false,
  });
  const headline = visit.primary_diagnosis ?? visit.chief_complaint ?? "No diagnosis written";
  return (
    <li className="rounded-[var(--radius-field)] border border-[var(--border)] bg-[var(--surface)]">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="flex w-full items-start gap-2 px-3 py-2.5 text-left transition-colors hover:bg-[var(--surface-sunken)]"
      >
        <span className="min-w-0 flex-1">
          <span className="block text-[13px] text-[var(--text-muted)] tabular">
            {shortDate(visit.visit_date)}
            {visit.status === "draft" ? ", not finished" : ""}
          </span>
          <span className="block truncate text-[14px] font-medium">{headline}</span>
        </span>
        <ChevronDown
          className={`mt-1 size-4 shrink-0 text-[var(--text-muted)] transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open && (
        <div className="border-t border-[var(--border)] px-3 py-3 text-[14px]">
          {full.isPending ? (
            <Loader2 className="size-4 animate-spin text-[var(--text-muted)]" />
          ) : full.isError ? (
            <p className="text-[var(--text-muted)]">These notes did not load.</p>
          ) : (
            <div className="flex flex-col gap-3">
              <div className="[&_dd]:text-[14px] [&_dl]:gap-3">
                <WrittenNote record={full.data} />
              </div>
              <Link
                href={`/consultations/${visit.id}` as Route}
                className="text-[13px] underline underline-offset-2"
              >
                Open these notes
              </Link>
            </div>
          )}
        </div>
      )}
    </li>
  );
}
