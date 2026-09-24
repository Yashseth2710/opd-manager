"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Download, Loader2 } from "lucide-react";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Permitted } from "@/components/layout/permitted";
import { DayChart, HourChart } from "@/components/reports/charts";
import { Against, Headlines, Panel, Quiet } from "@/components/reports/parts";
import { RangePicker, wrongWith } from "@/components/reports/range";
import { Charges, Doctors, Methods, Tests } from "@/components/reports/tables";
import { longDate, shortDate } from "@/lib/appointments";
import { money } from "@/lib/clinic";
import { localDay } from "@/lib/prescriptions";
import {
  dayBookHref,
  getReport,
  RANGES,
  type Range,
  type Report,
  type Span,
} from "@/lib/reports";

export default function ReportsPage() {
  return (
    <Permitted permission="reports:read">
      <Suspense fallback={<Working />}>
        <Reports />
      </Suspense>
    </Permitted>
  );
}

function Working() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center gap-3 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">Adding it up…</span>
    </div>
  );
}

function Reports() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const today = localDay(new Date().toISOString());

  const asked = params.get("range");
  const range: Range = RANGES.some((each) => each.value === asked) ? (asked as Range) : "week";
  const from = params.get("from") ?? today;
  const to = params.get("to") ?? today;
  const [showing, setShowing] = useState<"patients" | "money">("patients");

  const put = (next: URLSearchParams) => {
    const query = next.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}` as Route, { scroll: false });
  };

  const chooseRange = (picked: Range) => {
    const next = new URLSearchParams();
    next.set("range", picked);
    if (picked === "custom") {
      next.set("from", from);
      next.set("to", to);
    }
    put(next);
  };

  const chooseDates = (first: string, last: string) => {
    put(new URLSearchParams({ range: "custom", from: first, to: last }));
  };

  const usable = range !== "custom" || wrongWith(from, to) === null;
  const report = useQuery({
    queryKey: [
      "reports",
      { range, from: range === "custom" ? from : null, to: range === "custom" ? to : null },
    ],
    queryFn: () => getReport(range, from, to),
    enabled: usable,
    retry: false,
    // Today's figures move while the page is open; a month's do not.
    refetchInterval: range === "today" ? 60_000 : false,
  });

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-10 lg:py-14">
      <header className="mb-6 flex flex-col gap-4">
        <div>
          <h1 className="text-[26px] leading-tight font-semibold tracking-tight">Reports</h1>
          <p className="mt-1.5 text-[15px] leading-relaxed text-[var(--text-muted)]">
            {report.data ? said(report.data) : "How the clinic has been doing."}
          </p>
        </div>
        <RangePicker
          range={range}
          from={from}
          to={to}
          today={today}
          onRange={chooseRange}
          onDates={chooseDates}
        />
      </header>

      {!usable ? (
        <Nothing
          title="Nothing to show yet"
          words={`${wrongWith(from, to)} Put that right above and the figures follow.`}
        />
      ) : report.isPending ? (
        <Skeleton />
      ) : report.isError && !report.data ? (
        <Nothing
          title="The figures did not load"
          words="Something went wrong reaching the server. Try again in a moment."
          onRetry={() => void report.refetch()}
        />
      ) : report.data.view === "unlinked" ? (
        <Nothing
          title="Your account has nothing to report on yet"
          words="It is not linked to a doctor profile. An administrator can link it from your profile under Doctors, and your own figures will show here."
        />
      ) : (
        <Figures
          report={report.data}
          showing={showing}
          onShowing={setShowing}
          stale={report.isError}
        />
      )}
    </div>
  );
}

function said(report: Report): string {
  const { span } = report;
  const days =
    span.days === 1
      ? longDate(span.first_day)
      : `${shortDate(span.first_day)} to ${shortDate(span.last_day)}`;
  return report.view === "doctor"
    ? `Your own patients and bills, ${days}.`
    : `${days}, across the clinic.`;
}

function Figures({
  report,
  showing,
  onShowing,
  stale,
}: {
  report: Report;
  showing: "patients" | "money";
  onShowing: (showing: "patients" | "money") => void;
  stale: boolean;
}) {
  const { currency, span } = report;
  const quiet = report.seen === 0 && report.net === "0.00" && report.bills_issued === 0;

  if (quiet) {
    return (
      <Nothing
        title={span.days === 1 ? "Nothing on this day" : "Nothing in these days"}
        words="No patients were seen and no money came in. Try a longer stretch, or an earlier one."
      />
    );
  }

  return (
    <div className="flex flex-col gap-6">
      {stale && (
        <p
          role="alert"
          className="flex items-center gap-2 text-[13px] text-[var(--color-state-noshow)]"
        >
          <AlertTriangle className="size-3.5" />
          Lost touch with the server. What is shown may be out of date.
        </p>
      )}

      <Headlines
        figures={[
          {
            label: "Patients seen",
            value: String(report.seen),
            note: <Against now={report.seen} before={report.before.seen} words="was" />,
          },
          {
            label: "Money taken",
            value: money(report.net, currency),
            note: (
              <Against
                now={Number(report.net)}
                before={Number(report.before.collected)}
                currency={currency}
                words="was"
              />
            ),
          },
          {
            label: "New patients",
            value: String(report.new_patients),
            note:
              report.view === "doctor"
                ? "Counted for the clinic, not per doctor"
                : report.walk_ins > 0
                  ? `${report.walk_ins} of those seen walked in`
                  : "Everyone seen had booked",
          },
          {
            label: "Per patient seen",
            value: money(report.per_patient, currency),
            note:
              report.no_shows > 0
                ? `${report.no_shows} did not stay to be seen`
                : "Nobody left unseen",
          },
        ]}
      />

      {span.days > 1 && (
        <Panel
          id="day-by-day"
          title="Day by day"
          action={
            <div
              className="flex gap-1 rounded-full bg-[var(--surface-sunken)] p-0.5"
              role="group"
              aria-label="What the columns show"
            >
              {(["patients", "money"] as const).map((which) => (
                <button
                  key={which}
                  type="button"
                  aria-pressed={showing === which}
                  onClick={() => onShowing(which)}
                  className={`rounded-full px-3 py-1 text-[13px] transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)] ${
                    showing === which
                      ? "bg-[var(--surface)] font-medium shadow-[0_1px_2px_rgba(0,0,0,0.08)]"
                      : "text-[var(--text-muted)] hover:text-[var(--text)]"
                  }`}
                >
                  {which === "patients" ? "Patients" : "Money"}
                </button>
              ))}
            </div>
          }
        >
          <DayChart days={report.days} showing={showing} currency={currency} />
        </Panel>
      )}

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
        <Panel
          id="money"
          title="How it was paid"
          action={
            report.methods.length > 0 ? (
              <a
                href={dayBookHref(span.range, span.first_day, span.last_day)}
                className="inline-flex items-center gap-1.5 text-[13px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
              >
                <Download className="size-3.5" />
                Day book
              </a>
            ) : undefined
          }
        >
          {report.methods.length === 0 ? (
            <Quiet>Nothing came in over these days.</Quiet>
          ) : (
            <Methods methods={report.methods} currency={currency} net={report.net} />
          )}
          <Ledger report={report} />
        </Panel>

        <Panel
          id="doctors"
          title={report.view === "doctor" ? "Your line" : "Each doctor"}
          blurb={
            report.view === "doctor"
              ? undefined
              : "Busiest first. Money is what came in against their bills."
          }
        >
          {report.doctors.length === 0 ? (
            <Quiet>Nobody was seen over these days.</Quiet>
          ) : (
            <Doctors
              doctors={report.doctors}
              currency={currency}
              showMoney={report.view !== "doctor"}
            />
          )}
        </Panel>
      </div>

      <Panel id="hours" title="When people come" blurb="By the hour they arrive at the desk.">
        {report.hours.length === 0 ? (
          <Quiet>Nobody checked in over these days.</Quiet>
        ) : (
          <HourChart hours={report.hours} />
        )}
      </Panel>

      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
        <Panel id="charges" title="What the bills were for" blurb="Biggest earner first.">
          {report.charges.length === 0 ? (
            <Quiet>No bills were handed over these days.</Quiet>
          ) : (
            <Charges charges={report.charges} currency={currency} />
          )}
        </Panel>

        <Panel id="tests" title="Tests ordered" blurb="Most often asked for first.">
          {report.tests.length === 0 ? (
            <Quiet>No tests were ordered over these days.</Quiet>
          ) : (
            <Tests tests={report.tests} />
          )}
        </Panel>
      </div>
    </div>
  );
}

/** The lines under the methods that put the takings in context. */
function Ledger({ report }: { report: Report }) {
  const { currency } = report;
  return (
    <div className="mt-auto border-t border-[var(--border)] px-5 py-3 text-[14px] leading-relaxed text-[var(--text-muted)]">
      <p>
        {report.bills_issued === 0
          ? "No bills were handed over."
          : `${report.bills_issued} ${report.bills_issued === 1 ? "bill" : "bills"} handed over, coming to `}
        {report.bills_issued > 0 && (
          <span className="font-mono tabular">{money(report.billed, currency)}</span>
        )}
        {report.bills_issued > 0 && "."}
      </p>
      {report.online !== "0.00" && (
        <p className="mt-1">
          <span className="font-mono tabular">{money(report.online, currency)}</span> of it was
          paid from a link, so nobody at the desk handled it.
        </p>
      )}
      {report.outstanding_bills > 0 && (
        <p className="mt-1">
          <span className="font-mono font-semibold tabular text-[var(--text)]">
            {money(report.outstanding, currency)}
          </span>{" "}
          is still owed on {report.outstanding_bills}{" "}
          {report.outstanding_bills === 1 ? "bill" : "bills"}, whenever they were raised.
        </p>
      )}
    </div>
  );
}

function Nothing({
  title,
  words,
  onRetry,
}: {
  title: string;
  words: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-12 text-center">
      <h2 className="text-[17px] font-semibold tracking-tight">{title}</h2>
      <p className="mx-auto mt-1.5 max-w-[52ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
        {words}
      </p>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-5 inline-flex rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--accent-fg)] transition hover:brightness-[1.06]"
        >
          Try again
        </button>
      )}
    </div>
  );
}

function Skeleton() {
  return (
    <div aria-hidden className="flex flex-col gap-6">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--border)] sm:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <div key={index} className="bg-[var(--surface)] px-5 py-4">
            <span className="block h-3.5 w-20 animate-pulse rounded bg-[var(--surface-sunken)]" />
            <span className="mt-2 block h-6 w-16 animate-pulse rounded bg-[var(--surface-sunken)]" />
          </div>
        ))}
      </div>
      <div className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4">
        <span className="block h-4 w-28 animate-pulse rounded bg-[var(--surface-sunken)]" />
        <span className="mt-4 block h-40 w-full animate-pulse rounded bg-[var(--surface-sunken)]" />
      </div>
      <div className="grid grid-cols-1 items-start gap-6 lg:grid-cols-2">
        {Array.from({ length: 2 }, (_, index) => (
          <div
            key={index}
            className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
          >
            <span className="block h-4 w-32 animate-pulse rounded bg-[var(--surface-sunken)]" />
            {Array.from({ length: 4 }, (_, row) => (
              <span
                key={row}
                className="mt-4 block h-6 w-full animate-pulse rounded bg-[var(--surface-sunken)]"
              />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
