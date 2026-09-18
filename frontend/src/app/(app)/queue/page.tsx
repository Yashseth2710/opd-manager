"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ChevronDown,
  DoorOpen,
  Loader2,
  Megaphone,
  MonitorPlay,
  MoreHorizontal,
  NotebookPen,
  Pill,
  Siren,
  UserPlus,
  X,
} from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { PatientPicker } from "@/components/appointments/patient-picker";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { Token } from "@/components/queue/token";
import { ApiFailure } from "@/lib/api";
import { longDate, TYPE_LABELS } from "@/lib/appointments";
import { currentSession } from "@/lib/auth";
import { openNotes } from "@/lib/consultations";
import { readableTime } from "@/lib/doctors";
import type { PatientSummary } from "@/lib/patients";
import {
  addWalkIn,
  calledBy,
  checkIn,
  getQueue,
  POLL_MS,
  roughly,
  setPriority,
  spokenMinutes,
  takeStep,
  undoCheckIn,
  type Arrival,
  type Lane,
  type Priority,
  type QueueEntry,
  type Step,
} from "@/lib/queue";

export default function QueuePage() {
  return (
    <Permitted permission="appointment:read">
      <Suspense fallback={<Opening />}>
        <Queue />
      </Suspense>
    </Permitted>
  );
}

function Opening() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">Opening the queue…</span>
    </div>
  );
}

/** What just happened, said once at the top, with a way back where there is one. */
type Notice = { text: string; undo?: { entryId: string; label: string } };

function failure(error: unknown): string {
  if (error instanceof ApiFailure) {
    const field = error.fields ? Object.values(error.fields)[0] : undefined;
    return field ?? error.message;
  }
  return "That did not go through. Try again in a moment.";
}

