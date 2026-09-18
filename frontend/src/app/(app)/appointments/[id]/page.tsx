"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  CalendarClock,
  CalendarPlus,
  Check,
  DoorOpen,
  ListOrdered,
  Loader2,
  Pencil,
  UserX,
  XCircle,
} from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { SlotPicker } from "@/components/appointments/slot-picker";
import { StatusBadge } from "@/components/appointments/status";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { ApiFailure } from "@/lib/api";
import {
  bookingHref,
  cancelAppointment,
  changeAppointment,
  confirmAppointment,
  dayHref,
  getAppointment,
  isOpen,
  longDate,
  markNoShow,
  SOURCE_LABELS,
  STATUS_COLOURS,
  TYPE_LABELS,
  whenItHappened,
  type AppointmentDetail,
  type AppointmentEvent,
  type AppointmentType,
  type Source,
} from "@/lib/appointments";
import { currentSession } from "@/lib/auth";
import { listDoctors, readableTime, todayISO } from "@/lib/doctors";
import { initials, readablePhone } from "@/lib/patients";
import { checkIn } from "@/lib/queue";

type Mode = "move" | "edit" | "cancel" | "no_show" | null;

export default function AppointmentPage() {
  return (
    <Permitted permission="appointment:read">
      <Appointment />
    </Permitted>
  );
}

function Appointment() {
  const id = String(useParams().id);
  const [mode, setMode] = useState<Mode>(null);

  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const appointment = useQuery({
    queryKey: ["appointment", id],
    queryFn: () => getAppointment(id),
    retry: false,
  });
  const may = (permission: string) => session.data?.permissions.includes(permission) ?? false;

  if (appointment.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Opening the appointment…</span>
      </div>
    );
  }

  if (appointment.isError) {
    const missing =
      appointment.error instanceof ApiFailure && appointment.error.code === "APPT_NOT_FOUND";
    return (
      <Page title={missing ? "No such appointment" : "That appointment did not load"}>
        <p className="max-w-[54ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
          {missing
            ? "This appointment does not exist here, or it is not on your list. It may have been opened from an old link."
            : "Something went wrong reaching the server. Try again in a moment."}
        </p>
        <Link
          href="/appointments"
          className="mt-6 inline-flex items-center gap-1.5 text-[15px] underline underline-offset-2"
        >
          <ArrowLeft className="size-3.5" />
          Back to the day
        </Link>
      </Page>
    );
  }

  const record = appointment.data;
  const open = isOpen(record.status);

  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-10 lg:py-14">
      <Link
        href={dayHref(record.date) as Route}
        className="mb-6 inline-flex items-center gap-1.5 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
      >
        <ArrowLeft className="size-3.5" />
        Back to the day
      </Link>

      <Header record={record} />
      <When record={record} />

      {open && record.conflict && (
        <p
          role="status"
          className="mt-4 flex gap-2.5 rounded-[var(--radius-field)] border border-[color-mix(in_srgb,var(--color-state-waiting)_45%,transparent)] bg-[color-mix(in_srgb,var(--color-state-waiting)_10%,transparent)] px-4 py-3 text-[14px] leading-relaxed"
        >
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-[var(--color-marigold-600)]" />
          <span>
            {record.conflict} Move this appointment or ring the patient before the day.
          </span>
        </p>
      )}

      <Closed record={record} />

      <Actions
        record={record}
        mode={mode}
        setMode={setMode}
        mayUpdate={may("appointment:update")}
        mayCancel={may("appointment:cancel")}
        mayBook={may("appointment:create")}
        mayCheckIn={may("queue:checkin")}
        isDoctor={session.data?.role === "doctor"}
      />

      <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_20rem]">
        <Details record={record} />
        <History events={record.history} />
      </div>
    </div>
  );
}

