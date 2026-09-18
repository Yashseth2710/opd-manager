"use client";

import { useInfiniteQuery, useQuery } from "@tanstack/react-query";
import { Loader2, Lock, NotebookPen } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { shortDate } from "@/lib/appointments";
import { currentSession } from "@/lib/auth";
import {
  listConsultations,
  type ConsultationStatus,
  type ConsultationSummary,
} from "@/lib/consultations";
import { listDoctors } from "@/lib/doctors";

const PAGE = 25;

export default function NotesPage() {
  return (
    <Permitted permission="consultation:read">
      <Suspense fallback={<Looking />}>
        <NotesList />
      </Suspense>
    </Permitted>
  );
}

function Looking() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center gap-3 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">Finding the notes…</span>
    </div>
  );
}

const TABS: { value: ConsultationStatus | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "draft", label: "Not finished" },
  { value: "completed", label: "Finished" },
];

function NotesList() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const asked = params.get("status");
  const status: ConsultationStatus | "" =
    asked === "draft" || asked === "completed" ? asked : "";
  const doctor = params.get("doctor") ?? "";

  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const ownOnly = session.data?.role === "doctor";

  const doctors = useQuery({
    queryKey: ["doctors", "for-notes"],
    queryFn: () => listDoctors({ status: "all", per_page: 100 }),
    enabled: session.isSuccess && !ownOnly,
    retry: false,
  });

  const unfinished = useQuery({
    queryKey: ["consultations", { status: "draft", doctor, count: true }],
    queryFn: () =>
      listConsultations({ status: "draft", doctor: doctor || undefined, limit: 1 }),
    retry: false,
  });

  const notes = useInfiniteQuery({
    queryKey: ["consultations", { status, doctor }],
    queryFn: ({ pageParam }) =>
      listConsultations({
        status: status || undefined,
        doctor: doctor || undefined,
        limit: PAGE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const shown = pages.reduce((sum, page) => sum + page.items.length, 0);
      return shown < last.total ? shown : undefined;
    },
    retry: false,
  });

  const choose = (key: "status" | "doctor", value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    const query = next.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}` as Route, { scroll: false });
  };

  const items = notes.data?.pages.flatMap((page) => page.items) ?? [];
  const total = notes.data?.pages[0]?.total ?? 0;
  const waiting = unfinished.data?.total ?? 0;

  return (
    <Page
      title="Notes"
      blurb={
        ownOnly
          ? "What you wrote at each visit, newest first. Notes start from the queue once a patient is with you."
          : "What each doctor wrote at each visit, newest first."
      }
    >
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Which notes" className="flex flex-wrap gap-1.5">
          {TABS.map((tab) => {
            const active = status === tab.value;
            return (
              <button
                key={tab.value || "all"}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => choose("status", tab.value)}
                className={`rounded-full border px-3.5 py-1.5 text-[14px] transition-colors ${
                  active
                    ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-fg)]"
                    : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
                }`}
              >
                {tab.label}
                {tab.value === "draft" && waiting > 0 && (
                  <span className="ml-1.5 tabular opacity-80">{waiting}</span>
                )}
              </button>
            );
          })}
        </div>
        {!ownOnly && (
          <label className="flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
            Doctor
            <select
              value={doctor}
              onChange={(event) => choose("doctor", event.target.value)}
              className="max-w-[16rem] rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1.5 text-[14px] text-[var(--text)]"
            >
              <option value="">Everyone</option>
              {doctors.data?.items.map((each) => (
                <option key={each.id} value={each.id}>
                  {each.display_name}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {notes.isPending ? (
        <Looking />
      ) : notes.isError ? (
        <p className="text-[15px] text-[var(--text-muted)]">
          The notes did not load. Try again in a moment.
        </p>
      ) : items.length === 0 ? (
        <Empty status={status} ownOnly={ownOnly} filtered={Boolean(doctor)} />
      ) : (
        <>
          <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
            {items.map((item) => (
              <Row key={item.id} item={item} showDoctor={!ownOnly} />
            ))}
          </ul>
          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-[13px] text-[var(--text-muted)]">
            <span className="tabular">
              {items.length === total ? `${total} in all` : `${items.length} of ${total}`}
            </span>
            {notes.hasNextPage && (
              <button
                type="button"
                onClick={() => void notes.fetchNextPage()}
                disabled={notes.isFetchingNextPage}
                className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] text-[var(--text)] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-60"
              >
                {notes.isFetchingNextPage && <Loader2 className="size-4 animate-spin" />}
                Show more
              </button>
            )}
          </div>
        </>
      )}
    </Page>
  );
}

function Row({ item, showDoctor }: { item: ConsultationSummary; showDoctor: boolean }) {
  const draft = item.status === "draft";
  const headline = item.primary_diagnosis ?? item.chief_complaint;
  const more = item.diagnosis_count > 1 ? ` and ${item.diagnosis_count - 1} more` : "";
  return (
    <li>
      <Link
        href={`/consultations/${item.id}` as Route}
        className="grid grid-cols-[4.5rem_1fr] gap-x-4 gap-y-1 px-4 py-3 transition-colors hover:bg-[var(--surface-sunken)] focus-visible:bg-[var(--surface-sunken)] sm:grid-cols-[5.5rem_1fr_auto]"
      >
        <span className="text-[13px] leading-6 text-[var(--text-muted)] tabular">
          {shortDate(item.visit_date)}
        </span>
        <span className="min-w-0">
          <span className="block truncate text-[15px] font-medium">
            {item.patient.full_name}
            <span className="ml-2 text-[13px] font-normal text-[var(--text-muted)] tabular">
              {item.patient.patient_number}
            </span>
          </span>
          <span className="block truncate text-[14px] text-[var(--text-muted)]">
            {headline
              ? `${headline}${item.primary_diagnosis ? more : ""}`
              : "Nothing written yet"}
            {showDoctor && `, ${item.doctor.display_name}`}
          </span>
        </span>
        <span className="col-start-2 flex items-center gap-2 text-[12px] sm:col-start-auto sm:justify-end">
          {item.addendum_count > 0 && (
            <span className="text-[var(--text-muted)]">
              {item.addendum_count === 1 ? "1 addendum" : `${item.addendum_count} addenda`}
            </span>
          )}
          <span
            className="inline-flex items-center gap-1 rounded-full border px-2 py-0.5 font-medium"
            style={{
              borderColor: `color-mix(in srgb, ${draft ? "var(--color-state-waiting)" : "var(--color-state-completed)"} 50%, transparent)`,
              background: `color-mix(in srgb, ${draft ? "var(--color-state-waiting)" : "var(--color-state-completed)"} 12%, transparent)`,
            }}
          >
            {draft ? <NotebookPen className="size-3" /> : <Lock className="size-3" />}
            {draft ? "Not finished" : "Finished"}
          </span>
        </span>
      </Link>
    </li>
  );
}

function Empty({
  status,
  ownOnly,
  filtered,
}: {
  status: ConsultationStatus | "";
  ownOnly: boolean;
  filtered: boolean;
}) {
  const words =
    status === "draft"
      ? "Nothing left unfinished."
      : status === "completed"
        ? "No finished notes yet."
        : filtered
          ? "This doctor has no notes yet."
          : ownOnly
            ? "No notes yet. When a patient is with you, open their notes from the queue."
            : "No notes have been written at this clinic yet.";
  return (
    <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-10 text-center">
      <p className="text-[15px] text-[var(--text-muted)]">{words}</p>
      {ownOnly && status === "" && (
        <Link
          href="/queue"
          className="mt-4 inline-block rounded-[var(--radius-field)] border border-[var(--border-strong)] px-4 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
        >
          Open the queue
        </Link>
      )}
    </div>
  );
}
