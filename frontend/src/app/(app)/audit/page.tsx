"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, Loader2, Search, X } from "lucide-react";
import type { Route } from "next";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { EntryRow } from "@/components/audit/entry";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { ApiFailure } from "@/lib/api";
import { AREAS, readLog, type Area, type Asked } from "@/lib/audit";
import { byDay } from "@/lib/notifications";

export default function AuditPage() {
  return (
    <Permitted permission="audit:read">
      <Suspense fallback={<Looking />}>
        <AuditLog />
      </Suspense>
    </Permitted>
  );
}

function Looking() {
  return (
    <div className="flex min-h-[20vh] items-center justify-center gap-3 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">Reading the log…</span>
    </div>
  );
}

const field =
  "rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1.5 text-[14px] outline-none focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)]";

function AuditLog() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  const area = (AREAS.some((a) => a.value === params.get("area")) ? params.get("area") : "") as
    Area | "";
  const asked: Asked = {
    area,
    actor: params.get("who") ?? "",
    record: params.get("record") ?? "",
    from: params.get("from") ?? "",
    to: params.get("to") ?? "",
    q: params.get("q") ?? "",
    page: Math.max(Number(params.get("page")) || 1, 1),
  };
  const [typed, setTyped] = useState(asked.q);

  const choose = (
    changes: Partial<Record<"area" | "who" | "record" | "from" | "to" | "q" | "page", string>>,
  ) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    // Any change to what is asked starts again from the newest.
    if (!("page" in changes)) next.delete("page");
    const query = next.toString();
    router.replace(`${pathname}${query ? `?${query}` : ""}` as Route, { scroll: false });
  };

  useEffect(() => {
    const timer = setTimeout(() => {
      if (typed.trim() !== asked.q) choose({ q: typed.trim() });
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [typed]);

  const backwards = Boolean(asked.from && asked.to && asked.to < asked.from);
  const log = useQuery({
    queryKey: ["audit", asked],
    queryFn: () => readLog(asked),
    placeholderData: keepPreviousData,
    enabled: !backwards,
    retry: false,
  });

  const found = log.data;
  const narrowed = Boolean(
    asked.area || asked.actor || asked.record || asked.from || asked.to || asked.q,
  );
  const first = found ? (found.page - 1) * found.per_page + 1 : 0;
  const last = found ? first + found.items.length - 1 : 0;
  const aboutRecord = asked.record
    ? found?.items.find((entry) => entry.resource_id === asked.record)?.resource_label
    : null;

  return (
    <Page
      title="Audit log"
      blurb="Who did what, and when. Every change is written down as it is saved, and nothing here can be edited or removed."
    >
      <div className="mb-5 flex flex-col gap-3">
        <div role="tablist" aria-label="Part of the clinic" className="flex flex-wrap gap-1.5">
          {AREAS.map((choice) => {
            const active = area === choice.value;
            return (
              <button
                key={choice.value || "all"}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => choose({ area: choice.value })}
                className={`rounded-full border px-3 py-1 text-[13.5px] transition-colors ${
                  active
                    ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-fg)]"
                    : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
                }`}
              >
                {choice.label}
              </button>
            );
          })}
        </div>

        <div className="flex flex-wrap items-end gap-2.5">
          <label className="relative min-w-[12rem] flex-1 basis-56">
            <span className="sr-only">Search by person or record</span>
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-[var(--text-subtle)]"
            />
            <input
              type="search"
              value={typed}
              maxLength={120}
              onChange={(event) => setTyped(event.target.value)}
              placeholder="A name, a bill number, a patient"
              className={`${field} w-full py-2 pl-9`}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] text-[var(--text-muted)]">
            Who
            <select
              value={asked.actor}
              onChange={(event) => choose({ who: event.target.value })}
              className={`${field} max-w-[13rem]`}
            >
              <option value="">Anyone</option>
              {found?.actors.map((actor) => (
                <option key={actor.id} value={actor.id}>
                  {actor.name}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] text-[var(--text-muted)]">
            From
            <input
              type="date"
              value={asked.from}
              onChange={(event) => choose({ from: event.target.value })}
              className={`${field} tabular`}
            />
          </label>
          <label className="flex flex-col gap-1 text-[12.5px] text-[var(--text-muted)]">
            To
            <input
              type="date"
              value={asked.to}
              min={asked.from || undefined}
              onChange={(event) => choose({ to: event.target.value })}
              className={`${field} tabular`}
            />
          </label>
          {narrowed && (
            <button
              type="button"
              onClick={() => {
                setTyped("");
                router.replace(pathname as Route, { scroll: false });
              }}
              className="inline-flex items-center gap-1 rounded-[var(--radius-field)] px-2.5 py-2 text-[13.5px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
            >
              <X className="size-3.5" />
              Clear
            </button>
          )}
        </div>

        {asked.record && (
          <p className="inline-flex flex-wrap items-center gap-2 self-start rounded-full bg-[var(--accent-wash)] py-1 pr-1 pl-3 text-[13.5px]">
            Only {aboutRecord ?? "one record"}
            <button
              type="button"
              onClick={() => choose({ record: "" })}
              aria-label="Show every record again"
              className="grid size-6 place-items-center rounded-full transition-colors hover:bg-black/10"
            >
              <X className="size-3.5" />
            </button>
          </p>
        )}
        {backwards && (
          <p role="alert" className="text-[13.5px] text-[var(--color-state-noshow)]">
            The last day comes before the first one.
          </p>
        )}
      </div>

      {backwards ? null : log.isPending ? (
        <Looking />
      ) : log.isError ? (
        <p className="text-[15px] text-[var(--text-muted)]">
          {log.error instanceof ApiFailure && log.error.status === 422
            ? log.error.message
            : "The log did not load. Try again in a moment."}
        </p>
      ) : found!.items.length === 0 ? (
        <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-10 text-center">
          <p className="text-[15px] font-medium">
            {narrowed ? "Nothing matches" : "Nothing has been written down yet"}
          </p>
          <p className="mx-auto mt-1.5 max-w-[44ch] text-[14px] leading-relaxed text-[var(--text-muted)]">
            {narrowed
              ? "Try a wider stretch of days, another part of the clinic, or clear the search."
              : "As soon as anybody registers a patient, books an appointment or takes a payment, it appears here."}
          </p>
        </div>
      ) : (
        <div className={`transition-opacity ${log.isPlaceholderData ? "opacity-60" : ""}`}>
          <div className="flex flex-col gap-6">
            {byDay(found!.items).map(([day, entries]) => (
              <section key={day} aria-label={day}>
                <h2 className="mb-2 text-[13px] font-semibold text-[var(--text-muted)]">
                  {day}
                </h2>
                <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
                  {entries.map((entry) => (
                    <EntryRow
                      key={entry.id}
                      entry={entry}
                      onRecord={(id) => {
                        // Everything means everything: the other filters go.
                        setTyped("");
                        choose({ record: id, area: "", who: "", from: "", to: "", q: "" });
                      }}
                    />
                  ))}
                </ul>
              </section>
            ))}
          </div>

          <nav
            aria-label="Pages of the log"
            className="mt-5 flex flex-wrap items-center justify-between gap-3 text-[13px] text-[var(--text-muted)]"
          >
            <span className="tabular">
              {found!.total <= found!.per_page
                ? `${found!.total} in all`
                : `${first}–${last} of ${found!.total}`}
            </span>
            {found!.pages > 1 && (
              <span className="flex gap-1.5">
                <button
                  type="button"
                  disabled={found!.page <= 1}
                  onClick={() => choose({ page: String(found!.page - 1) })}
                  className="inline-flex items-center gap-1 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[14px] text-[var(--text)] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-40"
                >
                  <ChevronLeft className="size-4" />
                  Newer
                </button>
                <button
                  type="button"
                  disabled={found!.page >= found!.pages}
                  onClick={() => choose({ page: String(found!.page + 1) })}
                  className="inline-flex items-center gap-1 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[14px] text-[var(--text)] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-40"
                >
                  Older
                  <ChevronRight className="size-4" />
                </button>
              </span>
            )}
          </nav>
        </div>
      )}
    </Page>
  );
}