function Header({ record }: { record: AppointmentDetail }) {
  const person = record.patient;
  return (
    <header className="flex flex-wrap items-start justify-between gap-4">
      <div className="flex min-w-0 items-center gap-4">
        <span
          aria-hidden
          className="grid size-12 shrink-0 place-items-center rounded-full bg-[var(--accent-wash)] text-[16px] font-semibold text-[var(--color-marigold-700)]"
        >
          {initials(person.full_name)}
        </span>
        <div className="min-w-0">
          <h1 className="text-[26px] leading-tight font-semibold tracking-tight break-words text-balance">
            <Link
              href={`/patients/${person.id}` as Route}
              className="underline-offset-4 hover:underline"
            >
              {person.full_name}
            </Link>
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[14px] text-[var(--text-muted)]">
            <span className="font-mono text-[13px] text-[var(--text-subtle)]">
              {person.patient_number}
            </span>
            {person.age && <span>{person.age}</span>}
            {person.gender && <span className="capitalize">{person.gender}</span>}
            {person.phone && <span className="tabular">{readablePhone(person.phone)}</span>}
            {person.allergy_count > 0 && (
              <span className="inline-flex items-center gap-1 text-[var(--color-state-noshow)]">
                <AlertTriangle className="size-3.5" />
                {person.allergy_count === 1
                  ? "1 allergy on record"
                  : `${person.allergy_count} allergies on record`}
              </span>
            )}
          </p>
        </div>
      </div>
      <StatusBadge status={record.status} size="md" />
    </header>
  );
}

function When({ record }: { record: AppointmentDetail }) {
  const released = record.status === "cancelled" || record.status === "no_show";
  return (
    <section className="mt-8 flex flex-wrap items-end justify-between gap-4 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4">
      <div>
        <p className="text-[14px] text-[var(--text-muted)]">{longDate(record.date)}</p>
        <p
          className={`mt-0.5 font-mono text-[26px] leading-tight font-semibold tracking-tight tabular ${
            released ? "text-[var(--text-subtle)]" : ""
          }`}
        >
          <span className={released ? "line-through decoration-2" : ""}>
            {readableTime(record.start_time)}
          </span>
          <span className="px-2 font-sans text-[18px] font-normal text-[var(--text-subtle)]">
            to
          </span>
          <span className={released ? "line-through decoration-2" : ""}>
            {readableTime(record.end_time)}
          </span>
        </p>
      </div>
      <div className="text-[14px] sm:text-right">
        <Link
          href={`/doctors/${record.doctor.id}` as Route}
          className="font-medium underline-offset-4 hover:underline"
        >
          {record.doctor.display_name}
        </Link>
        <p className="text-[var(--text-muted)]">
          {[record.doctor.speciality, record.doctor.room && `Room ${record.doctor.room}`]
            .filter(Boolean)
            .join(", ")}
        </p>
      </div>
    </section>
  );
}

function Closed({ record }: { record: AppointmentDetail }) {
  if (record.status === "cancelled") {
    const who = [...record.history]
      .reverse()
      .find((line) => line.event === "cancelled")?.actor_name;
    return (
      <p className="mt-4 rounded-[var(--radius-field)] bg-[var(--surface-sunken)] px-4 py-3 text-[14px] leading-relaxed text-[var(--text-muted)]">
        Cancelled
        {record.cancelled_at && ` on ${whenItHappened(record.cancelled_at)}`}
        {who && ` by ${who}`}.
        {record.cancelled_reason && (
          <span className="mt-1 block text-[var(--text)]">“{record.cancelled_reason}”</span>
        )}
      </p>
    );
  }
  if (record.status === "no_show") {
    return (
      <p className="mt-4 rounded-[var(--radius-field)] bg-[color-mix(in_srgb,var(--color-state-noshow)_8%,transparent)] px-4 py-3 text-[14px] leading-relaxed">
        {record.patient.preferred_name ?? record.patient.full_name.split(" ")[0]} did not come.
        The time was given back.
      </p>
    );
  }
  return null;
}