function Queue() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const queries = useQueryClient();
  const askedDoctor = params.get("doctor") ?? "";

  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const may = (permission: string) => session.data?.permissions.includes(permission) ?? false;
  const mayCheckIn = may("queue:checkin");
  const mayManage = may("queue:manage");
  const notes = {
    write: may("consultation:create"),
    read: may("consultation:read"),
    prescriptions: may("prescription:read"),
  };

  const queue = useQuery({
    queryKey: ["queue"],
    queryFn: () => getQueue(),
    // Polled while the tab is in view, and not while it is hidden: a desk
    // screen left on all day should not keep asking when nobody is looking.
    refetchInterval: POLL_MS,
    retry: false,
  });

  const [notice, setNotice] = useState<Notice | null>(null);
  const [addingWalkIn, setAddingWalkIn] = useState(false);

  const lanes = queue.data?.lanes ?? [];
  const narrowed = queue.data?.only_doctor_id ?? null;
  const filter = lanes.some((lane) => lane.doctor.id === askedDoctor) ? askedDoctor : "";
  const shown = filter ? lanes.filter((lane) => lane.doctor.id === filter) : lanes;

  const choose = (doctor: string | null) => {
    const next = new URLSearchParams(params);
    if (doctor) next.set("doctor", doctor);
    else next.delete("doctor");
    const query = next.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}` as Route, { scroll: false });
  };

  const refresh = () => {
    void queries.invalidateQueries({ queryKey: ["queue"] });
    void queries.invalidateQueries({ queryKey: ["appointments"] });
    void queries.invalidateQueries({ queryKey: ["appointment"] });
    void queries.invalidateQueries({ queryKey: ["availability"] });
    void queries.invalidateQueries({ queryKey: ["patient-appointments"] });
  };

  const undo = useMutation({
    mutationFn: undoCheckIn,
    onSuccess: () => {
      setNotice({ text: "Check-in taken back." });
      refresh();
    },
    onError: (error) => setNotice({ text: failure(error) }),
  });

  const openLanes = lanes.filter((lane) => !lane.closed);

  return (
    <Page
      title="Queue"
      blurb={
        queue.data
          ? `${narrowed ? "Your line" : "Who is here"} for ${longDate(queue.data.date)}.`
          : "Who is here today, and who is next."
      }
      action={
        <div className="flex flex-wrap gap-2">
          <Link
            href={(filter ? `/queue/board?doctor=${filter}` : "/queue/board") as Route}
            target="_blank"
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
          >
            <MonitorPlay className="size-4" />
            Waiting-room screen
          </Link>
          {mayCheckIn && !queue.data?.unlinked && (
            <button
              type="button"
              onClick={() => setAddingWalkIn((open) => !open)}
              aria-expanded={addingWalkIn}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
            >
              <UserPlus className="size-4" />
              Add a walk-in
            </button>
          )}
        </div>
      }
    >
      <div aria-live="polite">
        {notice && (
          <div
            role="status"
            className="mb-5 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-4 py-2.5 text-[14px]"
          >
            <span className="min-w-0 flex-1">{notice.text}</span>
            {notice.undo && (
              <button
                type="button"
                onClick={() => {
                  const entryId = notice.undo!.entryId;
                  setNotice(null);
                  undo.mutate(entryId);
                }}
                className="font-medium underline underline-offset-2"
              >
                {notice.undo.label}
              </button>
            )}
            <button
              type="button"
              onClick={() => setNotice(null)}
              aria-label="Dismiss"
              className="rounded-[4px] p-1 text-[var(--text-subtle)] transition-colors hover:text-[var(--text)]"
            >
              <X className="size-3.5" />
            </button>
          </div>
        )}
      </div>

      {addingWalkIn && queue.data && (
        <WalkInPanel
          lanes={openLanes}
          preferred={filter || narrowed || ""}
          onClose={() => setAddingWalkIn(false)}
          onAdded={(entry) => {
            setAddingWalkIn(false);
            setNotice({
              text: `${calledBy(entry.patient)} is token ${entry.token} with ${entry.doctor.display_name}.`,
              undo: { entryId: entry.id, label: "Undo" },
            });
            refresh();
          }}
        />
      )}

      {!narrowed && lanes.length > 1 && (
        <div role="group" aria-label="Doctor" className="mb-5 flex flex-wrap gap-1.5">
          <Chip label="Everybody" active={!filter} onClick={() => choose(null)} />
          {lanes.map((lane) => (
            <Chip
              key={lane.doctor.id}
              label={lane.doctor.display_name}
              count={lane.waiting.length + (lane.called ? 1 : 0)}
              active={filter === lane.doctor.id}
              onClick={() => choose(lane.doctor.id)}
            />
          ))}
        </div>
      )}

      {queue.isPending ? (
        <Skeleton />
      ) : queue.isError && !queue.data ? (
        <Empty
          heading="The queue did not load"
          body="Something went wrong reaching the server. Try again in a moment."
          action={{ label: "Try again", onClick: () => void queue.refetch() }}
        />
      ) : queue.data.unlinked ? (
        <Empty
          heading="Your account has no line yet"
          body="It is not linked to a doctor profile. An administrator can link it from your profile under Doctors, and your patients will show here."
        />
      ) : shown.length === 0 ? (
        <Empty
          heading={`Nobody is sitting this ${queue.data.day_name}`}
          body="No doctor has hours today and nobody is booked in. A doctor's weekly hours decide who takes patients on which day."
        />
      ) : (
        <div className="flex flex-col gap-8">
          {queue.isError && (
            <p
              role="alert"
              className="flex items-center gap-2 text-[13px] text-[var(--color-state-noshow)]"
            >
              <AlertTriangle className="size-3.5" />
              Lost touch with the server. What is shown may be out of date.
            </p>
          )}
          {shown.map((lane) => (
            <LaneView
              key={lane.doctor.id}
              lane={lane}
              mayCheckIn={mayCheckIn}
              mayManage={mayManage}
              notes={notes}
              onNotice={setNotice}
              onChanged={refresh}
            />
          ))}
        </div>
      )}
    </Page>
  );
}

type NotesAccess = { write: boolean; read: boolean; prescriptions: boolean };

function LaneView({
  lane,
  mayCheckIn,
  mayManage,
  notes,
  onNotice,
  onChanged,
}: {
  lane: Lane;
  mayCheckIn: boolean;
  mayManage: boolean;
  notes: NotesAccess;
  onNotice: (notice: Notice) => void;
  onChanged: () => void;
}) {
  const router = useRouter();
  const [problem, setProblem] = useState<string | null>(null);
  const next = lane.waiting[0];

  // Most refusals here mean the line moved on under this screen, and the
  // next refresh shows how. The sentence goes once it has been read.
  useEffect(() => {
    if (!problem) return;
    const timer = setTimeout(() => setProblem(null), 10_000);
    return () => clearTimeout(timer);
  }, [problem]);

  const act = useMutation({
    mutationFn: ({ entry, step }: { entry: QueueEntry; step: Step }) =>
      takeStep(entry.id, step),
    onSuccess: (entry, { step }) => {
      setProblem(null);
      // The line reorders on every step, so the day is asked for again
      // rather than the answer patched into it.
      onChanged();
      if (step === "call")
        onNotice({
          text: `Token ${entry.token}, ${calledBy(entry.patient)}, has been called.`,
        });
    },
    onError: (error) => {
      setProblem(failure(error));
      onChanged();
    },
  });

  // Opening makes the notes the first time and finds them every time after.
  const write = useMutation({
    mutationFn: (entry: QueueEntry) => openNotes(entry.id),
    onSuccess: (opened) => router.push(`/consultations/${opened.id}` as Route),
    onError: (error) => {
      setProblem(failure(error));
      onChanged();
    },
  });

  const pending = act.isPending ? act.variables : undefined;
  const busy = (entry: QueueEntry, step: Step) =>
    pending?.entry.id === entry.id && pending.step === step;

  const room = lane.doctor.room ? `Room ${lane.doctor.room}` : null;
  const facts = [
    `${lane.waiting.length} waiting`,
    lane.seen_count ? `${lane.seen_count} seen` : null,
    lane.waiting.length || lane.now_seeing ? `about ${lane.average_minutes} min each` : null,
  ].filter(Boolean);

  return (
    <section
      aria-labelledby={`lane-${lane.doctor.id}`}
      className="overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]"
    >
      <header className="flex flex-wrap items-end justify-between gap-x-6 gap-y-2 border-b border-[var(--border)] px-5 py-4">
        <div className="min-w-0">
          <h2
            id={`lane-${lane.doctor.id}`}
            className="truncate text-[18px] font-semibold tracking-tight"
          >
            {lane.doctor.display_name}
          </h2>
          <p className="text-[14px] text-[var(--text-muted)]">
            {[lane.doctor.speciality, room].filter(Boolean).join(", ") || " "}
          </p>
        </div>
        <p className="text-[13px] text-[var(--text-muted)] tabular">{facts.join(", ")}</p>
      </header>

      {lane.closed && (
        <p className="flex items-center gap-2 border-b border-[var(--border)] bg-[var(--surface-sunken)] px-5 py-2.5 text-[14px] text-[var(--text-muted)]">
          <AlertTriangle className="size-4 shrink-0 text-[var(--color-marigold-600)]" />
          {lane.closed}. Nobody new can join this line.
        </p>
      )}

      <div className="flex flex-col gap-5 px-5 py-5">
        {problem && (
          <p role="alert" className="text-[13px] text-[var(--color-state-noshow)]">
            {problem}
          </p>
        )}

        {(lane.now_seeing || lane.called) && (
          <div className="grid gap-3 sm:grid-cols-2">
            {lane.now_seeing && (
              <Spotlight
                entry={lane.now_seeing}
                label="With the doctor"
                tone="var(--color-state-consulting)"
                since={lane.now_seeing.started_at}
                sinceWords="in for"
              >
                {notes.write && (
                  <ActionButton
                    primary
                    busy={write.isPending}
                    disabled={write.isPending}
                    onClick={() => write.mutate(lane.now_seeing!)}
                  >
                    <NotebookPen className="size-3.5" />
                    {lane.now_seeing.consultation_id ? "Open notes" : "Write notes"}
                  </ActionButton>
                )}
                {!notes.write && notes.read && lane.now_seeing.consultation_id && (
                  <NotesLink id={lane.now_seeing.consultation_id}>Read notes</NotesLink>
                )}
                {mayManage && (
                  <ActionButton
                    primary={!notes.write}
                    busy={busy(lane.now_seeing, "complete")}
                    disabled={act.isPending}
                    title={
                      notes.write
                        ? "Finishing the notes finishes the visit too. This is for a visit with nothing to write."
                        : undefined
                    }
                    onClick={() => act.mutate({ entry: lane.now_seeing!, step: "complete" })}
                  >
                    Finish
                  </ActionButton>
                )}
              </Spotlight>
            )}
            {lane.called && (
              <Spotlight
                entry={lane.called}
                label="Called"
                tone="var(--color-state-waiting)"
                since={lane.called.called_at}
                sinceAfter=" ago"
              >
                {mayManage && (
                  <>
                    <ActionButton
                      primary
                      busy={busy(lane.called, "start")}
                      disabled={act.isPending || Boolean(lane.now_seeing)}
                      title={
                        lane.now_seeing
                          ? `Finish token ${lane.now_seeing.token} first`
                          : undefined
                      }
                      onClick={() => act.mutate({ entry: lane.called!, step: "start" })}
                    >
                      <DoorOpen className="size-4" />
                      They are in
                    </ActionButton>
                    <ActionButton
                      busy={busy(lane.called, "skip")}
                      disabled={act.isPending}
                      onClick={() => act.mutate({ entry: lane.called!, step: "skip" })}
                    >
                      Not here
                    </ActionButton>
                    {lane.now_seeing && (
                      <p className="w-full text-[13px] text-[var(--text-muted)]">
                        Finish token {lane.now_seeing.token} before bringing them in.
                      </p>
                    )}
                  </>
                )}
              </Spotlight>
            )}
          </div>
        )}

        {mayManage && next && !lane.called && (
          <div className="flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => act.mutate({ entry: next, step: "call" })}
              disabled={act.isPending}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2.5 text-[15px] font-semibold text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-60"
            >
              {busy(next, "call") ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Megaphone className="size-4" />
              )}
              Call token {next.token}
            </button>
            <span className="text-[14px] text-[var(--text-muted)]">
              {next.patient.full_name}
              {next.priority === "urgent" && ", marked urgent"}
            </span>
          </div>
        )}

        <Group title="Waiting" count={lane.waiting.length}>
          {lane.waiting.length === 0 ? (
            <p className="px-1 text-[14px] text-[var(--text-muted)]">
              {lane.now_seeing || lane.called
                ? "Nobody else is waiting."
                : lane.closed
                  ? "Nobody is waiting."
                  : "Nobody is waiting. Patients show here as they check in."}
            </p>
          ) : (
            <ul className="divide-y divide-[var(--border)] rounded-[var(--radius-field)] border border-[var(--border)]">
              {lane.waiting.map((entry) => (
                <WaitingRow
                  key={entry.id}
                  entry={entry}
                  lane={lane}
                  mayManage={mayManage}
                  mayCheckIn={mayCheckIn}
                  acting={act.isPending}
                  onStep={(step) => act.mutate({ entry, step })}
                  onChanged={onChanged}
                  onProblem={setProblem}
                  onNotice={onNotice}
                />
              ))}
            </ul>
          )}
        </Group>

        {lane.skipped.length > 0 && (
          <Group title="Missed their call" count={lane.skipped.length}>
            <ul className="divide-y divide-[var(--border)] rounded-[var(--radius-field)] border border-[var(--border)]">
              {lane.skipped.map((entry) => (
                <li
                  key={entry.id}
                  className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-2 px-4 py-2.5 sm:grid-cols-[auto_1fr_auto]"
                >
                  <Token number={entry.token} status="skipped" />
                  <Who entry={entry} />
                  {mayManage && (
                    <div className="col-start-2 flex flex-wrap gap-2 sm:col-start-auto">
                      <ActionButton
                        busy={busy(entry, "recall")}
                        disabled={act.isPending}
                        onClick={() => act.mutate({ entry, step: "recall" })}
                      >
                        Back in the line
                      </ActionButton>
                      <ActionButton
                        busy={busy(entry, "no-show")}
                        disabled={act.isPending}
                        onClick={() => act.mutate({ entry, step: "no-show" })}
                      >
                        They left
                      </ActionButton>
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </Group>
        )}

        {lane.expected.length > 0 && (
          <Group title="Still to arrive" count={lane.expected.length}>
            <ul className="divide-y divide-[var(--border)] rounded-[var(--radius-field)] border border-[var(--border)]">
              {lane.expected.map((arrival) => (
                <ArrivalRow
                  key={arrival.id}
                  arrival={arrival}
                  mayCheckIn={mayCheckIn && !lane.closed}
                  onCheckedIn={(entry) => {
                    onNotice({
                      text: `${calledBy(entry.patient)} is token ${entry.token} with ${entry.doctor.display_name}.`,
                      undo: { entryId: entry.id, label: "Undo" },
                    });
                    onChanged();
                  }}
                  onProblem={(text) => {
                    setProblem(text);
                    onChanged();
                  }}
                />
              ))}
            </ul>
          </Group>
        )}

        {lane.done.length > 0 && (
          <Done
            entries={lane.done}
            notes={notes}
            opening={write.isPending ? write.variables?.id : undefined}
            onWrite={(entry) => write.mutate(entry)}
          />
        )}
      </div>
    </section>
  );
}

function Spotlight({
  entry,
  label,
  tone,
  since,
  sinceWords = "",
  sinceAfter = "",
  children,
}: {
  entry: QueueEntry;
  label: string;
  tone: string;
  since: string | null;
  sinceWords?: string;
  sinceAfter?: string;
  children?: React.ReactNode;
}) {
  const minutes = useMinutesSince(since);
  return (
    <div
      className="flex flex-col gap-3 rounded-[var(--radius-field)] border px-4 py-3.5"
      style={{
        borderColor: `color-mix(in srgb, ${tone} 45%, transparent)`,
        background: `color-mix(in srgb, ${tone} 8%, transparent)`,
      }}
    >
      <p className="flex items-center gap-2 text-[13px] font-medium" style={{ color: tone }}>
        <span aria-hidden className="size-2 rounded-full" style={{ background: tone }} />
        <span className="text-[var(--text)]">{label}</span>
        {minutes !== null && (
          <span className="font-normal text-[var(--text-muted)]">
            {sinceWords && `${sinceWords} `}
            {spokenMinutes(minutes)}
            {sinceAfter}
          </span>
        )}
      </p>
      <div className="flex min-w-0 items-center gap-3">
        <Token
          number={entry.token}
          status={entry.status}
          size="lg"
          urgent={entry.priority === "urgent"}
        />
        <Who entry={entry} />
      </div>
      {children && <div className="flex flex-wrap gap-2">{children}</div>}
    </div>
  );
}

/** Minutes since a moment, ticking over while the screen is open. */
function useMinutesSince(moment: string | null): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);
  if (!moment) return null;
  return Math.max(0, Math.floor((now - new Date(moment).getTime()) / 60_000));
}

function Who({ entry }: { entry: QueueEntry }) {
  const booked = entry.appointment;
  const why = booked ? booked.reason : entry.reason;
  const how = booked
    ? `${TYPE_LABELS[booked.appointment_type]} at ${readableTime(booked.start_time)}`
    : "Walk-in";
  return (
    <div className="min-w-0 flex-1">
      <p className="flex min-w-0 flex-wrap items-baseline gap-x-2">
        <Link
          href={`/patients/${entry.patient.id}` as Route}
          className="truncate text-[15px] font-medium underline-offset-4 hover:underline"
        >
          {entry.patient.full_name}
        </Link>
        <span className="shrink-0 font-mono text-[12px] text-[var(--text-subtle)]">
          {entry.patient.patient_number}
        </span>
        {entry.priority === "urgent" && (
          <span className="inline-flex items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--color-state-urgent)_14%,transparent)] px-2 py-px text-[12px] font-medium text-[var(--color-state-urgent)]">
            <Siren className="size-3" />
            Urgent
          </span>
        )}
      </p>
      <p className="truncate text-[13px] text-[var(--text-muted)]">
        {[how, why].filter(Boolean).join(", ")}
      </p>
      {entry.patient.allergy_count > 0 && (
        <p className="inline-flex items-center gap-1 text-[12px] text-[var(--color-state-noshow)]">
          <AlertTriangle className="size-3" />
          {entry.patient.allergy_count === 1
            ? "1 allergy on record"
            : `${entry.patient.allergy_count} allergies on record`}
        </p>
      )}
    </div>
  );
}

function WaitingRow({
  entry,
  lane,
  mayManage,
  mayCheckIn,
  acting,
  onStep,
  onChanged,
  onProblem,
  onNotice,
}: {
  entry: QueueEntry;
  lane: Lane;
  mayManage: boolean;
  mayCheckIn: boolean;
  acting: boolean;
  onStep: (step: Step) => void;
  onChanged: () => void;
  onProblem: (text: string | null) => void;
  onNotice: (notice: Notice) => void;
}) {
  const [confirmingLeft, setConfirmingLeft] = useState(false);
  const urgent = entry.priority === "urgent";

  const priority = useMutation({
    mutationFn: (to: Priority) => setPriority(entry.id, to),
    onSuccess: () => {
      onProblem(null);
      onChanged();
    },
    onError: (error) => {
      onProblem(failure(error));
      onChanged();
    },
  });

  const undo = useMutation({
    mutationFn: () => undoCheckIn(entry.id),
    onSuccess: () => {
      onProblem(null);
      onNotice({ text: `Check-in for ${calledBy(entry.patient)} taken back.` });
      onChanged();
    },
    onError: (error) => {
      onProblem(failure(error));
      onChanged();
    },
  });

  const items: MenuItem[] = [];
  if (mayManage) {
    if (!lane.called) items.push({ label: "Call now", onSelect: () => onStep("call") });
    if (!lane.now_seeing)
      items.push({ label: "Bring straight in", onSelect: () => onStep("start") });
    items.push({
      label: urgent ? "No longer urgent" : "Mark urgent",
      onSelect: () => priority.mutate(urgent ? "normal" : "urgent"),
    });
    items.push({ label: "They left", onSelect: () => setConfirmingLeft(true), danger: true });
  }
  if (mayCheckIn && !entry.called_at) {
    items.push({ label: "Undo check-in", onSelect: () => undo.mutate() });
  }

  const working = priority.isPending || undo.isPending;

  return (
    <li className="px-4 py-2.5">
      <div className="flex items-center gap-x-4 gap-y-2">
        <Token number={entry.token} status="waiting" urgent={urgent} />
        <Who entry={entry} />
        <div className="hidden shrink-0 text-right text-[13px] leading-snug sm:block">
          <p className="tabular">Waited {spokenMinutes(entry.waited_minutes)}</p>
          <p className="text-[var(--text-muted)]">{roughly(entry.expected_wait_minutes)}</p>
        </div>
        {working ? (
          <Loader2 className="size-4 shrink-0 animate-spin text-[var(--text-subtle)]" />
        ) : (
          items.length > 0 && (
            <RowMenu label={`More for token ${entry.token}`} items={items} disabled={acting} />
          )
        )}
      </div>
      <p className="mt-1 pl-[3.25rem] text-[13px] text-[var(--text-muted)] tabular sm:hidden">
        Waited {spokenMinutes(entry.waited_minutes)},{" "}
        {roughly(entry.expected_wait_minutes)?.toLowerCase()}
      </p>
      {confirmingLeft && (
        <div
          role="group"
          aria-label="Confirm they left"
          className="mt-2.5 flex flex-wrap items-center gap-2 rounded-[var(--radius-field)] bg-[color-mix(in_srgb,var(--color-state-noshow)_8%,transparent)] px-3 py-2 text-[14px]"
        >
          <span className="mr-auto">
            Take {calledBy(entry.patient)} out of the line as gone without being seen?
          </span>
          <button
            type="button"
            onClick={() => {
              setConfirmingLeft(false);
              onStep("no-show");
            }}
            className="rounded-[var(--radius-field)] bg-[var(--color-state-noshow)] px-3 py-1.5 text-[13px] font-semibold text-white transition hover:brightness-110"
          >
            Yes, they left
          </button>
          <button
            type="button"
            onClick={() => setConfirmingLeft(false)}
            className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[13px] transition-colors hover:bg-[var(--surface-sunken)]"
          >
            Keep them
          </button>
        </div>
      )}
    </li>
  );
}

function ArrivalRow({
  arrival,
  mayCheckIn,
  onCheckedIn,
  onProblem,
}: {
  arrival: Arrival;
  mayCheckIn: boolean;
  onCheckedIn: (entry: QueueEntry) => void;
  onProblem: (text: string) => void;
}) {
  const inFlight = useRef(false);
  const arrive = useMutation({
    mutationFn: () => checkIn(arrival.id),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: onCheckedIn,
    onError: (error) => onProblem(failure(error)),
  });

  return (
    <li className="grid grid-cols-[4.5rem_1fr] items-center gap-x-4 gap-y-2 px-4 py-2.5 sm:grid-cols-[4.5rem_1fr_auto]">
      <time className="font-mono text-[14px] tabular">{readableTime(arrival.start_time)}</time>
      <div className="min-w-0 flex-1">
        <p className="flex min-w-0 items-baseline gap-2">
          <Link
            href={`/appointments/${arrival.id}` as Route}
            className="truncate text-[15px] underline-offset-4 hover:underline"
          >
            {arrival.patient.full_name}
          </Link>
          <span className="shrink-0 font-mono text-[12px] text-[var(--text-subtle)]">
            {arrival.patient.patient_number}
          </span>
        </p>
        <p className="truncate text-[13px] text-[var(--text-muted)]">
          {[
            arrival.is_late ? "Late" : null,
            arrival.status === "confirmed" ? "Confirmed" : null,
            arrival.reason,
          ]
            .filter(Boolean)
            .join(", ") || TYPE_LABELS[arrival.appointment_type]}
        </p>
      </div>
      {mayCheckIn && (
        <button
          type="button"
          onClick={() => {
            if (inFlight.current) return;
            inFlight.current = true;
            arrive.mutate();
          }}
          disabled={arrive.isPending}
          aria-label={`Check in ${arrival.patient.full_name}`}
          className="col-start-2 inline-flex justify-self-start sm:col-start-auto items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-1.5 text-[13px] font-medium transition-colors hover:border-[var(--color-marigold-400)] hover:bg-[var(--accent-wash)] disabled:opacity-60"
        >
          {arrive.isPending && <Loader2 className="size-3.5 animate-spin" />}
          {arrive.isPending ? "Checking in" : "Check in"}
        </button>
      )}
    </li>
  );
}

function NotesLink({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <Link
      href={`/consultations/${id}` as Route}
      className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-1.5 text-[13px] font-medium transition hover:bg-[var(--surface-sunken)]"
    >
      <NotebookPen className="size-3.5" />
      {children}
    </Link>
  );
}

function Done({
  entries,
  notes,
  opening,
  onWrite,
}: {
  entries: QueueEntry[];
  notes: NotesAccess;
  opening: string | undefined;
  onWrite: (entry: QueueEntry) => void;
}) {
  const seen = entries.filter((entry) => entry.status === "completed").length;
  const left = entries.length - seen;
  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-center gap-2 text-[14px] font-medium text-[var(--text-muted)] transition-colors hover:text-[var(--text)] [&::-webkit-details-marker]:hidden">
        <ChevronDown className="size-4 -rotate-90 transition-transform group-open:rotate-0" />
        Done today (
        {[seen && `${seen} seen`, left && `${left} left`].filter(Boolean).join(", ")})
      </summary>
      <ul className="mt-2 divide-y divide-[var(--border)] rounded-[var(--radius-field)] border border-[var(--border)]">
        {entries.map((entry) => (
          <li
            key={entry.id}
            className="grid grid-cols-[auto_1fr] items-center gap-x-4 gap-y-1.5 px-4 py-2 text-[14px] sm:grid-cols-[auto_1fr_auto_auto_auto]"
          >
            <Token number={entry.token} status={entry.status} />
            <span className="min-w-0 truncate">{entry.patient.full_name}</span>
            <span className="col-start-2 text-[13px] text-[var(--text-muted)] sm:col-start-auto">
              {entry.status === "completed"
                ? `Seen after ${spokenMinutes(entry.waited_minutes)}`
                : "Left without being seen"}
            </span>
            {entry.status === "completed" &&
              (entry.consultation_id && notes.read ? (
                <span className="col-start-2 sm:col-start-auto">
                  <NotesLink id={entry.consultation_id}>Notes</NotesLink>
                </span>
              ) : notes.write ? (
                <span className="col-start-2 sm:col-start-auto">
                  <ActionButton
                    busy={opening === entry.id}
                    disabled={opening !== undefined}
                    onClick={() => onWrite(entry)}
                  >
                    <NotebookPen className="size-3.5" />
                    Write notes
                  </ActionButton>
                </span>
              ) : null)}
            {entry.prescription_id && notes.prescriptions && (
              <span className="col-start-2 sm:col-start-auto">
                <Link
                  href={`/prescriptions/${entry.prescription_id}` as Route}
                  className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-1.5 text-[13px] font-medium transition hover:bg-[var(--surface-sunken)]"
                >
                  <Pill className="size-3.5" />
                  Prescription
                </Link>
              </span>
            )}
          </li>
        ))}
      </ul>
    </details>
  );
}

function WalkInPanel({
  lanes,
  preferred,
  onClose,
  onAdded,
}: {
  lanes: Lane[];
  preferred: string;
  onClose: () => void;
  onAdded: (entry: QueueEntry) => void;
}) {
  const inFlight = useRef(false);
  const [patient, setPatient] = useState<PatientSummary | null>(null);
  const [doctorId, setDoctorId] = useState(
    lanes.some((lane) => lane.doctor.id === preferred)
      ? preferred
      : (lanes[0]?.doctor.id ?? ""),
  );
  const [reason, setReason] = useState("");
  const [urgent, setUrgent] = useState(false);
  const [problems, setProblems] = useState<{ patient?: string; form?: string }>({});

  const add = useMutation({
    mutationFn: () =>
      addWalkIn({
        patient_id: patient!.id,
        doctor_id: doctorId,
        reason: reason.trim() || null,
        priority: urgent ? "urgent" : "normal",
      }),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: onAdded,
    onError: (error) => setProblems({ form: failure(error) }),
  });

  if (lanes.length === 0) {
    return (
      <section className="mb-6 rounded-[var(--radius-panel)] border border-[var(--border-strong)] bg-[var(--surface)] px-5 py-4">
        <div className="flex items-start justify-between gap-4">
          <p className="text-[15px] text-[var(--text-muted)]">
            No doctor is taking patients today, so there is no line to add anyone to.
          </p>
          <CloseButton onClick={onClose} />
        </div>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="walk-in-heading"
      className="mb-6 rounded-[var(--radius-panel)] border border-[var(--border-strong)] bg-[var(--surface)] px-5 py-4"
    >
      <div className="mb-4 flex items-start justify-between gap-4">
        <h2 id="walk-in-heading" className="text-[16px] font-semibold tracking-tight">
          Add a walk-in
        </h2>
        <CloseButton onClick={onClose} />
      </div>
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          if (inFlight.current) return;
          if (!patient) {
            setProblems({ patient: "Find the patient first." });
            return;
          }
          inFlight.current = true;
          setProblems({});
          add.mutate();
        }}
        className="flex flex-col gap-4"
      >
        {problems.form && (
          <p role="alert" className="text-[13px] text-[var(--color-state-noshow)]">
            {problems.form}
          </p>
        )}
        <div>
          <span className="mb-1.5 block text-[13px] font-medium">Patient</span>
          <PatientPicker
            chosen={patient}
            onChoose={(chosen) => {
              setPatient(chosen);
              setProblems({});
            }}
            error={problems.patient}
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className="mb-1.5 block text-[13px] font-medium">Doctor</span>
            <select
              value={doctorId}
              onChange={(event) => setDoctorId(event.target.value)}
              className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px]"
            >
              {lanes.map((lane) => (
                <option key={lane.doctor.id} value={lane.doctor.id}>
                  {lane.doctor.display_name} ({lane.waiting.length} waiting)
                </option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="mb-1.5 block text-[13px] font-medium">
              Why they came{" "}
              <span className="font-normal text-[var(--text-subtle)]">optional</span>
            </span>
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              maxLength={200}
              placeholder="Fever since last night"
              className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] placeholder:text-[var(--text-subtle)]"
            />
          </label>
        </div>
        <label className="flex items-center gap-2.5 text-[14px]">
          <input
            type="checkbox"
            checked={urgent}
            onChange={(event) => setUrgent(event.target.checked)}
            className="size-4 accent-[var(--color-state-urgent)]"
          />
          Urgent, see them before everybody else
        </label>
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={add.isPending}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2 text-[14px] font-semibold text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-60"
          >
            {add.isPending && <Loader2 className="size-4 animate-spin" />}
            {add.isPending ? "Adding" : "Add to the queue"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-4 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

type MenuItem = { label: string; onSelect: () => void; danger?: boolean };

/** A handful of less common actions, kept out of the row until asked for. */
function RowMenu({
  label,
  items,
  disabled,
}: {
  label: string;
  items: MenuItem[];
  disabled: boolean;
}) {
  const [open, setOpen] = useState(false);
  const holder = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (event: MouseEvent) => {
      if (!holder.current?.contains(event.target as Node)) setOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        trigger.current?.focus();
      }
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    holder.current?.querySelector<HTMLButtonElement>("[role=menuitem]")?.focus();
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  return (
    <div ref={holder} className="relative shrink-0">
      <button
        ref={trigger}
        type="button"
        aria-label={label}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((now) => !now)}
        className="rounded-[var(--radius-field)] border border-transparent p-1.5 text-[var(--text-muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--text)] disabled:opacity-40"
      >
        <MoreHorizontal className="size-4" />
      </button>
      {open && (
        <div
          role="menu"
          aria-label={label}
          onKeyDown={(event) => {
            if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
            event.preventDefault();
            const buttons = [
              ...(holder.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]") ?? []),
            ];
            const at = buttons.indexOf(document.activeElement as HTMLButtonElement);
            const step = event.key === "ArrowDown" ? 1 : -1;
            buttons[(at + step + buttons.length) % buttons.length]?.focus();
          }}
          className="absolute top-full right-0 z-20 mt-1 min-w-[12rem] overflow-hidden rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] py-1 shadow-[0_8px_24px_-12px_rgb(15_27_45/0.35)]"
        >
          {items.map((item) => (
            <button
              key={item.label}
              type="button"
              role="menuitem"
              onClick={() => {
                setOpen(false);
                item.onSelect();
              }}
              className={`block w-full px-3.5 py-2 text-left text-[14px] transition-colors hover:bg-[var(--surface-sunken)] focus-visible:bg-[var(--surface-sunken)] ${
                item.danger ? "text-[var(--color-state-noshow)]" : ""
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function ActionButton({
  children,
  onClick,
  busy,
  disabled,
  primary = false,
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  busy: boolean;
  disabled: boolean;
  primary?: boolean;
  title?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-[var(--radius-field)] px-3 py-1.5 text-[13px] font-medium transition disabled:opacity-50 ${
        primary
          ? "bg-[var(--primary)] text-[var(--primary-fg)] hover:brightness-110"
          : "border border-[var(--border-strong)] bg-[var(--surface)] hover:bg-[var(--surface-sunken)]"
      }`}
    >
      {busy && <Loader2 className="size-3.5 animate-spin" />}
      {children}
    </button>
  );
}

function Group({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  return (
    <div>
      <h3 className="mb-2 flex items-baseline gap-2 text-[14px] font-semibold">
        {title}
        {count > 0 && (
          <span className="font-normal text-[var(--text-subtle)] tabular">{count}</span>
        )}
      </h3>
      {children}
    </div>
  );
}

function CloseButton({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-label="Close"
      className="rounded-[4px] p-1 text-[var(--text-subtle)] transition-colors hover:text-[var(--text)]"
    >
      <X className="size-4" />
    </button>
  );
}

function Chip({
  label,
  count,
  active,
  onClick,
}: {
  label: string;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[13px] transition-colors ${
        active
          ? "border-[var(--color-marigold-400)] bg-[var(--accent-wash)] font-medium text-[var(--color-marigold-700)] dark:text-[var(--color-marigold-200)]"
          : "border-[var(--border-strong)] text-[var(--text-muted)] hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
      }`}
    >
      {label}
      {count !== undefined && count > 0 && <span className="tabular opacity-75">{count}</span>}
    </button>
  );
}

function Skeleton() {
  return (
    <div aria-hidden className="flex flex-col gap-6">
      {Array.from({ length: 2 }, (_, index) => (
        <div
          key={index}
          className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-5"
        >
          <span className="block h-5 w-48 animate-pulse rounded bg-[var(--surface-sunken)]" />
          <span className="mt-2 block h-4 w-32 animate-pulse rounded bg-[var(--surface-sunken)]" />
          {Array.from({ length: 3 }, (_, row) => (
            <span
              key={row}
              className="mt-4 block h-9 w-full animate-pulse rounded bg-[var(--surface-sunken)]"
            />
          ))}
        </div>
      ))}
    </div>
  );
}

function Empty({
  heading,
  body,
  action,
}: {
  heading: string;
  body: string;
  action?: { label: string; onClick: () => void };
}) {
  return (
    <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-14 text-center">
      <DoorOpen aria-hidden className="mx-auto mb-3 size-6 text-[var(--text-subtle)]" />
      <h2 className="text-[17px] font-semibold tracking-tight text-balance">{heading}</h2>
      <p className="mx-auto mt-1.5 max-w-[48ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
        {body}
      </p>
      {action && (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-5 inline-flex rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
        >
          {action.label}
        </button>
      )}
    </div>
  );
}
