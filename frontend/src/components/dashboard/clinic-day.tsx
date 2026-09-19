"use client";

import { AlertTriangle, HeartPulse } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import {
  clinicFigures,
  DueBackList,
  Figures,
  Late,
  Panel,
  Quiet,
  Shown,
} from "@/components/dashboard/parts";
import { Token } from "@/components/queue/token";
import { ReadingsLine } from "@/components/vitals/readings";
import { LONG_WAIT_MINUTES, type DayLane, type Today } from "@/lib/dashboard";
import { readableTime } from "@/lib/doctors";
import { calledBy, spokenMinutes } from "@/lib/queue";

/** The whole clinic's day, for the desk, the administrator and the staff. */
export function ClinicDay({ today, mayBook }: { today: Today; mayBook: boolean }) {
  const open = today.lanes.filter((lane) => !lane.closed);
  const away = today.lanes.filter((lane) => lane.closed);

  return (
    <div className="flex flex-col gap-6">
      <Figures figures={clinicFigures(today.counts)} />

      <Panel id="doctors-today" title="Doctors today" more={{ href: "/queue", label: "Queue" }}>
        {today.lanes.length === 0 ? (
          <Quiet>
            Nobody is sitting this {today.day_name}. A doctor&apos;s weekly hours decide who
            takes patients on which day.
          </Quiet>
        ) : (
          <ul className="divide-y divide-[var(--border)]">
            {[...open, ...away].map((lane) => (
              <DoctorRow key={lane.doctor.id} lane={lane} />
            ))}
          </ul>
        )}
      </Panel>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel
          id="waiting-room"
          title="In the waiting room"
          count={today.waiting_total}
          more={{ href: "/queue", label: "Queue" }}
        >
          {today.waiting.length === 0 ? (
            <Quiet>Nobody is waiting. Patients show here as they check in.</Quiet>
          ) : (
            <>
              {today.without_vitals > 0 && (
                <p className="flex items-center gap-2 border-b border-[var(--border)] bg-[var(--accent-wash)] px-5 py-2 text-[13px]">
                  <HeartPulse className="size-3.5 shrink-0" />
                  {today.without_vitals === 1
                    ? "1 of them has no vitals taken yet."
                    : `${today.without_vitals} of them have no vitals taken yet.`}
                </p>
              )}
              <ul className="divide-y divide-[var(--border)]">
                {today.waiting.map((entry) => {
                  const long = entry.waited_minutes >= LONG_WAIT_MINUTES;
                  return (
                    <li key={entry.entry_id} className="flex items-start gap-3 px-5 py-2.5">
                      <Token
                        number={entry.token}
                        status="waiting"
                        urgent={entry.priority === "urgent"}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="flex flex-wrap items-baseline justify-between gap-x-3">
                          <Link
                            href={`/queue?doctor=${entry.doctor.id}` as Route}
                            className="min-w-0 truncate text-[15px] font-medium underline-offset-4 hover:underline"
                          >
                            {entry.patient.full_name}
                          </Link>
                          <span
                            className={`shrink-0 text-[13px] tabular ${
                              long
                                ? "font-semibold text-[var(--color-state-noshow)]"
                                : "text-[var(--text-muted)]"
                            }`}
                          >
                            {spokenMinutes(entry.waited_minutes)}
                          </span>
                        </p>
                        <p className="truncate text-[13px] text-[var(--text-muted)]">
                          {[entry.doctor.display_name, entry.reason].filter(Boolean).join(", ")}
                        </p>
                        {entry.vitals ? (
                          <ReadingsLine vitals={entry.vitals} className="mt-0.5" />
                        ) : (
                          <p className="mt-0.5 text-[12px] text-[var(--color-marigold-700)] dark:text-[var(--color-marigold-300)]">
                            No vitals yet
                          </p>
                        )}
                      </div>
                    </li>
                  );
                })}
              </ul>
              <Shown shown={today.waiting.length} total={today.waiting_total} />
            </>
          )}
        </Panel>

        <Panel
          id="still-to-arrive"
          title="Still to arrive"
          count={today.arrivals_total}
          more={{ href: "/appointments", label: "Appointments" }}
        >
          {today.arrivals.length === 0 ? (
            <Quiet>
              {today.counts.booked
                ? "Everyone booked for today has arrived."
                : "Nobody is booked for today."}
            </Quiet>
          ) : (
            <>
              <ul className="divide-y divide-[var(--border)]">
                {today.arrivals.map((arrival) => (
                  <li
                    key={arrival.appointment_id}
                    className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-baseline gap-x-3 px-5 py-2.5"
                  >
                    <time className="font-mono text-[14px] tabular">
                      {readableTime(arrival.start_time)}
                    </time>
                    <div className="min-w-0">
                      <Link
                        href={`/appointments/${arrival.appointment_id}` as Route}
                        className="block truncate text-[15px] underline-offset-4 hover:underline"
                      >
                        {arrival.patient.full_name}
                      </Link>
                      <p className="truncate text-[13px] text-[var(--text-muted)]">
                        {arrival.doctor.display_name}
                        {arrival.is_late && <Late>, late</Late>}
                      </p>
                    </div>
                  </li>
                ))}
              </ul>
              <Shown shown={today.arrivals.length} total={today.arrivals_total} />
            </>
          )}
        </Panel>
      </div>

      {today.due_back.length > 0 && (
        <Panel id="due-back" title="Asked to come back today" count={today.due_back.length}>
          <DueBackList items={today.due_back} date={today.date} mayBook={mayBook} showDoctor />
        </Panel>
      )}
    </div>
  );
}

