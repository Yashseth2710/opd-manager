"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { CalendarRange, Loader2, Search, Stethoscope, UserPlus, X } from "lucide-react";
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
  listDoctors,
  listSpecialities,
  PAGE_SIZE,
  type DoctorSummary,
} from "@/lib/doctors";

type Status = "active" | "inactive" | "all";

const FILTERS: { value: Status; label: string }[] = [
  { value: "active", label: "Practising" },
  { value: "inactive", label: "Stood down" },
  { value: "all", label: "Everyone" },
];

export default function DoctorsPage() {
  return (
    <Permitted permission="doctor:read">
      <Suspense fallback={<Waiting />}>
        <Panel />
      </Suspense>
    </Permitted>
  );
}

function Waiting() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">Opening the list…</span>
    </div>
  );
}

function Panel() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const query = params.get("q") ?? "";
  const speciality = params.get("speciality") ?? "";
  // Read defensively: these come out of the address bar, which anybody can
  // type into, and a filter of "garbage" should show the list rather than
  // an error the API was right to raise.
  const asked = params.get("status");
  const status: Status = FILTERS.some((filter) => filter.value === asked)
    ? (asked as Status)
    : "active";
  const asNumber = Number(params.get("page"));
  const page = Number.isFinite(asNumber) ? Math.max(Math.trunc(asNumber), 1) : 1;

  // Typed separately from the query in the address bar, which follows a beat
  // later. Keeping the search in the URL is what lets somebody open a
  // profile and come back to the list exactly as they left it.
  const [typed, setTyped] = useState(query);
  const [mirrored, setMirrored] = useState(query);

  // The address bar can change without anybody typing — the back button, a
  // pasted link — and the box has to follow it when it does.
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
  const mayManage = session.data?.permissions.includes("doctor:manage") ?? false;

  const specialities = useQuery({
    queryKey: ["specialities", status],
    queryFn: () => listSpecialities(status),
    retry: false,
  });

  const doctors = useQuery({
    queryKey: ["doctors", query, speciality, status, page],
    queryFn: () => listDoctors({ q: query, speciality, status, page }),
    placeholderData: keepPreviousData,
    retry: false,
  });

  const total = doctors.data?.total ?? 0;
  const lastPage = doctors.data?.pages ?? 1;
  const size = doctors.data?.per_page ?? PAGE_SIZE;
  const from = total === 0 ? 0 : (page - 1) * size + 1;
  const to = Math.min(page * size, total);
  const offered = specialities.data ?? [];

  return (
    <Page
      title="Doctors"
      blurb="Everyone who sees patients here, what they charge, and the hours they sit."
      action={
        mayManage && (
          <Link
            href="/doctors/new"
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
          >
            <UserPlus className="size-4" />
            Add a doctor
          </Link>
        )
      }
    >
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[var(--text-subtle)]" />
          <input
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            type="search"
            aria-label="Search doctors"
            placeholder="Iyer, paediatrics, room 3"
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

      {/* Built from what this clinic actually offers, rather than a fixed
          list every clinic has to pick the wrong answer from. */}
      {offered.length > 1 && (
        <div className="mb-6 flex flex-wrap gap-1.5">
          <Chip
            label="All specialities"
            active={!speciality}
            onClick={() => move({ speciality: null, page: null })}
          />
          {offered.map((name) => (
            <Chip
              key={name}
              label={name}
              active={speciality.toLowerCase() === name.toLowerCase()}
              onClick={() => move({ speciality: name, page: null })}
            />
          ))}
        </div>
      )}

      {doctors.isPending ? (
        <Skeleton />
      ) : doctors.isError ? (
        <Empty
          heading="The list did not load"
          body="Something went wrong reaching the server. Try again in a moment."
        />
      ) : doctors.data.items.length === 0 ? (
        query || speciality ? (
          <Empty
            heading={`Nobody matches ${query ? `“${query}”` : speciality}`}
            body="Try part of a surname, a speciality, or a room number."
          />
        ) : status === "inactive" ? (
          <Empty
            heading="Nobody stood down"
            body="Doctors who stop practising here will appear under this filter."
          />
        ) : (
          <Empty
            heading="No doctors yet"
            body="Add the people who see patients, then give each of them the hours they sit."
            action={
              mayManage ? { href: "/doctors/new", label: "Add the first doctor" } : undefined
            }
          />
        )
      ) : (
        <>
          <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
            {doctors.data.items.map((doctor) => (
              <DoctorRow key={doctor.id} doctor={doctor} />
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
          ? "border-[var(--color-marigold-400)] bg-[var(--accent-wash)] font-medium text-[var(--color-marigold-700)]"
          : "border-[var(--border-strong)] text-[var(--text-muted)] hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
      }`}
    >
      {label}
    </button>
  );
}

function DoctorRow({ doctor }: { doctor: DoctorSummary }) {
  // Falls back to the room, then to when they joined, so every row carries
  // a second line and the list keeps one rhythm down the page.
  const summary =
    describe(doctor) ||
    (doctor.room ? `Room ${doctor.room}` : "") ||
    `Added ${new Date(doctor.created_at).toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
      year: "numeric",
    })}`;

  return (
    <li>
      <Link
        href={`/doctors/${doctor.id}` as Route}
        className="flex items-center gap-4 px-5 py-3.5 transition-colors hover:bg-[var(--surface-sunken)]"
      >
        <span
          aria-hidden
          className="grid size-9 shrink-0 place-items-center rounded-full bg-[var(--accent-wash)] text-[13px] font-semibold text-[var(--color-marigold-700)]"
        >
          {initials(doctor.full_name)}
        </span>

        <div className="min-w-0 flex-1">
          <p className="flex flex-wrap items-center gap-x-2 text-[15px] font-medium">
            <span className="truncate">{doctor.display_name}</span>
            {doctor.status === "inactive" && (
              <span className="rounded-full bg-[var(--surface-sunken)] px-2 py-0.5 text-[12px] font-normal text-[var(--text-muted)]">
                stood down
              </span>
            )}
            {doctor.working_days === 0 && doctor.status === "active" && (
              <span
                title="No weekly hours set, so nobody can be booked in with them"
                className="inline-flex items-center gap-1 text-[12px] font-normal text-[var(--color-state-waiting)]"
              >
                <CalendarRange className="size-3" />
                no hours
              </span>
            )}
          </p>
          <p className="truncate text-[13px] text-[var(--text-muted)]">{summary}</p>
        </div>

        <p className="hidden w-28 shrink-0 text-right text-[14px] text-[var(--text-muted)] tabular sm:block">
          {doctor.working_days > 0 &&
            `${doctor.working_days} ${doctor.working_days === 1 ? "day" : "days"}`}
        </p>
        <p className="w-20 shrink-0 text-right text-[14px] tabular">
          ₹{doctor.consultation_fee}
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
      {Array.from({ length: 5 }, (_, index) => (
        <li key={index} className="flex items-center gap-4 px-5 py-3.5">
          <span className="size-9 shrink-0 animate-pulse rounded-full bg-[var(--surface-sunken)]" />
          <span className="h-4 flex-1 animate-pulse rounded bg-[var(--surface-sunken)]" />
          <span className="hidden h-4 w-20 animate-pulse rounded bg-[var(--surface-sunken)] sm:block" />
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
      <Stethoscope aria-hidden className="mx-auto mb-3 size-6 text-[var(--text-subtle)]" />
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
