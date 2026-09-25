"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { Page } from "@/components/layout/shell";
import { Empty, Failed, Loading, StatusBadge } from "@/components/platform/parts";
import { sinceThen } from "@/lib/notifications";
import { describeStanding, getMetrics, listClinics, whole, type Metrics } from "@/lib/platform";

export default function OverviewPage() {
  const metrics = useQuery({ queryKey: ["platform", "metrics"], queryFn: getMetrics });
  const newest = useQuery({
    queryKey: ["platform", "clinics", "newest"],
    queryFn: () => listClinics({ per_page: 5 }),
  });

  return (
    <Page
      title="Overview"
      blurb="Every clinic on OPD Manager, counted. Nothing here names a patient."
      wide
    >
      {metrics.isPending ? (
        <Loading what="Counting across every clinic…" />
      ) : metrics.isError ? (
        <Failed what="The numbers" retry={() => void metrics.refetch()} />
      ) : metrics.data.clinics === 0 ? (
        <Empty
          heading="No clinics yet"
          body="The first one shows up here the moment somebody registers a clinic."
        />
      ) : (
        <div className="flex flex-col gap-8">
          <Figures metrics={metrics.data} />
          <div className="grid gap-8 lg:grid-cols-[3fr_2fr]">
            <Signups metrics={metrics.data} />
            <PlanShare metrics={metrics.data} />
          </div>

          <section aria-labelledby="newest">
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <h2 id="newest" className="text-[17px] font-semibold tracking-tight">
                Newest clinics
              </h2>
              <Link
                href={"/admin/clinics" as Route}
                className="inline-flex items-center gap-1 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
              >
                Every clinic
                <ArrowRight className="size-3.5" />
              </Link>
            </div>
            {newest.isPending ? (
              <Loading what="Finding the newest…" />
            ) : newest.isError ? (
              <Failed what="The newest clinics" retry={() => void newest.refetch()} />
            ) : (
              <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
                {newest.data.items.map((clinic) => (
                  <li key={clinic.id}>
                    <Link
                      href={`/admin/clinics/${clinic.id}` as Route}
                      className="flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3.5 transition-colors hover:bg-[var(--surface-sunken)]"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[15px] font-medium">
                          {clinic.name}
                        </span>
                        <span className="block truncate text-[13px] text-[var(--text-muted)]">
                          {clinic.owner?.email ?? "No administrator"}, joined{" "}
                          {sinceThen(clinic.created_at)}
                        </span>
                      </span>
                      <span className="text-[13px] text-[var(--text-muted)]">
                        {describeStanding(clinic.standing)}
                      </span>
                      <StatusBadge status={clinic.status} />
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>
      )}
    </Page>
  );
}

function Figures({ metrics }: { metrics: Metrics }) {
  const { statuses } = metrics;
  const figures = [
    {
      label: "Clinics",
      value: metrics.clinics,
      detail: `${whole(statuses.active)} running, ${whole(statuses.pending)} setting up${
        statuses.suspended ? `, ${whole(statuses.suspended)} suspended` : ""
      }`,
    },
    {
      label: "Joined this month",
      value: metrics.new_clinics_this_month,
      detail: `${whole(metrics.on_trial)} trying a plan`,
    },
    {
      label: "Staff accounts",
      value: metrics.accounts,
      detail: `${whole(metrics.doctors)} doctors seeing patients`,
    },
    { label: "Patients on the books", value: metrics.patients, detail: "Archived not counted" },
    {
      label: "Bookings this month",
      value: metrics.appointments_this_month,
      detail: "Made since the 1st, UTC",
    },
  ];

  return (
    <dl className="grid grid-cols-2 overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] sm:grid-cols-3 lg:grid-cols-5">
      {figures.map((figure) => (
        <div
          key={figure.label}
          className="border-[var(--border)] px-5 py-4 [&:not(:last-child)]:border-b sm:border-r lg:border-b-0"
        >
          <dt className="text-[13px] text-[var(--text-muted)]">{figure.label}</dt>
          <dd className="mt-1 text-[26px] leading-none font-semibold tracking-tight tabular">
            {whole(figure.value)}
          </dd>
          <dd className="mt-1.5 text-[12px] leading-snug text-[var(--text-subtle)]">
            {figure.detail}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function Signups({ metrics }: { metrics: Metrics }) {
  const highest = Math.max(...metrics.signups.map((week) => week.clinics), 1);
  const label = (starts: string) =>
    new Date(`${starts}T00:00:00`).toLocaleDateString("en-IN", {
      day: "numeric",
      month: "short",
    });

  return (
    <section aria-labelledby="signups">
      <h2 id="signups" className="text-[17px] font-semibold tracking-tight">
        New clinics, week by week
      </h2>
      <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
        The last twelve weeks, Monday to Sunday.
      </p>
      <div className="mt-4 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-4 pt-5 pb-3">
        <ol className="flex h-36 items-end gap-[5px]" aria-label="New clinics each week">
          {metrics.signups.map((week) => (
            <li
              key={week.starts}
              className="group relative flex h-full flex-1 flex-col justify-end"
              aria-label={`Week of ${label(week.starts)}: ${week.clinics} ${week.clinics === 1 ? "clinic" : "clinics"}`}
            >
              <span className="pointer-events-none absolute -top-1 left-1/2 -translate-x-1/2 -translate-y-full rounded-[4px] bg-[var(--text)] px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap text-[var(--background)] opacity-0 transition-opacity group-hover:opacity-100">
                {week.clinics}
              </span>
              <span
                className="block w-full rounded-t-[3px] transition-[height] duration-500 ease-[cubic-bezier(0.32,0.72,0,1)]"
                style={{
                  height: `${week.clinics ? Math.max((week.clinics / highest) * 100, 4) : 0}%`,
                  backgroundColor: "var(--color-marigold-400)",
                }}
              />
              <span aria-hidden className="block h-px w-full bg-[var(--border-strong)]" />
            </li>
          ))}
        </ol>
        <p className="mt-2 flex justify-between text-[11px] text-[var(--text-subtle)] tabular">
          <span>{label(metrics.signups[0]?.starts ?? "")}</span>
          <span>This week</span>
        </p>
      </div>
    </section>
  );
}

function PlanShare({ metrics }: { metrics: Metrics }) {
  const total = Math.max(metrics.clinics, 1);
  return (
    <section aria-labelledby="plan-share">
      <h2 id="plan-share" className="text-[17px] font-semibold tracking-tight">
        Clinics on each plan
      </h2>
      <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
        A clinic trying a plan counts on that plan until its trial ends.
      </p>
      <ul className="mt-4 flex flex-col gap-3.5 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4">
        {metrics.plans.map((plan) => (
          <li key={plan.id}>
            <Link
              href={`/admin/clinics?plan=${plan.id}` as Route}
              className="group block rounded-[4px] focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-[var(--focus-ring)]"
            >
              <span className="flex items-baseline justify-between text-[14px]">
                <span className="font-medium group-hover:underline group-hover:underline-offset-2">
                  {plan.name}
                </span>
                <span className="text-[var(--text-muted)] tabular">{whole(plan.clinics)}</span>
              </span>
              <span className="mt-1.5 block h-2 overflow-hidden rounded-full bg-[var(--surface-sunken)]">
                <span
                  className="block h-full rounded-full bg-[var(--primary)] dark:bg-[var(--accent)]"
                  style={{ width: `${(plan.clinics / total) * 100}%` }}
                />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