function DoctorRow({ lane }: { lane: DayLane }) {
  const { now_seeing: inRoom, called } = lane;
  const long = (lane.longest_wait_minutes ?? 0) >= LONG_WAIT_MINUTES;
  const room = lane.doctor.room ? `Room ${lane.doctor.room}` : null;

  return (
    <li className="grid grid-cols-1 gap-x-6 gap-y-1.5 px-5 py-3 sm:grid-cols-[minmax(0,1fr)_auto]">
      <div className="min-w-0">
        <p className="flex flex-wrap items-baseline gap-x-2">
          <Link
            href={`/queue?doctor=${lane.doctor.id}` as Route}
            className="truncate text-[15px] font-medium underline-offset-4 hover:underline"
          >
            {lane.doctor.display_name}
          </Link>
          {room && <span className="text-[13px] text-[var(--text-subtle)]">{room}</span>}
        </p>
        {lane.closed ? (
          <p className="flex items-center gap-1.5 text-[13px] text-[var(--text-muted)]">
            <AlertTriangle className="size-3.5 shrink-0 text-[var(--color-marigold-600)]" />
            {lane.closed}
          </p>
        ) : (
          <p className="flex min-w-0 items-center gap-1.5 text-[13px] text-[var(--text-muted)]">
            <span
              aria-hidden
              className="size-2 shrink-0 rounded-full"
              style={{
                background: inRoom
                  ? "var(--color-state-consulting)"
                  : called
                    ? "var(--color-state-waiting)"
                    : "var(--color-state-cancelled)",
              }}
            />
            <span className="truncate">
              {inRoom
                ? `With token ${inRoom.token}, ${calledBy(inRoom.patient)}, for ${spokenMinutes(inRoom.minutes)}`
                : called
                  ? `Token ${called.token}, ${calledBy(called.patient)}, called ${spokenMinutes(called.minutes)} ago`
                  : lane.waiting
                    ? "Nobody in the room"
                    : "Free"}
            </span>
          </p>
        )}
      </div>
      <dl className="flex flex-wrap items-baseline gap-x-5 gap-y-1 text-[13px] sm:justify-end">
        <Stat label="waiting" value={lane.waiting} />
        {lane.longest_wait_minutes !== null && (
          <div className={long ? "font-semibold text-[var(--color-state-noshow)]" : ""}>
            <dt className="sr-only">Longest wait</dt>
            <dd className="tabular">longest {spokenMinutes(lane.longest_wait_minutes)}</dd>
          </div>
        )}
        <Stat label="seen" value={lane.seen} />
        {lane.to_come > 0 && <Stat label="to come" value={lane.to_come} />}
      </dl>
    </li>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    // The label comes first for the list to read correctly, and shows second.
    <div className="flex flex-row-reverse items-baseline justify-end gap-1">
      <dt className="text-[var(--text-muted)]">{label}</dt>
      <dd className="font-mono text-[15px] font-semibold tabular">{value}</dd>
    </div>
  );
}
