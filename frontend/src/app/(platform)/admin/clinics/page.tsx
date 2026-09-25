"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search, X } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Page } from "@/components/layout/shell";
import { Empty, Failed, Loading, StatusBadge } from "@/components/platform/parts";
import { sinceThen } from "@/lib/notifications";
import {
  describeStanding,
  listClinics,
  listPlans,
  PER_PAGE,
  STATUS_WORDS,
  whole,
  type ClinicRow,
  type ClinicStatus,
  type Sort,
} from "@/lib/platform";

const TABS: { value: ClinicStatus | null; label: string; key: "all" | ClinicStatus }[] = [
  { value: null, label: "All", key: "all" },
  { value: "active", label: STATUS_WORDS.active, key: "active" },
  { value: "pending", label: STATUS_WORDS.pending, key: "pending" },
  { value: "suspended", label: STATUS_WORDS.suspended, key: "suspended" },
];

const SORTS: { value: Sort; label: string }[] = [
  { value: "-created_at", label: "Newest first" },
  { value: "created_at", label: "Oldest first" },
  { value: "name", label: "By name" },
];

const FIELD =
  "rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2.5 text-[14px] transition-colors hover:border-[var(--color-paper-400)]";

export default function ClinicsPage() {
  return (
    <Suspense fallback={<Loading what="Opening the list…" />}>
      <Clinics />
    </Suspense>
  );
}