function Actions({
  record,
  mode,
  setMode,
  mayUpdate,
  mayCancel,
  mayBook,
  mayCheckIn,
  isDoctor,
}: {
  record: AppointmentDetail;
  mode: Mode;
  setMode: (mode: Mode) => void;
  mayUpdate: boolean;
  mayCancel: boolean;
  mayBook: boolean;
  mayCheckIn: boolean;
  isDoctor: boolean;
}) {
  const queries = useQueryClient();
  const [problem, setProblem] = useState<string | null>(null);
  const open = isOpen(record.status);

  // Every action answers with the whole appointment, so the screen takes
  // that as the truth straight away rather than asking again and briefly
  // showing the old one.
  const settle = (next: AppointmentDetail) => {
    queries.setQueryData(["appointment", record.id], next);
    void queries.invalidateQueries({ queryKey: ["appointments"] });
    void queries.invalidateQueries({ queryKey: ["availability"] });
    void queries.invalidateQueries({ queryKey: ["patient-appointments", record.patient.id] });
    setProblem(null);
    setMode(null);
  };
  const failed = (error: Error) => setProblem(error.message || "That did not go through.");

  const confirm = useMutation({
    mutationFn: () => confirmAppointment(record.id),
    onSuccess: settle,
    onError: failed,
  });

  // Answers with the place in the queue rather than the appointment, so the
  // appointment is asked for again to pick up its new status and token.
  const arrive = useMutation({
    mutationFn: () => checkIn(record.id),
    onSuccess: () => {
      setProblem(null);
      void queries.invalidateQueries({ queryKey: ["appointment", record.id] });
      void queries.invalidateQueries({ queryKey: ["appointments"] });
      void queries.invalidateQueries({ queryKey: ["queue"] });
      void queries.invalidateQueries({ queryKey: ["patient-appointments", record.patient.id] });
    },
    onError: (error) => {
      failed(error);
      void queries.invalidateQueries({ queryKey: ["appointment", record.id] });
    },
  });

  if (
    record.queue_token !== null &&
    (record.status === "waiting" || record.status === "in_consultation")
  ) {
    return (
      <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--color-state-waiting)_45%,transparent)] bg-[color-mix(in_srgb,var(--color-state-waiting)_8%,transparent)] px-4 py-3">
        <span className="font-mono text-[22px] leading-none font-semibold tabular">
          <span className="sr-only">Token </span>
          {record.queue_token}
        </span>
        <p className="min-w-0 flex-1 text-[14px]">
          {record.status === "in_consultation"
            ? `With ${record.doctor.display_name} now.`
            : `Checked in and waiting for ${record.doctor.display_name}.`}
        </p>
        <Link
          href={`/queue?doctor=${record.doctor.id}` as Route}
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-1.5 text-[13px] font-medium transition-colors hover:bg-[var(--surface-sunken)]"
        >
          <ListOrdered className="size-3.5" />
          Open the queue
        </Link>
      </div>
    );
  }

  if (!open) {
    return mayBook ? (
      <div className="mt-6">
        <Link
          href={bookingHref({ patient: record.patient.id, doctor: record.doctor.id }) as Route}
          className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
        >
          <CalendarPlus className="size-4" />
          Book again
        </Link>
      </div>
    ) : null;
  }

  const button =
    "inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-50";

  return (
    <div className="mt-6">
      {mode === null && (
        <div className="flex flex-wrap gap-2">
          {mayCheckIn && record.is_today && (
            <button
              type="button"
              onClick={() => arrive.mutate()}
              disabled={arrive.isPending}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-3.5 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06] disabled:opacity-60"
            >
              {arrive.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <DoorOpen className="size-4" />
              )}
              {arrive.isPending ? "Checking in" : "Check in"}
            </button>
          )}
          {mayUpdate && record.status === "scheduled" && !record.is_over && (
            <button
              type="button"
              onClick={() => confirm.mutate()}
              disabled={confirm.isPending}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-3.5 py-2 text-[14px] font-medium text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-60"
            >
              {confirm.isPending ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Check className="size-4" />
              )}
              {confirm.isPending ? "Confirming" : "Confirm"}
            </button>
          )}
          {mayUpdate && (
            <button type="button" onClick={() => setMode("move")} className={button}>
              <CalendarClock className="size-4" />
              Move
            </button>
          )}
          {mayUpdate && (
            <button type="button" onClick={() => setMode("edit")} className={button}>
              <Pencil className="size-3.5" />
              Edit details
            </button>
          )}
          {mayUpdate && record.has_started && (
            <button type="button" onClick={() => setMode("no_show")} className={button}>
              <UserX className="size-4" />
              Did not come
            </button>
          )}
          {mayCancel && (
            <button
              type="button"
              onClick={() => setMode("cancel")}
              className={`${button} text-[var(--color-state-noshow)]`}
            >
              <XCircle className="size-4" />
              Cancel appointment
            </button>
          )}
        </div>
      )}

      {problem && mode === null && (
        <p role="alert" className="mt-3 text-[13px] text-[var(--color-state-noshow)]">
          {problem}
        </p>
      )}

      {mode === "move" && (
        <Move
          record={record}
          isDoctor={isDoctor}
          onDone={settle}
          onClose={() => setMode(null)}
        />
      )}
      {mode === "edit" && (
        <Edit record={record} onDone={settle} onClose={() => setMode(null)} />
      )}
      {mode === "cancel" && (
        <Cancel record={record} onDone={settle} onClose={() => setMode(null)} />
      )}
      {mode === "no_show" && (
        <NoShow record={record} onDone={settle} onClose={() => setMode(null)} />
      )}
    </div>
  );
}

