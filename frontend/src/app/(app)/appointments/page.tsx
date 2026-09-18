"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  CalendarDays,
  CalendarPlus,
  ChevronLeft,
  ChevronRight,
  Loader2,
  Plus,
} from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { StatusBadge } from "@/components/appointments/status";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import {
  bookingHref,
  getDay,
  longDate,
  STATUS_COLOURS,
  STATUS_LABELS,
  type Appointment,
  type Status,
} from "@/lib/appointments";
import { currentSession } from "@/lib/auth";
import {
  getAvailability,
  listDoctors,
  readableTime,
  shiftDate,
  type Slot,
} from "@/lib/doctors";

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

// The order a tally reads in, which is the order a day goes in.
const TALLY: Status[] = [
  "scheduled",
  "confirmed",
  "checked_in",
  "waiting",
  "in_consultation",
  "completed",
  "no_show",
  "cancelled",
];

export default function AppointmentsPage() {
  return (
    <Permitted permission="appointment:read">
      <Suspense fallback={<Waiting />}>
        <Day />
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

type Entry =
  | { kind: "appointment"; at: string; appointment: Appointment }
  | { kind: "free"; at: string; slot: Slot };

function Day() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  // Read defensively: the address bar is typed into, and a date of "soon"
  // should show today rather than an error the API was right to raise.
  const rawDate = params.get("date");
  const askedDate = rawDate && ISO_DATE.test(rawDate) ? rawDate : undefined;
  const askedDoctor = params.get("doctor") ?? "";

  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const mayBook = session.data?.permissions.includes("appointment:create") ?? false;
  const mayManageDoctors = session.data?.permissions.includes("doctor:manage") ?? false;
  const isDoctor = session.data?.role === "doctor";

  const doctors = useQuery({
    queryKey: ["doctors", "bookable"],
    queryFn: () => listDoctors({ status: "active", per_page: 100 }),
    enabled: session.isSuccess && !isDoctor,
    retry: false,
  });
  const known = doctors.data?.items ?? [];
  const filter = known.some((doctor) => doctor.id === askedDoctor) ? askedDoctor : "";

  const day = useQuery({
    queryKey: ["appointments", "day", askedDate ?? "today", filter],
    queryFn: () => getDay({ date: askedDate, doctor: filter || undefined }),
    placeholderData: keepPreviousData,
    enabled: session.isSuccess && (isDoctor || !askedDoctor || doctors.isFetched),
    retry: false,
  });

  const date = askedDate ?? day.data?.date;
  const narrowedTo = day.data?.only_doctor_id ?? null;
  const doctorId = narrowedTo ?? filter;

  // One doctor's day is shown as their sheet: the times they sit, with the
  // bookings in them and the gaps left to fill.
  const plan = useQuery({
    queryKey: ["availability", doctorId, date],
    queryFn: () => getAvailability(doctorId, date!),
    enabled: Boolean(doctorId && date),
    retry: false,
  });

  const move = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    router.replace(`${pathname}?${next}` as Route, { scroll: false });
  };

  const items = day.data?.items ?? [];
  const showingOld = day.isPlaceholderData;
  const selected = known.find((doctor) => doctor.id === doctorId);

  return (
    <Page
      title="Appointments"
      blurb={
        narrowedTo
          ? "Your list for the day."
          : "The day's book, for everybody or for one doctor at a time."
      }
      action={
        mayBook &&
        !day.data?.unlinked && (
          <Link
            href={bookingHref({ doctor: doctorId || undefined, date }) as Route}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
          >
            <Plus className="size-4" />
            Book an appointment
          </Link>
        )
      }
    >
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => date && move({ date: shiftDate(date, -1) })}
          disabled={!date}
          aria-label="Previous day"
          className="rounded-[var(--radius-field)] border border-[var(--border-strong)] p-2 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)] disabled:opacity-40"
        >
          <ChevronLeft className="size-4" />
        </button>
        <input
          type="date"
          aria-label="Show this day"
          value={date ?? ""}
          onChange={(event) => event.target.value && move({ date: event.target.value })}
          className="rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] tabular transition-colors hover:border-[var(--color-paper-400)]"
        />
        <button
          type="button"
          onClick={() => date && move({ date: shiftDate(date, 1) })}
          disabled={!date}
          aria-label="Next day"
          className="rounded-[var(--radius-field)] border border-[var(--border-strong)] p-2 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)] disabled:opacity-40"
        >
          <ChevronRight className="size-4" />
        </button>
        {date && (
          <h2 className="ml-1 text-[17px] font-semibold tracking-tight">{longDate(date)}</h2>
        )}
        {day.data && !showingOld && day.data.is_today ? (
          <span className="rounded-full bg-[var(--accent-wash)] px-2.5 py-0.5 text-[13px] font-medium text-[var(--color-marigold-700)]">
            Today
          </span>
        ) : (
          askedDate && (
            <button
              type="button"
              onClick={() => move({ date: null })}
              className="rounded-full border border-[var(--border-strong)] px-3 py-0.5 text-[13px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
            >
              Back to today
            </button>
          )
        )}
      </div>

      {!narrowedTo && !isDoctor && known.length > 1 && (
        <div role="group" aria-label="Doctor" className="mb-5 flex flex-wrap gap-1.5">
          <Chip label="Everybody" active={!filter} onClick={() => move({ doctor: null })} />
          {known.map((doctor) => (
            <Chip
              key={doctor.id}
              label={doctor.display_name}
              active={filter === doctor.id}
              onClick={() => move({ doctor: doctor.id })}
            />
          ))}
        </div>
      )}

      {day.isPending || (doctorId && plan.isPending && !plan.isError) ? (
        <Skeleton />
      ) : day.isError ? (
        <Empty
          heading="The day did not load"
          body="Something went wrong reaching the server. Try again in a moment."
          action={{ label: "Try again", onClick: () => void day.refetch() }}
        />
      ) : day.data.unlinked ? (
        <Empty
          heading="Your account has no list yet"
          body="It is not linked to a doctor profile. An administrator can link it from your profile under Doctors, and your appointments will show here."
        />
      ) : doctorId ? (
        <Sheet
          items={items}
          plan={plan.data}
          planFailed={plan.isError}
          date={date!}
          doctorId={doctorId}
          doctorName={selected?.display_name}
          mayBook={mayBook}
          dimmed={showingOld}
        />
      ) : !isDoctor && doctors.isSuccess && known.length === 0 ? (
        <Empty
          heading="No doctors yet"
          body="Appointments are booked into a doctor's weekly hours. Add a doctor and set their hours first."
          action={
            mayManageDoctors ? { label: "Add a doctor", href: "/doctors/new" } : undefined
          }
        />
      ) : items.length === 0 ? (
        <Empty
          heading={`Nothing booked for ${day.data.day_name}`}
          body={
            day.data.is_today
              ? "Nobody is booked in today yet."
              : "Nobody is booked in for this day."
          }
          action={
            mayBook
              ? { label: "Book an appointment", href: bookingHref({ date: date }) }
              : undefined
          }
        />
      ) : (
        <>
          <Tally items={items} />
          <ul
            className={`divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] transition-opacity ${
              showingOld ? "opacity-60" : ""
            }`}
          >
            {items.map((appointment) => (
              <AppointmentRow key={appointment.id} appointment={appointment} withDoctor />
            ))}
          </ul>
        </>
      )}
    </Page>
  );
}