function Clinics() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  // Read defensively: these come out of the address bar.
  const query = params.get("q") ?? "";
  const askedStatus = params.get("status");
  const status = TABS.some((tab) => tab.value === askedStatus)
    ? (askedStatus as ClinicStatus)
    : null;
  const askedSort = params.get("sort");
  const sort = SORTS.some((option) => option.value === askedSort)
    ? (askedSort as Sort)
    : "-created_at";
  const askedPlan = params.get("plan");
  const plan = askedPlan && /^[0-9a-f-]{36}$/i.test(askedPlan) ? askedPlan : null;
  const asNumber = Number(params.get("page"));
  const page = Number.isFinite(asNumber) ? Math.max(Math.trunc(asNumber), 1) : 1;

  const [typed, setTyped] = useState(query);
  const [mirrored, setMirrored] = useState(query);
  if (mirrored !== query) {
    setMirrored(query);
    setTyped(query);
  }

  // Set the moment somebody opens a row. A search still waiting to be
  // applied would otherwise land while the next page loads and put them
  // back on the list they had just left.
  const leaving = useRef(false);

  useEffect(() => {
    if (typed === query) return;
    const timer = setTimeout(() => {
      if (leaving.current) return;
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

  const plans = useQuery({ queryKey: ["platform", "plans"], queryFn: listPlans });
  const clinics = useQuery({
    queryKey: ["platform", "clinics", query, status, plan, sort, page],
    queryFn: () => listClinics({ q: query, status, plan, sort, page }),
    placeholderData: keepPreviousData,
  });

  const total = clinics.data?.total ?? 0;
  const lastPage = clinics.data?.pages ?? 1;
  const from = total === 0 ? 0 : (page - 1) * PER_PAGE + 1;
  const to = Math.min(page * PER_PAGE, total);
  const planName = plans.data?.find((option) => option.id === plan)?.name;
  const narrowed = Boolean(query || status || plan);

  return (
    <Page
      title="Clinics"
      blurb="Every clinic that has registered, with who runs it and what it is on."
      wide
    >
      <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[var(--text-subtle)]" />
          <input
            value={typed}
            onChange={(event) => setTyped(event.target.value)}
            type="search"
            aria-label="Search clinics"
            placeholder="Clinic name, web address or the owner's email"
            maxLength={100}
            className={`w-full py-2.5 pr-9 pl-9 text-[15px] placeholder:text-[var(--text-subtle)] ${FIELD}`}
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
        <div className="flex gap-3">
          <select
            aria-label="Plan"
            value={plan ?? ""}
            onChange={(event) => move({ plan: event.target.value || null, page: null })}
            className={`min-w-0 flex-1 md:w-40 md:flex-none ${FIELD}`}
          >
            <option value="">Any plan</option>
            {plans.data?.map((option) => (
              <option key={option.id} value={option.id}>
                {option.name}
              </option>
            ))}
          </select>
          <select
            aria-label="Order"
            value={sort}
            onChange={(event) =>
              move({ sort: event.target.value === "-created_at" ? null : event.target.value })
            }
            className={`min-w-0 flex-1 md:w-40 md:flex-none ${FIELD}`}
          >
            {SORTS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div
        role="group"
        aria-label="Filter by status"
        className="mb-6 flex gap-1 overflow-x-auto border-b border-[var(--border)]"
      >
        {TABS.map((tab) => {
          const chosen = status === tab.value;
          const count = clinics.data?.statuses[tab.key];
          return (
            <button
              key={tab.key}
              type="button"
              aria-pressed={chosen}
              onClick={() => move({ status: tab.value, page: null })}
              className={`-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-[14px] whitespace-nowrap transition-colors ${
                chosen
                  ? "border-[var(--accent)] font-medium text-[var(--text)]"
                  : "border-transparent text-[var(--text-muted)] hover:text-[var(--text)]"
              }`}
            >
              {tab.label}
              {count !== undefined && (
                <span className="rounded-full bg-[var(--surface-sunken)] px-1.5 text-[12px] text-[var(--text-muted)] tabular">
                  {whole(count)}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {clinics.isPending ? (
        <Loading what="Finding clinics…" />
      ) : clinics.isError ? (
        <Failed what="The list of clinics" retry={() => void clinics.refetch()} />
      ) : clinics.data.items.length === 0 ? (
        page > lastPage && total > 0 ? (
          <Empty
            heading={`Nothing on page ${page}`}
            body={`The list stops at page ${lastPage}.`}
            action={{ label: "Back to the first page", onClick: () => move({ page: null }) }}
          />
        ) : narrowed ? (
          <Empty
            heading="No clinic matches"
            body={[
              query && `Nothing is called or run by “${query}”.`,
              status &&
                `Looking only at clinics that are ${STATUS_WORDS[status].toLowerCase()}.`,
              planName && `Looking only at the ${planName} plan.`,
            ]
              .filter(Boolean)
              .join(" ")}
            action={{
              label: "Show every clinic",
              onClick: () => {
                setTyped("");
                router.replace(pathname as Route, { scroll: false });
              },
            }}
          />
        ) : (
          <Empty
            heading="No clinics yet"
            body="A clinic appears here the moment somebody registers one."
          />
        )
      ) : (
        <>
          <div
            className={`overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] transition-opacity ${
              clinics.isPlaceholderData ? "opacity-60" : ""
            }`}
          >
            <div
              aria-hidden
              className="hidden grid-cols-[minmax(0,2.2fr)_minmax(0,1.3fr)_repeat(4,4.5rem)_minmax(0,1fr)_6.5rem] gap-4 border-b border-[var(--border)] bg-[var(--surface-sunken)] px-5 py-2 text-[12px] text-[var(--text-muted)] lg:grid"
            >
              <span>Clinic</span>
              <span>Plan</span>
              <span className="text-right">Doctors</span>
              <span className="text-right">Staff</span>
              <span className="text-right">Patients</span>
              <span className="text-right">Bookings</span>
              <span>Last sign-in</span>
              <span>Status</span>
            </div>
            <ul
              className="divide-y divide-[var(--border)]"
              onClickCapture={(event) => {
                const plain =
                  event.button === 0 &&
                  !event.metaKey &&
                  !event.ctrlKey &&
                  !event.shiftKey &&
                  !event.altKey;
                if (plain) leaving.current = true;
              }}
            >
              {clinics.data.items.map((clinic) => (
                <Row key={clinic.id} clinic={clinic} />
              ))}
            </ul>
          </div>

          <div className="mt-5 flex flex-wrap items-center justify-between gap-3">
            <p className="text-[14px] text-[var(--text-muted)] tabular">
              {from}–{to} of {whole(total)}
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

function Row({ clinic }: { clinic: ClinicRow }) {
  const seen = clinic.last_active_at ? sinceThen(clinic.last_active_at) : "Never";
  return (
    <li>
      <Link
        href={`/admin/clinics/${clinic.id}` as Route}
        className="grid gap-x-4 gap-y-1.5 px-5 py-3.5 transition-colors hover:bg-[var(--surface-sunken)] lg:grid-cols-[minmax(0,2.2fr)_minmax(0,1.3fr)_repeat(4,4.5rem)_minmax(0,1fr)_6.5rem] lg:items-center"
      >
        <span className="flex min-w-0 items-start justify-between gap-3 lg:block">
          <span className="min-w-0">
            <span className="block truncate text-[15px] font-medium">{clinic.name}</span>
            <span className="block truncate text-[13px] text-[var(--text-muted)]">
              {clinic.owner?.email ?? "No administrator left"}
            </span>
          </span>
          <span className="lg:hidden">
            <StatusBadge status={clinic.status} />
          </span>
        </span>
        <span
          className={`truncate text-[13px] ${
            clinic.standing.trial_over
              ? "text-[var(--color-state-waiting)]"
              : "text-[var(--text-muted)]"
          }`}
        >
          {describeStanding(clinic.standing)}
        </span>
        <span className="text-[13px] text-[var(--text-muted)] tabular lg:hidden">
          {whole(clinic.doctors)} {clinic.doctors === 1 ? "doctor" : "doctors"},{" "}
          {whole(clinic.staff)} staff, {whole(clinic.patients)}{" "}
          {clinic.patients === 1 ? "patient" : "patients"},{" "}
          {whole(clinic.appointments_this_month)} bookings this month. Last sign-in{" "}
          {seen.toLowerCase()}.
        </span>
        {[clinic.doctors, clinic.staff, clinic.patients, clinic.appointments_this_month].map(
          (value, index) => (
            <span key={index} className="hidden text-right text-[14px] tabular lg:block">
              {whole(value)}
            </span>
          ),
        )}
        <span className="hidden truncate text-[13px] text-[var(--text-muted)] lg:block">
          {seen}
        </span>
        <span className="hidden lg:block">
          <StatusBadge status={clinic.status} />
        </span>
      </Link>
    </li>
  );
}
