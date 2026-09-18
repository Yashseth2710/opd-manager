"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarCheck, Info, Loader2 } from "lucide-react";
import type { Route } from "next";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useId, useRef, useState } from "react";
import { PatientPicker } from "@/components/appointments/patient-picker";
import { SlotPicker } from "@/components/appointments/slot-picker";
import { Problem } from "@/components/auth/form";
import { showFirstProblem } from "@/components/common/first-problem";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { ApiFailure } from "@/lib/api";
import {
  bookAppointment,
  dayHref,
  getDay,
  getPatientAppointments,
  isReleased,
  longDate,
  shortDate,
  SOURCE_LABELS,
  TYPE_LABELS,
  type AppointmentType,
  type Source,
} from "@/lib/appointments";
import { currentSession } from "@/lib/auth";
import { getSettings } from "@/lib/clinic";
import { getDoctor, listDoctors, readableTime, todayISO } from "@/lib/doctors";
import { getPatient, type PatientSummary } from "@/lib/patients";

const TYPES: AppointmentType[] = ["consultation", "follow_up"];
const SOURCES: Source[] = ["desk", "phone"];

export default function BookPage() {
  return (
    <Permitted permission="appointment:create">
      <Suspense fallback={<Waiting />}>
        <Booking />
      </Suspense>
    </Permitted>
  );
}

function Waiting() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">Opening the book…</span>
    </div>
  );
}

const DAY_MS = 86_400_000;

function daysBetween(from: string, to: string): number {
  return Math.round(
    (new Date(`${to}T00:00:00`).getTime() - new Date(`${from}T00:00:00`).getTime()) / DAY_MS,
  );
}

