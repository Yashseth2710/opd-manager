"use client";

import type { Route } from "next";
import Link from "next/link";
import { Amount } from "@/components/billing/parts";
import { METHOD_WORDS, type MethodTotal } from "@/lib/billing";
import { Share } from "@/components/reports/parts";
import type { ChargeLine, DoctorLine, TestLine } from "@/lib/reports";

const ROW = "grid items-baseline gap-x-4 px-5 py-2.5";

export function Methods({
  methods,
  currency,
  net,
}: {
  methods: MethodTotal[];
  currency: string;
  net: string;
}) {
  const biggest = Math.max(1, ...methods.map((each) => Math.abs(Number(each.net))));
  return (
    <ul className="divide-y divide-[var(--border)]" role="list">
      {methods.map((each) => (
        <li
          key={each.method}
          className={`${ROW} grid-cols-[1fr_auto]`}
          style={{ gridTemplateAreas: '"name total" "bar bar"' }}
        >
          <span className="text-[15px]" style={{ gridArea: "name" }}>
            {METHOD_WORDS[each.method]}
            <span className="ml-2 text-[13px] text-[var(--text-muted)] tabular">
              {each.count === 0
                ? "only given back"
                : `${each.count} ${each.count === 1 ? "payment" : "payments"}`}
            </span>
          </span>
          <span className="text-right" style={{ gridArea: "total" }}>
            <Amount value={each.net} currency={currency} className="text-[15px]" />
            {each.refunded !== "0.00" && (
              <span className="block text-[13px] text-[var(--text-muted)]">
                after <Amount value={each.refunded} currency={currency} /> back
              </span>
            )}
          </span>
          <span style={{ gridArea: "bar" }}>
            <Share
              of={Math.abs(Number(each.net)) / biggest}
              tone={
                Number(each.net) < 0
                  ? "var(--color-state-noshow)"
                  : "var(--color-state-completed)"
              }
            />
          </span>
        </li>
      ))}
      <li className={`${ROW} grid-cols-[1fr_auto] bg-[var(--surface-sunken)]`}>
        <span className="text-[15px] font-semibold">All of it</span>
        <Amount value={net} currency={currency} className="text-[15px] font-semibold" />
      </li>
    </ul>
  );
}

export function Doctors({
  doctors,
  currency,
  showMoney,
}: {
  doctors: DoctorLine[];
  currency: string;
  showMoney: boolean;
}) {
  return (
    <ul className="divide-y divide-[var(--border)]" role="list">
      {doctors.map((each) => (
        <li key={each.doctor.id} className="flex items-baseline gap-x-4 gap-y-1 px-5 py-3">
          <div className="min-w-0 flex-1">
            <Link
              href={`/doctors/${each.doctor.id}` as Route}
              className="block truncate text-[15px] font-medium underline-offset-4 hover:underline"
            >
              {each.doctor.display_name}
            </Link>
            <p className="text-[13px] text-[var(--text-muted)]">
              {[
                each.average_minutes !== null
                  ? `${each.average_minutes} minutes a visit`
                  : null,
                each.no_shows > 0 ? `${each.no_shows} did not stay` : null,
              ]
                .filter(Boolean)
                .join(", ") || "Nothing timed yet"}
            </p>
            {showMoney && (
              <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
                <Amount
                  value={each.collected}
                  currency={currency}
                  className="text-[var(--text)]"
                />{" "}
                in, of <Amount value={each.billed} currency={currency} /> billed
              </p>
            )}
          </div>
          <div className="shrink-0 text-right">
            <span className="block font-mono text-[17px] font-semibold tabular">
              {each.seen}
            </span>
            <span className="block text-[13px] text-[var(--text-muted)]">seen</span>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function Charges({ charges, currency }: { charges: ChargeLine[]; currency: string }) {
  const biggest = Math.max(1, ...charges.map((each) => Number(each.amount)));
  return (
    <ul className="divide-y divide-[var(--border)]" role="list">
      {charges.map((each) => (
        <li key={each.description} className="px-5 py-2.5">
          <div className="flex items-baseline justify-between gap-4">
            <span className="min-w-0 truncate text-[15px]">{each.description}</span>
            <span className="shrink-0 text-right">
              <Amount value={each.amount} currency={currency} className="text-[15px]" />
              <span className="ml-2 text-[13px] text-[var(--text-muted)] tabular">
                &times;{each.times}
              </span>
            </span>
          </div>
          <Share of={Number(each.amount) / biggest} tone="var(--color-marigold-400)" />
        </li>
      ))}
    </ul>
  );
}

export function Tests({ tests }: { tests: TestLine[] }) {
  const most = Math.max(1, ...tests.map((each) => each.times));
  return (
    <ul className="divide-y divide-[var(--border)]" role="list">
      {tests.map((each) => (
        <li key={each.name} className="px-5 py-2.5">
          <div className="flex items-baseline justify-between gap-4">
            <span className="min-w-0 truncate text-[15px]">{each.name}</span>
            <span className="shrink-0 text-[15px] tabular">{each.times}</span>
          </div>
          <Share of={each.times / most} tone="var(--color-state-consulting)" />
        </li>
      ))}
    </ul>
  );
}