function Panel({
  title,
  children,
  tone = "plain",
}: {
  title: string;
  children: React.ReactNode;
  tone?: "plain" | "danger";
}) {
  return (
    <section
      className={`rounded-[var(--radius-panel)] border bg-[var(--surface)] px-5 py-4 ${
        tone === "danger"
          ? "border-[color-mix(in_srgb,var(--color-state-noshow)_40%,transparent)]"
          : "border-[var(--border-strong)]"
      }`}
    >
      <h2 className="mb-4 text-[16px] font-semibold tracking-tight">{title}</h2>
      {children}
    </section>
  );
}

function Buttons({
  busy,
  label,
  busyLabel,
  back,
  onBack,
  danger = false,
}: {
  busy: boolean;
  label: string;
  busyLabel: string;
  back: string;
  onBack: () => void;
  danger?: boolean;
}) {
  return (
    <div className="mt-5 flex flex-wrap gap-2">
      <button
        type="submit"
        disabled={busy}
        className={`inline-flex items-center gap-2 rounded-[var(--radius-field)] px-4 py-2 text-[14px] font-semibold transition hover:brightness-110 disabled:opacity-60 ${
          danger
            ? "bg-[var(--color-state-noshow)] text-white"
            : "bg-[var(--primary)] text-[var(--primary-fg)]"
        }`}
      >
        {busy && <Loader2 className="size-4 animate-spin" />}
        {busy ? busyLabel : label}
      </button>
      <button
        type="button"
        onClick={onBack}
        disabled={busy}
        className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-4 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-50"
      >
        {back}
      </button>
    </div>
  );
}

function Alert({ children }: { children: React.ReactNode }) {
  return (
    <p role="alert" className="mb-3 text-[13px] text-[var(--color-state-noshow)]">
      {children}
    </p>
  );
}