function Booking() {
  const router = useRouter();
  const params = useSearchParams();
  const queries = useQueryClient();
  const inFlight = useRef(false);

  const askedPatient = params.get("patient");
  const askedDoctor = params.get("doctor") ?? "";
  const askedDate = params.get("date");
  const askedTime = params.get("time");
  const today = todayISO();

  // Undefined until somebody picks or clears a patient, so a patient named
  // in the address bar fills the box without fighting a later change.
  const [patientChoice, setPatientChoice] = useState<PatientSummary | null | undefined>(
    undefined,
  );
  const [doctorChoice, setDoctorChoice] = useState<string | null>(null);
  const [date, setDate] = useState(
    askedDate && /^\d{4}-\d{2}-\d{2}$/.test(askedDate) && askedDate >= today
      ? askedDate
      : today,
  );
  const [time, setTime] = useState<string | null>(
    askedTime && /^\d{2}:\d{2}$/.test(askedTime) ? askedTime : null,
  );
  // Null until somebody chooses, so the suggestion below can decide.
  const [typeChoice, setTypeChoice] = useState<AppointmentType | null>(null);
  const [source, setSource] = useState<Source>("desk");
  const [reason, setReason] = useState("");
  const [notes, setNotes] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);

  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const isDoctor = session.data?.role === "doctor";

  const prefilled = useQuery({
    queryKey: ["patient", askedPatient],
    queryFn: () => getPatient(askedPatient!),
    enabled: Boolean(askedPatient),
    retry: false,
  });
  const archivedPrefill = prefilled.data?.status === "archived";
  const patient =
    patientChoice === undefined
      ? archivedPrefill
        ? null
        : (prefilled.data ?? null)
      : patientChoice;

  const doctors = useQuery({
    queryKey: ["doctors", "bookable"],
    queryFn: () => listDoctors({ status: "active", per_page: 100 }),
    retry: false,
  });
  // A doctor books into their own list and nobody else's, which the day's
  // answer says without another route.
  const reach = useQuery({
    queryKey: ["appointments", "reach"],
    queryFn: () => getDay(),
    enabled: isDoctor,
    retry: false,
  });

  const choices = (doctors.data?.items ?? []).filter(
    (doctor) => !isDoctor || doctor.id === reach.data?.only_doctor_id,
  );
  const doctorId =
    doctorChoice ??
    (choices.some((doctor) => doctor.id === askedDoctor)
      ? askedDoctor
      : choices.length === 1
        ? choices[0]!.id
        : "");

  const doctor = useQuery({
    queryKey: ["doctor", doctorId],
    queryFn: () => getDoctor(doctorId),
    enabled: Boolean(doctorId),
    retry: false,
  });
  const settings = useQuery({ queryKey: ["settings"], queryFn: getSettings, retry: false });
  const visits = useQuery({
    queryKey: ["patient-appointments", patient?.id],
    queryFn: () => getPatientAppointments(patient!.id),
    enabled: Boolean(patient),
    retry: false,
  });

  // Seen by this doctor recently enough that the clinic charges the lower
  // follow-up fee. Suggested rather than decided: the desk may know better.
  const lastVisit = (visits.data?.history ?? []).find(
    (visit) => visit.doctor.id === doctorId && visit.has_started && !isReleased(visit.status),
  );
  const windowDays = settings.data?.follow_up_window_days ?? 0;
  const gap = lastVisit ? daysBetween(lastVisit.date, date) : null;
  const followsUp = gap !== null && gap >= 0 && gap <= windowDays;
  const kind: AppointmentType = typeChoice ?? (followsUp ? "follow_up" : "consultation");

  const alreadyBooked = (visits.data?.upcoming ?? []).find(
    (visit) => visit.doctor.id === doctorId,
  );

  const book = useMutation({
    mutationFn: () =>
      bookAppointment({
        patient_id: patient!.id,
        doctor_id: doctorId,
        date,
        start_time: time!,
        appointment_type: kind,
        source,
        reason: reason.trim() || null,
        notes: notes.trim() || null,
      }),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: (made) => {
      queries.setQueryData(["appointment", made.id], made);
      void queries.invalidateQueries({ queryKey: ["availability", doctorId] });
      void queries.invalidateQueries({ queryKey: ["appointments"] });
      void queries.invalidateQueries({ queryKey: ["patient-appointments", made.patient.id] });
      router.replace(`/appointments/${made.id}` as Route);
    },
    onError: (error) => {
      if (!(error instanceof ApiFailure)) {
        setProblem("Something went wrong. Try again.");
        return;
      }
      if (error.code === "APPT_SLOT_UNAVAILABLE") {
        // Somebody else got there first. The time is cleared and the day
        // reloaded, so what is on screen is what is really free.
        setTime(null);
        void queries.invalidateQueries({ queryKey: ["availability", doctorId, date] });
      }
      if (error.fields) {
        setFields(error.fields);
        showFirstProblem(error.fields);
      }
      setProblem(error.message);
    },
  });

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (inFlight.current) return;

    const missing: Record<string, string> = {};
    if (!patient) missing.patient_id = "Choose who the appointment is for.";
    if (!doctorId) missing.doctor_id = "Choose a doctor.";
    if (!time) missing.start_time = "Pick a time.";
    setFields(missing);
    setProblem(null);
    if (Object.keys(missing).length) {
      showFirstProblem(missing);
      return;
    }

    inFlight.current = true;
    book.mutate();
  };

  if (isDoctor && reach.data?.unlinked) {
    return (
      <Page
        title="Book an appointment"
        back={{ href: "/appointments" as Route, label: "Back to the day" }}
      >
        <p className="max-w-[56ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
          Your account is not linked to a doctor profile yet, so there is no list to book into.
          An administrator can link it from your profile under Doctors.
        </p>
      </Page>
    );
  }

  const chosenDoctor = choices.find((item) => item.id === doctorId);
  const fee = (type: AppointmentType) =>
    doctor.data
      ? type === "follow_up"
        ? doctor.data.follow_up_fee
        : doctor.data.consultation_fee
      : null;

  return (
    <Page
      title="Book an appointment"
      blurb="Pick the patient, the doctor and a free time. Nothing is booked until you press the button at the bottom."
      back={{ href: dayHref(date, askedDoctor || null) as Route, label: "Back to the day" }}
    >
      <form onSubmit={submit} noValidate className="max-w-2xl">
        {problem && <Problem>{problem}</Problem>}

        <Section title="Patient">
          {archivedPrefill && patientChoice === undefined && (
            <p className="mb-3 text-[14px] text-[var(--text-muted)]">
              {prefilled.data?.full_name}&rsquo;s record is archived. Restore it from their
              profile before booking, or find somebody else.
            </p>
          )}
          {askedPatient && prefilled.isPending && patientChoice === undefined ? (
            <div className="h-[4.25rem] animate-pulse rounded-[var(--radius-panel)] bg-[var(--surface-sunken)]" />
          ) : (
            <PatientPicker
              chosen={patient}
              onChoose={(next) => {
                setPatientChoice(next);
                setTypeChoice(null);
                setFields(({ patient_id: _, ...rest }) => rest);
              }}
              error={fields.patient_id}
            />
          )}
        </Section>

        <Section title="Doctor">
          {doctors.isPending || (isDoctor && reach.isPending) ? (
            <div className="h-11 animate-pulse rounded-[var(--radius-field)] bg-[var(--surface-sunken)]" />
          ) : choices.length === 0 ? (
            <p className="text-[14px] leading-relaxed text-[var(--text-muted)]">
              There is nobody to book with yet. Add a doctor and give them their weekly hours
              first.
            </p>
          ) : (
            <>
              <select
                name="doctor_id"
                value={doctorId}
                onChange={(event) => {
                  setDoctorChoice(event.target.value);
                  setTime(null);
                  setTypeChoice(null);
                  setFields(({ doctor_id: _, ...rest }) => rest);
                }}
                aria-label="Doctor"
                aria-invalid={Boolean(fields.doctor_id)}
                className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2.5 text-[15px] transition-colors hover:border-[var(--color-paper-400)] aria-invalid:border-[var(--color-state-noshow)]"
              >
                <option value="" disabled>
                  Choose a doctor
                </option>
                {choices.map((item) => (
                  <option key={item.id} value={item.id}>
                    {item.display_name}
                    {item.speciality ? `, ${item.speciality}` : ""}
                  </option>
                ))}
              </select>
              {chosenDoctor && chosenDoctor.working_days === 0 && (
                <p className="mt-2 text-[13px] text-[var(--color-state-waiting)]">
                  {chosenDoctor.display_name} has no weekly hours yet, so there are no times to
                  offer.
                </p>
              )}
              {fields.doctor_id && (
                <p role="alert" className="mt-2 text-[13px] text-[var(--color-state-noshow)]">
                  {fields.doctor_id}
                </p>
              )}
            </>
          )}
        </Section>

        <Section title="Time">
          {doctorId ? (
            <SlotPicker
              doctorId={doctorId}
              date={date}
              onDate={(next) => {
                setDate(next);
                setTime(null);
                setFields(({ date: _, start_time: __, ...rest }) => rest);
              }}
              value={time}
              onPick={(start) => {
                setTime(start);
                setFields(({ date: _, start_time: __, ...rest }) => rest);
              }}
              error={fields.start_time ?? fields.date}
            />
          ) : (
            <p className="text-[14px] text-[var(--text-muted)]">
              Choose a doctor to see their free times.
            </p>
          )}
          {patient && alreadyBooked && (
            <p className="mt-3 flex gap-2 text-[13px] leading-relaxed text-[var(--text-muted)]">
              <Info className="mt-0.5 size-3.5 shrink-0" />
              {patient.preferred_name ?? patient.full_name.split(" ")[0]} is already booked with{" "}
              {alreadyBooked.doctor.display_name} on {shortDate(alreadyBooked.date)} at{" "}
              {readableTime(alreadyBooked.start_time)}.
            </p>
          )}
        </Section>

        <Section title="Visit">
          <div className="grid gap-5">
            <Choice
              label="Type"
              options={TYPES.map((type) => ({
                value: type,
                label: TYPE_LABELS[type],
                aside: fee(type) ? `₹${fee(type)}` : undefined,
              }))}
              value={kind}
              onChange={(value) => setTypeChoice(value as AppointmentType)}
            />
            {followsUp && lastVisit && (
              <p className="-mt-3 text-[13px] text-[var(--text-muted)]">
                Seen by {lastVisit.doctor.display_name} on {shortDate(lastVisit.date)}, inside
                the clinic&rsquo;s {windowDays}-day follow-up window.
              </p>
            )}
            <Choice
              label="How it was booked"
              options={SOURCES.map((value) => ({ value, label: SOURCE_LABELS[value] }))}
              value={source}
              onChange={(value) => setSource(value as Source)}
            />
            <Text
              label="Reason for the visit"
              name="reason"
              value={reason}
              onChange={setReason}
              max={200}
              hint="In the patient's words. The doctor sees this."
              error={fields.reason}
            />
            <Text
              label="Notes for the desk"
              name="notes"
              value={notes}
              onChange={setNotes}
              max={1000}
              multiline
              hint="Bring last month's reports, needs a wheelchair."
              error={fields.notes}
            />
          </div>
        </Section>

        <div className="mt-8 flex flex-col gap-4 border-t border-[var(--border)] pt-6 sm:flex-row sm:items-center sm:justify-between">
          <p
            className="text-[15px] leading-relaxed text-[var(--text-muted)]"
            aria-live="polite"
          >
            {patient && chosenDoctor && time ? (
              <>
                <span className="text-[var(--text)]">{patient.full_name}</span> with{" "}
                <span className="text-[var(--text)]">{chosenDoctor.display_name}</span>,{" "}
                {longDate(date)} at{" "}
                <span className="text-[var(--text)] tabular">{readableTime(time)}</span>.
              </>
            ) : (
              "Choose a patient, a doctor and a time."
            )}
          </p>
          <button
            type="submit"
            disabled={book.isPending}
            className="inline-flex shrink-0 items-center justify-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-5 py-2.5 text-[15px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06] disabled:opacity-60"
          >
            {book.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <CalendarCheck className="size-4" />
            )}
            {book.isPending ? "Booking" : "Book appointment"}
          </button>
        </div>
      </form>
    </Page>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <fieldset className="grid gap-3 border-t border-[var(--border)] py-6 first-of-type:border-0 first-of-type:pt-0 sm:grid-cols-[9rem_1fr] sm:gap-6">
      <legend className="contents">
        <span className="text-[15px] font-semibold tracking-tight sm:pt-2">{title}</span>
      </legend>
      <div className="min-w-0">{children}</div>
    </fieldset>
  );
}

