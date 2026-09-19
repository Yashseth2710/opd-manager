"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, Loader2, Plus, X, Zap } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useId, useMemo, useRef, useState } from "react";
import { FlaggedCount, LabStatusChip, Urgent } from "@/components/labs/parts";
import { ApiFailure } from "@/lib/api";
import {
  findTest,
  getLabTests,
  listLabOrders,
  matchTests,
  orderTest,
  removeLabOrder,
  type LabOrderListed,
  type LabOrderPage,
  type LabTest,
} from "@/lib/labs";

// What most outpatient doctors ask for most, offered before the clinic has
// ordered enough for its own habits to show.
const USUAL = ["cbc", "fbs", "hba1c", "lipid", "kft", "lft", "thyroid", "urine_routine"];
const QUICK = 8;

const FIELD =
  "w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3.5 py-2 text-[15px] outline-none transition-[border-color,box-shadow] placeholder:text-[var(--text-subtle)] focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)] disabled:opacity-70";

/** "CBC" rather than "Complete blood count", where the test goes by letters. */
function shortName(test: LabTest): string {
  const letters = test.also.find((other) => /^[A-Z0-9]{2,5}$/.test(other));
  return letters ?? test.name;
}

export const visitKey = (visitId: string) => ["lab-orders", "visit", visitId] as const;

/**
 * The tests asked for on this visit. While the doctor is writing the notes
 * they can order more, one at a time, and take one back that has not gone
 * anywhere yet. Afterwards it is the list, each one opening its report.
 */
export function VisitTests({
  visitId,
  canOrder,
  disabled = false,
}: {
  visitId: string;
  canOrder: boolean;
  disabled?: boolean;
}) {
  const orders = useQuery({
    queryKey: visitKey(visitId),
    queryFn: () => listLabOrders({ visit: visitId, limit: 100 }),
    retry: false,
  });
  const items = orders.data?.items ?? [];

  if (!canOrder && orders.isSuccess && items.length === 0) return null;

  return (
    <section aria-labelledby="visit-tests-title" className="flex flex-col gap-3">
      <div>
        <h2 id="visit-tests-title" className="text-[15px] font-semibold">
          Tests
        </h2>
        {canOrder && (
          <p className="text-[13px] text-[var(--text-muted)]">
            Ordered as you add them, so the desk sees them straight away. The desk types the
            report in when it comes back.
          </p>
        )}
      </div>

      {orders.isPending ? (
        <p className="inline-flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" /> Looking…
        </p>
      ) : orders.isError ? (
        <p className="text-[14px] text-[var(--text-muted)]">
          The tests on this visit did not load.
        </p>
      ) : (
        items.length > 0 && (
          <ul
            aria-label="Tests on this visit"
            className="flex max-w-[75ch] flex-col divide-y divide-[var(--border)] rounded-[var(--radius-field)] border border-[var(--border)] bg-[var(--surface)]"
          >
            {items.map((item) => (
              <OrderRow
                key={item.id}
                item={item}
                visitId={visitId}
                removable={canOrder && !disabled && item.status === "ordered"}
                writing={canOrder}
              />
            ))}
          </ul>
        )
      )}

      {canOrder && orders.isSuccess && (
        <Picker visitId={visitId} ordered={items} disabled={disabled} />
      )}
    </section>
  );
}

function OrderRow({
  item,
  visitId,
  removable,
  writing,
}: {
  item: LabOrderListed;
  visitId: string;
  removable: boolean;
  /** While the notes are being written, a test not back yet needs no label. */
  writing: boolean;
}) {
  const queries = useQueryClient();
  const remove = useMutation({
    mutationFn: () => removeLabOrder(item.id),
    onSuccess: () => {
      queries.setQueryData<LabOrderPage>(visitKey(visitId), (page) =>
        page
          ? {
              ...page,
              items: page.items.filter((each) => each.id !== item.id),
              total: page.total - 1,
            }
          : page,
      );
      void queries.invalidateQueries({ queryKey: ["lab-orders"] });
      void queries.invalidateQueries({ queryKey: ["lab-tests"] });
    },
  });

  return (
    <li className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-3.5 py-2.5">
      <span className="min-w-0 flex-1 basis-[14rem]">
        <span className="flex flex-wrap items-baseline gap-x-2">
          <Link
            href={`/lab/${item.id}` as Route}
            className="text-[15px] font-medium break-words underline-offset-4 hover:underline"
          >
            {item.test_name}
          </Link>
          <span className="font-mono text-[12px] text-[var(--text-subtle)] tabular">
            {item.order_number}
          </span>
        </span>
        {item.instructions && (
          <span className="block text-[13px] text-[var(--text-muted)]">
            {item.instructions}
          </span>
        )}
        {remove.isError && (
          <span role="alert" className="block text-[13px] text-[var(--color-state-noshow)]">
            {remove.error instanceof ApiFailure
              ? remove.error.message
              : "That did not go through. Try again in a moment."}
          </span>
        )}
      </span>
      <span className="flex flex-wrap items-center gap-2">
        {item.urgent && <Urgent />}
        <FlaggedCount count={item.flagged} />
        {(item.status !== "ordered" || !writing) && <LabStatusChip status={item.status} />}
        {removable && (
          <button
            type="button"
            onClick={() => remove.mutate()}
            disabled={remove.isPending}
            aria-label={`Take back ${item.test_name}`}
            title="Take back"
            className="grid size-8 place-items-center rounded-[6px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)] disabled:opacity-60"
          >
            {remove.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <X className="size-4" />
            )}
          </button>
        )}
      </span>
    </li>
  );
}