function Sheet({
  items,
  plan,
  planFailed,
  date,
  doctorId,
  doctorName,
  mayBook,
  dimmed,
}: {
  items: Appointment[];
  plan: { slots: Slot[]; reason: string | null } | undefined;
  planFailed: boolean;
  date: string;
  doctorId: string;
  doctorName?: string;
  mayBook: boolean;
  dimmed: boolean;
}) {
  const entries: Entry[] = [
    ...items.map((appointment): Entry => ({
      kind: "appointment",
      at: appointment.start_time,
      appointment,
    })),
    ...(plan?.slots ?? [])
      .filter((slot) => slot.state === "free")
      .map((slot): Entry => ({ kind: "free", at: slot.start_time, slot })),
  ].sort((one, two) =>
    one.at === two.at ? (one.kind === "appointment" ? -1 : 1) : one.at < two.at ? -1 : 1,
  );

  const free = entries.filter((entry) => entry.kind === "free").length;

  if (entries.length === 0) {
    return (
      <Empty
        heading={doctorName ? `Nothing for ${doctorName} this day` : "Nothing this day"}
        body={
          planFailed
            ? "Their hours did not load. Try again in a moment."
            : (plan?.reason ??
              (plan?.slots.length
                ? "Every time on this day has gone by, and nobody was booked."
                : "Nobody is booked in."))
        }
      />
    );
  }

  return (
    <>
      <Tally items={items} free={free} />
      {plan?.reason && (
        <p className="mb-3 flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <AlertTriangle className="size-4 text-[var(--color-marigold-600)]" />
          {plan.reason}
        </p>
      )}
      <ul
        className={`divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] transition-opacity ${
          dimmed ? "opacity-60" : ""
        }`}
      >
        {entries.map((entry) =>
          entry.kind === "appointment" ? (
            <AppointmentRow key={entry.appointment.id} appointment={entry.appointment} />
          ) : (
            <FreeRow
              key={`free-${entry.at}`}
              slot={entry.slot}
              href={mayBook ? bookingHref({ doctor: doctorId, date, time: entry.at }) : null}
            />
          ),
        )}
      </ul>
    </>
  );
}