function Move({
  record,
  isDoctor,
  onDone,
  onClose,
}: {
  record: AppointmentDetail;
  isDoctor: boolean;
  onDone: (next: AppointmentDetail) => void;
  onClose: () => void;
}) {
  const queries = useQueryClient();
  const inFlight = useRef(false);
  const [doctorId, setDoctorId] = useState(record.doctor.id);
  const today = todayISO();
  const [date, setDate] = useState(record.date < today ? today : record.date);
  const [time, setTime] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);

  const doctors = useQuery({
    queryKey: ["doctors", "bookable"],
    queryFn: () => listDoctors({ status: "active", per_page: 100 }),
    retry: false,
    enabled: !isDoctor,
  });
  // A doctor moves appointments within their own list, so is never offered
  // anybody else's.
  const choices = isDoctor
    ? []
    : (doctors.data?.items ?? []).filter((doctor) => doctor.status === "active");

  const move = useMutation({
    mutationFn: () =>
      changeAppointment(record.id, { doctor_id: doctorId, date, start_time: time! }),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: (next) => {
      void queries.invalidateQueries({ queryKey: ["availability", record.doctor.id] });
      onDone(next);
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.code === "APPT_SLOT_UNAVAILABLE") {
        setTime(null);
        void queries.invalidateQueries({ queryKey: ["availability", doctorId, date] });
      }
      const fields = error instanceof ApiFailure ? error.fields : undefined;
      setProblem(fields ? Object.values(fields)[0]! : error.message);
    },
  });

  return (
    <Panel title="Move to another time">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (inFlight.current) return;
          if (!time) {
            setProblem("Pick the new time.");
            return;
          }
          inFlight.current = true;
          setProblem(null);
          move.mutate();
        }}
        noValidate
      >
        {problem && <Alert>{problem}</Alert>}
        {choices.length > 1 && (
          <label className="mb-4 block max-w-sm">
            <span className="mb-1.5 block text-[13px] font-medium">Doctor</span>
            <select
              value={doctorId}
              onChange={(event) => {
                setDoctorId(event.target.value);
                setTime(null);
              }}
              className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px]"
            >
              {choices.map((doctor) => (
                <option key={doctor.id} value={doctor.id}>
                  {doctor.display_name}
                </option>
              ))}
            </select>
          </label>
        )}
        <SlotPicker
          doctorId={doctorId}
          date={date}
          onDate={(next) => {
            setDate(next);
            setTime(null);
          }}
          value={time}
          onPick={setTime}
          current={{
            date: record.date,
            start_time: record.start_time,
            doctorId: record.doctor.id,
          }}
        />
        {record.status === "confirmed" && (
          <p className="mt-3 text-[13px] text-[var(--text-muted)]">
            It goes back to booked, since the patient agreed to the old time rather than the new
            one.
          </p>
        )}
        <Buttons
          busy={move.isPending}
          label="Move appointment"
          busyLabel="Moving"
          back="Keep it where it is"
          onBack={onClose}
        />
      </form>
    </Panel>
  );
}

function Edit({
  record,
  onDone,
  onClose,
}: {
  record: AppointmentDetail;
  onDone: (next: AppointmentDetail) => void;
  onClose: () => void;
}) {
  const inFlight = useRef(false);
  const [type, setType] = useState<AppointmentType>(record.appointment_type);
  const [source, setSource] = useState<Source>(record.source);
  const [reason, setReason] = useState(record.reason ?? "");
  const [notes, setNotes] = useState(record.notes ?? "");
  const [problem, setProblem] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      changeAppointment(record.id, {
        appointment_type: type,
        source,
        reason: reason.trim() || null,
        notes: notes.trim() || null,
      }),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: onDone,
    onError: (error) => {
      const fields = error instanceof ApiFailure ? error.fields : undefined;
      setProblem(fields ? Object.values(fields)[0]! : error.message);
    },
  });

  const field =
    "w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] transition-colors hover:border-[var(--color-paper-400)]";

  return (
    <Panel title="Edit details">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (inFlight.current) return;
          inFlight.current = true;
          setProblem(null);
          save.mutate();
        }}
        noValidate
        className="grid max-w-xl gap-4"
      >
        {problem && <Alert>{problem}</Alert>}
        <Segmented
          label="Type"
          value={type}
          options={(["consultation", "follow_up"] as const).map((value) => ({
            value,
            label: TYPE_LABELS[value],
          }))}
          onChange={(value) => setType(value as AppointmentType)}
        />
        <Segmented
          label="How it was booked"
          value={source}
          options={(["desk", "phone"] as const).map((value) => ({
            value,
            label: SOURCE_LABELS[value],
          }))}
          onChange={(value) => setSource(value as Source)}
        />
        <label className="block">
          <span className="mb-1.5 block text-[13px] font-medium">Reason for the visit</span>
          <input
            name="reason"
            value={reason}
            maxLength={200}
            onChange={(event) => setReason(event.target.value)}
            className={field}
          />
        </label>
        <label className="block">
          <span className="mb-1.5 block text-[13px] font-medium">Notes for the desk</span>
          <textarea
            name="notes"
            value={notes}
            maxLength={1000}
            rows={3}
            onChange={(event) => setNotes(event.target.value)}
            className={`${field} resize-y`}
          />
        </label>
        <Buttons
          busy={save.isPending}
          label="Save changes"
          busyLabel="Saving"
          back="Keep as it was"
          onBack={onClose}
        />
      </form>
    </Panel>
  );
}

