"use client";

import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Loader2, NotebookPen } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DueBackList, Figures, Late, Panel, Quiet, Shown } from "@/components/dashboard/parts";
import { FlaggedCount, Urgent } from "@/components/labs/parts";
import { Token } from "@/components/queue/token";
import { ReadingsLine } from "@/components/vitals/readings";
import { ApiFailure } from "@/lib/api";
import { shortDate } from "@/lib/appointments";
import { openNotes } from "@/lib/consultations";
import type { InRoom, Today, WaitingPatient } from "@/lib/dashboard";
import { spokenMinutes } from "@/lib/queue";

/** One doctor's own day: who is in, who is next, and what is still open. */
export function DoctorDay({ today, mayBook }: { today: Today; mayBook: boolean }) {
  const lane = today.lanes[0] ?? null;
  const { counts } = today;
  const next = lane?.next ?? null;

  return (
    <div className="flex flex-col gap-6">
      {lane?.closed && (
        <p className="flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-4 py-2.5 text-[14px]">
          <AlertTriangle className="size-4 shrink-0 text-[var(--color-marigold-600)]" />
          {lane.closed}. Nobody new can join your line today.
        </p>
      )}

      <Figures
        figures={[
          {
            label: "Waiting for you",
            value: counts.waiting,
            note: lane?.longest_wait_minutes
              ? `Longest ${spokenMinutes(lane.longest_wait_minutes)}`
              : "Nobody yet",
          },
          {
            label: "Seen today",
            value: counts.seen,
            note: lane && counts.seen ? `About ${lane.average_minutes} min each` : undefined,
          },
          {
            label: "Still to come",
            value: counts.to_come,
            note: counts.late ? <Late>{counts.late} late</Late> : undefined,
          },
          {
            label: "Notes left open",
            value: today.unfinished_total,
            note: today.unfinished_total
              ? "Their prescriptions are not issued"
              : "All finished",
          },
        ]}
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <InTheRoom entry={lane?.now_seeing ?? null} />
        <NextUp entry={next} called={lane?.called ?? null} doctorId={lane?.doctor.id} />
      </div>

      {today.results_total > 0 && (
        <Panel
          id="results"
          title="Reports back for you"
          count={today.results_total}
          more={{ href: "/lab?show=to_review" as Route, label: "All reports" }}
        >
          <ul className="divide-y divide-[var(--border)]">
            {today.results.map((item) => (
              <li key={item.order_id}>
                <Link
                  href={`/lab/${item.order_id}` as Route}
                  className="flex flex-wrap items-baseline gap-x-4 gap-y-1 px-5 py-2.5 transition-colors hover:bg-[var(--surface-sunken)]"
                >
                  <span className="w-24 shrink-0 text-[13px] text-[var(--text-muted)] tabular">
                    {shortDate(item.reported_on)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[15px] font-medium">
                      {item.patient.full_name}
                    </span>
                    <span className="block truncate text-[13px] text-[var(--text-muted)]">
                      {item.test_name}
                    </span>
                  </span>
                  <span className="flex items-center gap-2">
                    {item.urgent && <Urgent />}
                    <FlaggedCount count={item.flagged} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          <Shown shown={today.results.length} total={today.results_total} />
        </Panel>
      )}

      <Panel
        id="unfinished"
        title="Notes left open"
        count={today.unfinished_total}
        more={{ href: "/consultations", label: "All notes" }}
      >
        {today.unfinished.length === 0 ? (
          <Quiet>Every visit you have seen has its notes finished.</Quiet>
        ) : (
          <>
            <ul className="divide-y divide-[var(--border)]">
              {today.unfinished.map((item) => (
                <li key={item.consultation_id}>
                  <Link
                    href={`/consultations/${item.consultation_id}` as Route}
                    className="flex items-baseline gap-4 px-5 py-2.5 transition-colors hover:bg-[var(--surface-sunken)]"
                  >
                    <span className="w-24 shrink-0 text-[13px] text-[var(--text-muted)] tabular">
                      {shortDate(item.visit_date)}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-[15px] font-medium">
                        {item.patient.full_name}
                      </span>
                      <span className="block truncate text-[13px] text-[var(--text-muted)]">
                        {item.chief_complaint ?? "Nothing written yet"}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
            <Shown shown={today.unfinished.length} total={today.unfinished_total} />
          </>
        )}
      </Panel>

      {today.due_back.length > 0 && (
        <Panel id="due-back" title="Asked to come back today" count={today.due_back.length}>
          <DueBackList
            items={today.due_back}
            date={today.date}
            mayBook={mayBook}
            showDoctor={false}
          />
        </Panel>
      )}
    </div>
  );
}

function Card({
  label,
  tone,
  children,
}: {
  label: string;
  tone: string;
  children: React.ReactNode;
}) {
  return (
    <section
      aria-label={label}
      className="flex min-w-0 flex-col gap-3 rounded-[var(--radius-panel)] border px-5 py-4"
      style={{
        borderColor: `color-mix(in srgb, ${tone} 40%, var(--border))`,
        background: `color-mix(in srgb, ${tone} 6%, var(--surface))`,
      }}
    >
      <h2 className="flex items-center gap-2 text-[13px] font-medium">
        <span aria-hidden className="size-2 rounded-full" style={{ background: tone }} />
        {label}
      </h2>
      {children}
    </section>
  );
}

function InTheRoom({ entry }: { entry: InRoom | null }) {
  const router = useRouter();
  const open = useMutation({
    mutationFn: () => openNotes(entry!.entry_id),
    onSuccess: (notes) => router.push(`/consultations/${notes.id}` as Route),
  });

  if (!entry) {
    return (
      <Card label="With you now" tone="var(--color-state-cancelled)">
        <p className="text-[14px] text-[var(--text-muted)]">Nobody is in the room.</p>
      </Card>
    );
  }
  return (
    <Card label="With you now" tone="var(--color-state-consulting)">
      <div className="flex min-w-0 items-center gap-3">
        <Token number={entry.token} status="in_consultation" size="lg" />
        <div className="min-w-0">
          <p className="truncate text-[17px] font-semibold">{entry.patient.full_name}</p>
          <p className="text-[13px] text-[var(--text-muted)]">
            {[entry.patient.age, `in for ${spokenMinutes(entry.minutes)}`]
              .filter(Boolean)
              .join(", ")}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => open.mutate()}
          disabled={open.isPending}
          className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] bg-[var(--primary)] px-3.5 py-2 text-[14px] font-semibold text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-60"
        >
          {open.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <NotebookPen className="size-4" />
          )}
          {entry.consultation_id ? "Open notes" : "Write notes"}
        </button>
        {open.isError && (
          <p role="alert" className="text-[13px] text-[var(--color-state-noshow)]">
            {open.error instanceof ApiFailure
              ? open.error.message
              : "That did not go through. Try again in a moment."}
          </p>
        )}
      </div>
    </Card>
  );
}

function NextUp({
  entry,
  called,
  doctorId,
}: {
  entry: WaitingPatient | null;
  called: InRoom | null;
  doctorId: string | undefined;
}) {
  if (!entry) {
    return (
      <Card label="Next" tone="var(--color-state-cancelled)">
        <p className="text-[14px] text-[var(--text-muted)]">
          Nobody is waiting. Patients show here as they check in.
        </p>
      </Card>
    );
  }
  const isCalled = called?.entry_id === entry.entry_id;
  return (
    <Card
      label={isCalled ? "Called, on their way in" : "Next"}
      tone="var(--color-state-waiting)"
    >
      <div className="flex min-w-0 items-center gap-3">
        <Token
          number={entry.token}
          status={isCalled ? "called" : "waiting"}
          size="lg"
          urgent={entry.priority === "urgent"}
        />
        <div className="min-w-0">
          <p className="truncate text-[17px] font-semibold">{entry.patient.full_name}</p>
          <p className="truncate text-[13px] text-[var(--text-muted)]">
            {[entry.patient.age, entry.reason, `waited ${spokenMinutes(entry.waited_minutes)}`]
              .filter(Boolean)
              .join(", ")}
          </p>
        </div>
      </div>
      {entry.vitals ? (
        <ReadingsLine vitals={entry.vitals} spoken />
      ) : (
        <p className="text-[13px] text-[var(--text-muted)]">No vitals taken yet.</p>
      )}
      {entry.patient.allergy_count > 0 && (
        <p className="flex items-center gap-1.5 text-[13px] font-medium text-[var(--color-state-noshow)]">
          <AlertTriangle className="size-3.5" />
          {entry.patient.allergy_count === 1
            ? "1 allergy on record"
            : `${entry.patient.allergy_count} allergies on record`}
        </p>
      )}
      <Link
        href={(doctorId ? `/queue?doctor=${doctorId}` : "/queue") as Route}
        className="self-start text-[14px] font-medium underline underline-offset-4"
      >
        Your queue
      </Link>
    </Card>
  );
}