function AppointmentRow({
  appointment,
  withDoctor = false,
}: {
  appointment: Appointment;
  withDoctor?: boolean;
}) {
  const released = appointment.status === "cancelled" || appointment.status === "no_show";
  const second = [withDoctor ? appointment.doctor.display_name : null, appointment.reason]
    .filter(Boolean)
    .join(", ");

  return (
    <li>
      <Link
        href={`/appointments/${appointment.id}` as Route}
        className="grid grid-cols-[4.75rem_1fr] items-start gap-x-4 gap-y-1.5 px-5 py-3 transition-colors hover:bg-[var(--surface-sunken)] sm:grid-cols-[5.5rem_1fr_auto] sm:items-center"
      >
        <time
          className={`pt-0.5 font-mono text-[14px] tabular sm:pt-0 ${
            released || appointment.is_over ? "text-[var(--text-subtle)]" : ""
          } ${released ? "line-through" : ""}`}
        >
          {readableTime(appointment.start_time)}
        </time>

        <div className="min-w-0">
          <p className="flex min-w-0 items-baseline gap-2">
            <span
              className={`truncate text-[15px] font-medium ${
                released ? "text-[var(--text-muted)]" : ""
              }`}
            >
              {appointment.patient.full_name}
            </span>
            <span className="shrink-0 font-mono text-[12px] text-[var(--text-subtle)]">
              {appointment.patient.patient_number}
            </span>
          </p>
          {second && <p className="truncate text-[13px] text-[var(--text-muted)]">{second}</p>}
          {appointment.conflict && !released && (
            <p className="mt-0.5 flex items-center gap-1.5 text-[13px] text-[var(--color-marigold-700)] dark:text-[var(--color-marigold-300)]">
              <AlertTriangle className="size-3.5 shrink-0" />
              <span className="truncate">{appointment.conflict}</span>
            </p>
          )}
        </div>

        <div className="col-start-2 sm:col-start-auto">
          <StatusBadge status={appointment.status} />
        </div>
      </Link>
    </li>
  );
}

function FreeRow({ slot, href }: { slot: Slot; href: string | null }) {
  return (
    <li className="grid grid-cols-[4.75rem_1fr_auto] items-center gap-x-4 bg-[color-mix(in_srgb,var(--surface-sunken)_45%,transparent)] px-5 py-2 sm:grid-cols-[5.5rem_1fr_auto]">
      <time className="font-mono text-[14px] text-[var(--text-muted)] tabular">
        {readableTime(slot.start_time)}
      </time>
      <span className="text-[14px] text-[var(--text-subtle)]">Free</span>
      {href && (
        <Link
          href={href as Route}
          aria-label={`Book ${readableTime(slot.start_time)}`}
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1 text-[13px] transition-colors hover:border-[var(--color-marigold-400)] hover:bg-[var(--accent-wash)]"
        >
          <CalendarPlus className="size-3.5" />
          Book
        </Link>
      )}
    </li>
  );
}

function Tally({ items, free }: { items: Appointment[]; free?: number }) {
  const counts = new Map<Status, number>();
  for (const item of items) counts.set(item.status, (counts.get(item.status) ?? 0) + 1);

  return (
    <div className="mb-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[13px] text-[var(--text-muted)]">
      {TALLY.filter((status) => counts.get(status)).map((status) => (
        <span key={status} className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="size-1.5 rounded-full"
            style={{ background: STATUS_COLOURS[status] }}
          />
          <span className="tabular">{counts.get(status)}</span>{" "}
          {STATUS_LABELS[status].toLowerCase()}
        </span>
      ))}
      {free !== undefined && (
        <span className="inline-flex items-center gap-1.5">
          <span
            aria-hidden
            className="size-1.5 rounded-full border border-[var(--border-strong)]"
          />
          <span className="tabular">{free}</span> free
        </span>
      )}
    </div>
  );
}

function Chip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-3 py-1 text-[13px] transition-colors ${
        active
          ? "border-[var(--color-marigold-400)] bg-[var(--accent-wash)] font-medium text-[var(--color-marigold-700)] dark:text-[var(--color-marigold-200)]"
          : "border-[var(--border-strong)] text-[var(--text-muted)] hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
      }`}
    >
      {label}
    </button>
  );
}

function Skeleton() {
  return (
    <ul
      aria-hidden
      className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]"
    >
      {Array.from({ length: 6 }, (_, index) => (
        <li key={index} className="flex items-center gap-4 px-5 py-3.5">
          <span className="h-4 w-16 animate-pulse rounded bg-[var(--surface-sunken)]" />
          <span className="h-4 flex-1 animate-pulse rounded bg-[var(--surface-sunken)]" />
          <span className="h-5 w-20 animate-pulse rounded-full bg-[var(--surface-sunken)]" />
        </li>
      ))}
    </ul>
  );
}

function Empty({
  heading,
  body,
  action,
}: {
  heading: string;
  body: string;
  action?: { label: string; href?: string; onClick?: () => void };
}) {
  return (
    <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-14 text-center">
      <CalendarDays aria-hidden className="mx-auto mb-3 size-6 text-[var(--text-subtle)]" />
      <h2 className="text-[17px] font-semibold tracking-tight text-balance">{heading}</h2>
      <p className="mx-auto mt-1.5 max-w-[46ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
        {body}
      </p>
      {action?.href ? (
        <Link
          href={action.href as Route}
          className="mt-5 inline-flex rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
        >
          {action.label}
        </Link>
      ) : action?.onClick ? (
        <button
          type="button"
          onClick={action.onClick}
          className="mt-5 inline-flex rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
        >
          {action.label}
        </button>
      ) : null}
    </div>
  );
}