const REASONS = ["Patient asked to cancel", "Doctor not available", "Booked by mistake"];

function Cancel({
  record,
  onDone,
  onClose,
}: {
  record: AppointmentDetail;
  onDone: (next: AppointmentDetail) => void;
  onClose: () => void;
}) {
  const inFlight = useRef(false);
  const [reason, setReason] = useState("");
  const [problem, setProblem] = useState<string | null>(null);

  const cancel = useMutation({
    mutationFn: () => cancelAppointment(record.id, reason.trim() || null),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: onDone,
    onError: (error) => setProblem(error.message),
  });

  return (
    <Panel title="Cancel this appointment" tone="danger">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (inFlight.current) return;
          inFlight.current = true;
          setProblem(null);
          cancel.mutate();
        }}
        noValidate
      >
        {problem && <Alert>{problem}</Alert>}
        <p className="mb-4 text-[14px] leading-relaxed text-[var(--text-muted)]">
          {readableTime(record.start_time)} on {longDate(record.date)} goes back to being free.
          The appointment stays on the record as cancelled.
        </p>
        <div className="mb-3 flex flex-wrap gap-1.5">
          {REASONS.map((preset) => (
            <button
              key={preset}
              type="button"
              aria-pressed={reason === preset}
              onClick={() => setReason(preset)}
              className={`rounded-full border px-3 py-1 text-[13px] transition-colors ${
                reason === preset
                  ? "border-[var(--color-ink-700)] bg-[var(--primary)] text-[var(--primary-fg)]"
                  : "border-[var(--border-strong)] text-[var(--text-muted)] hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
              }`}
            >
              {preset}
            </button>
          ))}
        </div>
        <label className="block max-w-xl">
          <span className="mb-1.5 block text-[13px] font-medium">Reason</span>
          <input
            name="reason"
            value={reason}
            maxLength={200}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Optional"
            className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] placeholder:text-[var(--text-subtle)]"
          />
        </label>
        <Buttons
          busy={cancel.isPending}
          label="Cancel appointment"
          busyLabel="Cancelling"
          back="Keep appointment"
          onBack={onClose}
          danger
        />
      </form>
    </Panel>
  );
}

function NoShow({
  record,
  onDone,
  onClose,
}: {
  record: AppointmentDetail;
  onDone: (next: AppointmentDetail) => void;
  onClose: () => void;
}) {
  const inFlight = useRef(false);
  const [problem, setProblem] = useState<string | null>(null);
  const name = record.patient.preferred_name ?? record.patient.full_name.split(" ")[0];

  const mark = useMutation({
    mutationFn: () => markNoShow(record.id),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: onDone,
    onError: (error) => setProblem(error.message),
  });

  return (
    <Panel title={`Mark ${name} as not having come`} tone="danger">
      <form
        onSubmit={(event) => {
          event.preventDefault();
          if (inFlight.current) return;
          inFlight.current = true;
          setProblem(null);
          mark.mutate();
        }}
      >
        {problem && <Alert>{problem}</Alert>}
        <p className="text-[14px] leading-relaxed text-[var(--text-muted)]">
          This cannot be undone. If {name} turns up later, book them again.
        </p>
        <Buttons
          busy={mark.isPending}
          label="Mark as a no-show"
          busyLabel="Marking"
          back="Not yet"
          onBack={onClose}
          danger
        />
      </form>
    </Panel>
  );
}