function Choice({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { value: string; label: string; aside?: string }[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <p className="mb-1.5 text-[13px] font-medium">{label}</p>
      <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-2">
        {options.map((option) => {
          const on = option.value === value;
          return (
            <button
              key={option.value}
              type="button"
              role="radio"
              aria-checked={on}
              onClick={() => onChange(option.value)}
              className={`inline-flex items-center gap-2 rounded-[var(--radius-field)] border px-3.5 py-2 text-[14px] transition-colors ${
                on
                  ? "border-[var(--color-ink-700)] bg-[var(--primary)] font-medium text-[var(--primary-fg)]"
                  : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
              }`}
            >
              {option.label}
              {option.aside && (
                <span className={`tabular ${on ? "opacity-80" : "text-[var(--text-muted)]"}`}>
                  {option.aside}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Text({
  label,
  name,
  value,
  onChange,
  max,
  hint,
  error,
  multiline = false,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  max: number;
  hint?: string;
  error?: string;
  multiline?: boolean;
}) {
  const id = useId();
  // The hint sits outside the label and is pointed to, so the field is
  // announced by its name and the hint follows, rather than one long name.
  const described = error || hint ? `${id}-about` : undefined;
  const shared =
    "w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2.5 text-[15px] transition-colors placeholder:text-[var(--text-subtle)] hover:border-[var(--color-paper-400)] aria-invalid:border-[var(--color-state-noshow)]";
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-[13px] font-medium">
        {label}
      </label>
      {multiline ? (
        <textarea
          id={id}
          name={name}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          maxLength={max}
          rows={3}
          aria-invalid={Boolean(error)}
          aria-describedby={described}
          className={`${shared} resize-y`}
        />
      ) : (
        <input
          id={id}
          name={name}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          maxLength={max}
          aria-invalid={Boolean(error)}
          aria-describedby={described}
          className={shared}
        />
      )}
      {error ? (
        <p
          id={described}
          role="alert"
          className="mt-1.5 text-[13px] text-[var(--color-state-noshow)]"
        >
          {error}
        </p>
      ) : (
        hint && (
          <p id={described} className="mt-1.5 text-[13px] text-[var(--text-subtle)]">
            {hint}
          </p>
        )
      )}
    </div>
  );
}
