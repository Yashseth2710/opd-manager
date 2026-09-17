"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Loader2, Search, TriangleAlert, UserPlus, X } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { currentSession } from "@/lib/auth";
import {
  describe,
  initials,
  listPatients,
  PAGE_SIZE,
  readablePhone,
  type PatientSummary,
} from "@/lib/patients";

type Status = "active" | "archived" | "all";

const FILTERS: { value: Status; label: string }[] = [
  { value: "active", label: "Active" },
  { value: "archived", label: "Archived" },
  { value: "all", label: "Everyone" },
];

export default function PatientsPage() {
  return (
    <Permitted permission="patient:read">
      <Suspense fallback={<Waiting />}>
        <Register />
      </Suspense>
    </Permitted>
  );
}

function Waiting() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">Opening the register…</span>
    </div>
  );
}

function Register() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const query = params.get("q") ?? "";
  // Read defensively. These come out of the address bar, which anybody can
  // type into, and a filter of "garbage" should show the register rather
  // than an error the API was right to raise.
  const asked = params.get("status");
  const status: Status = FILTERS.some((filter) => filter.value === asked)
    ? (asked as Status)
    : "active";
  const asNumber = Number(params.get("page"));
  const page = Number.isFinite(asNumber) ? Math.max(Math.trunc(asNumber), 1) : 1;

  // Typed separately from the query in the address bar, which follows along
  // a beat later. Keeping the search in the URL is what lets somebody open a
  // record and come back to the list exactly as they left it. It replaces
  // rather than pushes, so the back button leaves the list rather than
  // walking backwards through half-typed names.
  const [typed, setTyped] = useState(query);
  const [mirrored, setMirrored] = useState(query);

  // The address bar can change without anybody typing — the back button, a
  // pasted link — and the box has to follow it when that happens.
  if (mirrored !== query) {
    setMirrored(query);
    setTyped(query);
  }

  useEffect(() => {
    if (typed === query) return;
    const timer = setTimeout(() => {
      const next = new URLSearchParams(params);
      if (typed.trim()) next.set("q", typed.trim());
      else next.delete("q");
      next.delete("page");
      router.replace(`${pathname}?${next}` as Route, { scroll: false });
    }, 300);
    return () => clearTimeout(timer);
  }, [typed, query, params, pathname, router]);

  const move = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value === null) next.delete(key);
      else next.set(key, value);
    }
    router.replace(`${pathname}?${next}` as Route, { scroll: false });
  };

  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const mayRegister = session.data?.permissions.includes("patient:create") ?? false;

  const patients = useQuery({
    queryKey: ["patients", query, status, page],
    queryFn: () => listPatients({ q: query, status, page }),
    // The list stays on screen while the next search resolves, so typing
    // does not make the page flicker between empty and full.
    placeholderData: keepPreviousData,
    retry: false,
  });

  const total = patients.data?.total ?? 0;
  const lastPage = patients.data?.pages ?? 1;
  const size = patients.data?.per_page ?? PAGE_SIZE;
  const from = total === 0 ? 0 : (page - 1) * size + 1;
  const to = Math.min(page * size, total);

  return (
    <Page
      title="Patients"
      blurb="Everyone registered at this clinic. Search by name, phone number or patient number."
      action={
        mayRegister && (
          <Link
            href="/patients/new"
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
          >
            <UserPlus className="size-4" />
            Register patient
          </Link>
        )
      }
    >
      <div className="mb-6 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[var(--text-subtle)]" />
          <input
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            type="search"
            aria-label="Search patients"
            placeholder="Aarti, 98200 11223, PT-000014"
            autoFocus
            className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] py-2.5 pr-9 pl-9 text-[15px] transition-colors placeholder:text-[var(--text-subtle)] hover:border-[var(--color-paper-400)]"
          />
          {typed && (
            <button
              type="button"
              onClick={() => setTyped("")}
              aria-label="Clear search"
              className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded-[4px] p-1.5 text-[var(--text-subtle)] transition-colors hover:text-[var(--text)]"
            >
              <X className="size-3.5" />
            </button>
          )}
        </div>

        <div
          role="group"
          aria-label="Filter by status"
          className="flex rounded-[var(--radius-field)] border border-[var(--border-strong)] p-0.5"
        >
          {FILTERS.map((filter) => (
            <button
              key={filter.value}
              type="button"
              onClick={() => move({ status: filter.value, page: null })}
              aria-pressed={status === filter.value}
              className={`rounded-[4px] px-3 py-1.5 text-[14px] transition-colors ${
                status === filter.value
                  ? "bg-[var(--primary)] font-medium text-[var(--primary-fg)]"
                  : "text-[var(--text-muted)] hover:text-[var(--text)]"
              }`}
            >
              {filter.label}
            </button>
          ))}
        </div>
      </div>

      {patients.isPending ? (
        <Skeleton />
      ) : patients.isError ? (
        <Empty
          heading="The register did not load"
          body="Something went wrong reaching the server. Try again in a moment."
        />
      ) : patients.data.items.length === 0 ? (
        query ? (
          <Empty
            heading={`Nobody matches “${query}”`}
            body="Try part of a name, the last few digits of a phone number, or a patient number."
          />
        ) : status === "archived" ? (
          <Empty heading="Nothing archived" body="Archived records will appear here." />
        ) : (
          <Empty
            heading="No patients yet"
            body="The first person you register gets number PT-000001."
            action={
              mayRegister
                ? { href: "/patients/new", label: "Register the first patient" }
                : undefined
            }
          />
        )
      ) : (
        <>
          <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
            {patients.data.items.map((patient) => (
              <PatientRow key={patient.id} patient={patient} />
            ))}
          </ul>

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <p className="text-[14px] text-[var(--text-muted)] tabular">
              {from}–{to} of {total}
            </p>
            {lastPage > 1 && (
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  disabled={page <= 1}
                  onClick={() => move({ page: page <= 2 ? null : String(page - 1) })}
                  className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Previous
                </button>
                <span className="text-[14px] text-[var(--text-muted)] tabular">
                  {page} of {lastPage}
                </span>
                <button
                  type="button"
                  disabled={page >= lastPage}
                  onClick={() => move({ page: String(page + 1) })}
                  className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </Page>
  );
}

function PatientRow({ patient }: { patient: PatientSummary }) {
  // Falls back to when they joined the register, so every row carries a
  // second line and the list keeps one rhythm down the page.
  const summary =
    describe(patient) ||
    `Registered ${new Date(patient.created_at).toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })}`;

  return (
    <li>
      <Link
        href={`/patients/${patient.id}` as Route}
        className="flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-[var(--surface-sunken)]"
      >
        <span
          aria-hidden
          className="grid size-9 shrink-0 place-items-center rounded-full bg-[var(--accent-wash)] text-[13px] font-semibold text-[var(--color-marigold-700)]"
        >
          {initials(patient.full_name)}
        </span>

        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-x-2 text-[15px] font-medium">
            <span className="truncate">{patient.full_name}</span>
            {patient.preferred_name && (
              <span className="truncate text-[13px] font-normal text-[var(--text-muted)]">
                “{patient.preferred_name}”
              </span>
            )}
            {patient.status === "archived" && (
              <span className="rounded-full bg-[var(--surface-sunken)] px-2 py-0.5 text-[12px] font-normal text-[var(--text-muted)]">
                archived
              </span>
            )}
            {patient.allergy_count > 0 && (
              <span
                title={`${patient.allergy_count} recorded ${
                  patient.allergy_count === 1 ? "allergy" : "allergies"
                }`}
                className="inline-flex items-center gap-1 text-[12px] font-normal text-[var(--color-state-noshow)]"
              >
                <TriangleAlert className="size-3" />
                {patient.allergy_count}
              </span>
            )}
          </p>
          <p className="truncate text-[13px] text-[var(--text-muted)]">{summary}</p>
        </div>

        <p className="hidden w-36 shrink-0 text-right text-[14px] text-[var(--text-muted)] tabular sm:block">
          {readablePhone(patient.phone)}
        </p>
        <p className="w-24 shrink-0 text-right font-mono text-[13px] text-[var(--text-subtle)]">
          {patient.patient_number}
        </p>
      </Link>
    </li>
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
          <span className="size-9 shrink-0 animate-pulse rounded-full bg-[var(--surface-sunken)]" />
          <span className="h-4 flex-1 animate-pulse rounded bg-[var(--surface-sunken)]" />
          <span className="hidden h-4 w-28 animate-pulse rounded bg-[var(--surface-sunken)] sm:block" />
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
  action?: { href: string; label: string };
}) {
  return (
    <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-14 text-center">
      <h2 className="text-[17px] font-semibold tracking-tight text-balance">{heading}</h2>
      <p className="mx-auto mt-1.5 max-w-[46ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
        {body}
      </p>
      {action && (
        <Link
          href={action.href as Route}
          className="mt-5 inline-flex rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
        >
          {action.label}
        </Link>
      )}
    </div>
  );
}