function Segmented({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <p className="mb-1.5 text-[13px] font-medium">{label}</p>
      <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-2">
        {options.map((option) => (
          <button
            key={option.value}
            type="button"
            role="radio"
            aria-checked={option.value === value}
            onClick={() => onChange(option.value)}
            className={`rounded-[var(--radius-field)] border px-3.5 py-2 text-[14px] transition-colors ${
              option.value === value
                ? "border-[var(--color-ink-700)] bg-[var(--primary)] font-medium text-[var(--primary-fg)]"
                : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 border-t border-[var(--border)] px-5 py-3 first:border-0 sm:flex-row sm:gap-4">
      <dt className="text-[13px] text-[var(--text-muted)] sm:w-36 sm:shrink-0 sm:pt-0.5">
        {label}
      </dt>
      <dd className="min-w-0 text-[15px] break-words whitespace-pre-line">
        {value || <span className="text-[var(--text-subtle)]">Not given</span>}
      </dd>
    </div>
  );
}

function Details({ record }: { record: AppointmentDetail }) {
  return (
    <dl className="self-start overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
      <Row
        label="Visit"
        value={
          <span>
            {TYPE_LABELS[record.appointment_type]}
            <span className="ml-2 text-[var(--text-muted)] tabular">₹{record.fee}</span>
          </span>
        }
      />
      <Row label="Reason" value={record.reason} />
      <Row label="Notes for the desk" value={record.notes} />
      <Row label="How it was booked" value={SOURCE_LABELS[record.source]} />
      <Row
        label="Booked by"
        value={
          record.booked_by_name
            ? `${record.booked_by_name}, ${whenItHappened(record.created_at)}`
            : whenItHappened(record.created_at)
        }
      />
    </dl>
  );
}

const EVENT_WORDS: Record<AppointmentEvent["event"], string> = {
  booked: "Booked",
  confirmed: "Confirmed",
  rescheduled: "Moved",
  cancelled: "Cancelled",
  no_show: "Marked as a no-show",
  edited: "Details changed",
  checked_in: "Checked in",
  check_in_undone: "Check-in taken back",
  started: "Went in to the doctor",
  seen: "Seen",
  left: "Left without being seen",
};

function History({ events }: { events: AppointmentEvent[] }) {
  return (
    <section className="self-start rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4">
      <h2 className="mb-4 text-[15px] font-semibold tracking-tight">History</h2>
      <ol className="relative flex flex-col gap-4">
        {events.map((line, index) => (
          <li key={line.id} className="relative flex gap-3">
            {index < events.length - 1 && (
              <span
                aria-hidden
                className="absolute top-3.5 left-[4.5px] h-[calc(100%+0.5rem)] w-px bg-[var(--border-strong)]"
              />
            )}
            <span
              aria-hidden
              className="relative mt-1.5 size-2.5 shrink-0 rounded-full ring-4 ring-[var(--surface)]"
              style={{ background: STATUS_COLOURS[line.to_status] }}
            />
            <div className="min-w-0 text-[14px] leading-snug">
              <p className="font-medium">{EVENT_WORDS[line.event]}</p>
              {line.detail && (
                <p className="mt-0.5 break-words text-[var(--text-muted)]">
                  {line.event === "cancelled" ? `“${line.detail}”` : line.detail}
                </p>
              )}
              <p className="mt-0.5 text-[13px] text-[var(--text-subtle)]">
                {[line.actor_name, whenItHappened(line.created_at)].filter(Boolean).join(", ")}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