function Picker({
  visitId,
  ordered,
  disabled,
}: {
  visitId: string;
  ordered: LabOrderListed[];
  disabled: boolean;
}) {
  const queries = useQueryClient();
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  const closing = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [typed, setTyped] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [urgent, setUrgent] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const catalogue = useQuery({
    queryKey: ["lab-tests"],
    queryFn: getLabTests,
    staleTime: 5 * 60_000,
    retry: false,
  });
  const tests = useMemo(() => catalogue.data?.tests ?? [], [catalogue.data]);
  const categories = catalogue.data?.categories ?? {};

  const taken = new Set(
    ordered
      .filter((each) => each.status !== "cancelled")
      .map((each) => each.test_name.toLowerCase()),
  );
  const isTaken = (test: LabTest) => taken.has(test.name.toLowerCase());

  const quick = useMemo(() => {
    const often = tests
      .filter((test) => test.times_ordered > 0)
      .sort((a, b) => b.times_ordered - a.times_ordered);
    const usual = USUAL.map((code) => tests.find((test) => test.code === code)).filter(
      (test): test is LabTest => Boolean(test),
    );
    const seen = new Set<string>();
    return [...often, ...usual]
      .filter((test) => {
        const key = test.name.toLowerCase();
        if (seen.has(key)) return false;
        seen.add(key);
        return true;
      })
      .slice(0, QUICK);
  }, [tests]);

  const clean = typed.trim().replace(/\s+/g, " ");
  const matches = clean ? matchTests(tests, clean) : [];
  const exact = findTest(tests, clean);
  // Anything not on the list can still be ordered, in the doctor's words.
  const options: ({ kind: "test"; test: LabTest } | { kind: "typed"; name: string })[] = [
    ...matches.map((test) => ({ kind: "test" as const, test })),
    ...(clean && !exact ? [{ kind: "typed" as const, name: clean }] : []),
  ];
  const showing = open && clean.length > 0 && options.length > 0;

  const place = useMutation({
    mutationFn: (what: { code?: string; name?: string }) =>
      orderTest({
        consultation_id: visitId,
        ...(what.code ? { test_code: what.code } : { test_name: what.name }),
        urgent,
      }),
    onSuccess: (made) => {
      queries.setQueryData<LabOrderPage>(visitKey(visitId), (page) =>
        page ? { ...page, items: [...page.items, made], total: page.total + 1 } : page,
      );
      void queries.invalidateQueries({ queryKey: ["lab-orders"], exact: false });
      void queries.invalidateQueries({ queryKey: ["lab-tests"] });
      setTyped("");
      setOpen(false);
      setProblem(null);
      input.current?.focus();
    },
    onError: (error) =>
      setProblem(
        error instanceof ApiFailure
          ? ((error.fields ? Object.values(error.fields)[0] : undefined) ?? error.message)
          : "That did not go through. Try again in a moment.",
      ),
  });

  const choose = (option: (typeof options)[number]) => {
    if (place.isPending) return;
    if (option.kind === "test") {
      if (isTaken(option.test)) {
        setOpen(false);
        setProblem(`${option.test.name} is already ordered on this visit.`);
        return;
      }
      place.mutate(option.test.code ? { code: option.test.code } : { name: option.test.name });
    } else {
      place.mutate({ name: option.name });
    }
  };

  const busy = disabled || place.isPending;

  return (
    <div className="flex max-w-[75ch] flex-col gap-2.5">
      <div className="flex flex-wrap items-stretch gap-2">
        <div className="relative min-w-[min(100%,16rem)] flex-1">
          <label htmlFor={`${id}-test`} className="sr-only">
            Order a test
          </label>
          <FlaskConical
            aria-hidden
            className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[var(--text-subtle)]"
          />
          <input
            ref={input}
            id={`${id}-test`}
            role="combobox"
            aria-expanded={showing}
            aria-controls={`${id}-options`}
            aria-autocomplete="list"
            aria-activedescendant={showing ? `${id}-option-${active}` : undefined}
            aria-invalid={Boolean(problem)}
            aria-describedby={problem ? `${id}-problem` : undefined}
            autoComplete="off"
            value={typed}
            maxLength={120}
            disabled={disabled}
            placeholder="Order a test: CBC, thyroid, X-ray chest…"
            onChange={(event) => {
              setTyped(event.target.value);
              setOpen(true);
              setActive(0);
              setProblem(null);
            }}
            onFocus={() => {
              // Coming straight back must not be undone by the last blur.
              if (closing.current) clearTimeout(closing.current);
              setOpen(true);
            }}
            onBlur={() => {
              closing.current = setTimeout(() => setOpen(false), 120);
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") {
                setOpen(false);
                return;
              }
              // Enter orders what is typed even with the list closed, rather
              // than doing nothing with it.
              if (event.key === "Enter") {
                event.preventDefault();
                const chosen = options[showing ? active : 0];
                if (chosen) choose(chosen);
                return;
              }
              if (!showing) return;
              if (event.key === "ArrowDown") {
                event.preventDefault();
                setActive((at) => (at + 1) % options.length);
              } else if (event.key === "ArrowUp") {
                event.preventDefault();
                setActive((at) => (at - 1 + options.length) % options.length);
              }
            }}
            className={`${FIELD} pl-9`}
          />
          {showing && (
            <ul
              id={`${id}-options`}
              role="listbox"
              aria-label="Tests"
              className="absolute top-full right-0 left-0 z-20 mt-1 max-h-80 overflow-auto rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface-raised)] py-1 shadow-[0_12px_32px_-12px_rgb(8_15_26/0.35)]"
            >
              {options.map((option, index) => {
                const already = option.kind === "test" && isTaken(option.test);
                return (
                  <li
                    key={option.kind === "test" ? `t-${option.test.name}` : "typed"}
                    id={`${id}-option-${index}`}
                    role="option"
                    aria-selected={index === active}
                    aria-disabled={already || undefined}
                    onMouseDown={(event) => {
                      event.preventDefault();
                      choose(option);
                    }}
                    onMouseMove={() => {
                      if (active !== index) setActive(index);
                    }}
                    className={`flex cursor-pointer items-baseline justify-between gap-3 px-3 py-2 text-[14px] ${
                      index === active ? "bg-[var(--accent-wash)]" : ""
                    } ${already ? "opacity-55" : ""}`}
                  >
                    {option.kind === "test" ? (
                      <>
                        <span className="min-w-0">
                          <span className="font-medium">{option.test.name}</span>
                          {option.test.also.length > 0 && (
                            <span className="ml-2 text-[13px] text-[var(--text-muted)]">
                              {option.test.also.slice(0, 2).join(", ")}
                            </span>
                          )}
                        </span>
                        <span className="shrink-0 text-[12px] text-[var(--text-muted)]">
                          {already
                            ? "Ordered"
                            : option.test.category
                              ? (categories[option.test.category] ?? "")
                              : option.test.times_ordered
                                ? "Ordered here before"
                                : ""}
                        </span>
                      </>
                    ) : (
                      <span className="min-w-0">
                        Order <span className="font-medium">“{option.name}”</span>
                        <span className="ml-2 text-[13px] text-[var(--text-muted)]">
                          as you typed it
                        </span>
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
        <button
          type="button"
          aria-pressed={urgent}
          onClick={() => setUrgent((value) => !value)}
          disabled={busy}
          title="Tests added while this is on are marked urgent"
          className={`inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border px-3 text-[14px] font-medium transition-colors disabled:opacity-60 ${
            urgent
              ? "border-[var(--color-state-urgent)] bg-[color-mix(in_srgb,var(--color-state-urgent)_12%,transparent)] text-[var(--color-state-urgent)]"
              : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
          }`}
        >
          <Zap className="size-4" />
          Urgent
        </button>
        {place.isPending && (
          <span className="inline-flex items-center gap-1.5 text-[13px] text-[var(--text-muted)]">
            <Loader2 className="size-4 animate-spin" /> Ordering…
          </span>
        )}
      </div>

      {problem && (
        <p
          id={`${id}-problem`}
          role="alert"
          className="text-[13px] text-[var(--color-state-noshow)]"
        >
          {problem}
        </p>
      )}

      {catalogue.isError ? (
        <p className="text-[13px] text-[var(--text-muted)]">
          The list of tests did not load. Type the test and press the option to order it as
          written.
        </p>
      ) : (
        quick.length > 0 && (
          <div role="group" aria-label="Order in one tap" className="flex flex-wrap gap-1.5">
            {quick.map((test) => {
              const already = isTaken(test);
              return (
                <button
                  key={test.name}
                  type="button"
                  disabled={busy || already}
                  aria-pressed={already}
                  onClick={() => choose({ kind: "test", test })}
                  className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-[13px] transition-colors disabled:cursor-default ${
                    already
                      ? "border-[var(--color-state-completed)] bg-[color-mix(in_srgb,var(--color-state-completed)_12%,transparent)] text-[var(--text)]"
                      : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)] disabled:opacity-60"
                  }`}
                >
                  {!already && <Plus aria-hidden className="size-3.5" />}
                  <span aria-hidden>{shortName(test)}</span>
                  <span className="sr-only">
                    {already ? `${test.name}, ordered` : `Order ${test.name}`}
                  </span>
                </button>
              );
            })}
          </div>
        )
      )}
    </div>
  );
}
