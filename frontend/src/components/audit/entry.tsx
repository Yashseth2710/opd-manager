"use client";

import { ChevronDown, Filter } from "lucide-react";
import Link from "next/link";
import { useId, useState } from "react";
import {
  areaOf,
  asChange,
  device,
  fieldName,
  sentence,
  shown,
  whereItIs,
  type Area,
  type Entry,
} from "@/lib/audit";

const AREA_COLOUR: Record<Area, string> = {
  patients: "var(--color-ink-400)",
  appointments: "var(--color-state-confirmed)",
  clinical: "var(--color-state-consulting)",
  billing: "var(--color-marigold-500)",
  people: "var(--color-state-completed)",
  clinic: "var(--color-paper-500)",
  sign_in: "var(--color-state-noshow)",
};

function clock(value: string): string {
  return new Date(value).toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
}

function initials(name: string): string {
  const parts = name
    .replace(/\(.*\)/, "")
    .trim()
    .split(/\s+/);
  return (
    (parts[0]?.[0] ?? "") + (parts.length > 1 ? (parts.at(-1)?.[0] ?? "") : "")
  ).toUpperCase();
}

/**
 * One line of the log, read as a sentence. What moved, where it came from and
 * on what device fold out underneath, since most of the time the sentence is
 * all anybody needs.
 */
export function EntryRow({
  entry,
  onRecord,
}: {
  entry: Entry;
  onRecord: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const detailsId = useId();
  const words = sentence(entry);
  const where = whereItIs(entry);
  const area = areaOf(entry);
  const system = entry.actor_id === null;
  const changes = Object.entries(entry.changes ?? {});
  const machine = device(entry.user_agent);

  const record =
    entry.resource_label &&
    words.names &&
    (where ? (
      <Link
        href={where}
        className="font-medium text-[var(--text)] underline decoration-[var(--border-strong)] underline-offset-[3px] transition-colors hover:decoration-[var(--accent)]"
      >
        {entry.resource_label}
      </Link>
    ) : (
      <span className="font-medium text-[var(--text)]">{entry.resource_label}</span>
    ));

  return (
    <li className="group">
      <div className="flex items-start gap-2.5 px-3.5 py-2.5 sm:gap-3 sm:px-5">
        <time
          dateTime={entry.created_at}
          className="w-[3.4rem] shrink-0 pt-[3px] text-[12.5px] text-[var(--text-subtle)] tabular sm:w-[4.25rem] sm:text-[13px]"
        >
          {clock(entry.created_at)}
        </time>
        <span
          aria-hidden
          className={`mt-px hidden size-6 shrink-0 sm:grid place-items-center rounded-full text-[10.5px] font-semibold ${
            system
              ? "border border-dashed border-[var(--border-strong)] text-[var(--text-subtle)]"
              : "bg-[var(--surface-sunken)] text-[var(--text-muted)]"
          }`}
        >
          {system ? "?" : initials(entry.actor_name)}
        </span>
        <p className="min-w-0 flex-1 text-[14px] leading-relaxed [overflow-wrap:anywhere] text-[var(--text-muted)]">
          <span
            aria-hidden
            className="mr-2 inline-block size-[7px] rounded-full align-middle"
            style={{ background: AREA_COLOUR[area] }}
          />
          <span className={system ? "italic" : "font-medium text-[var(--text)]"}>
            {entry.actor_name}
          </span>{" "}
          {words.before} {record}
          {words.after && ` ${words.after}`}
        </p>
        <button
          type="button"
          onClick={() => setOpen((was) => !was)}
          aria-expanded={open}
          aria-controls={detailsId}
          aria-label={open ? "Hide details" : "Show details"}
          className="grid size-7 shrink-0 place-items-center rounded-[var(--radius-field)] text-[var(--text-subtle)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
        >
          <ChevronDown
            className={`size-4 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
          />
        </button>
      </div>

      {open && (
        <div
          id={detailsId}
          className="mb-3 ml-4 mr-4 rounded-[var(--radius-field)] bg-[var(--surface-sunken)] px-4 py-3 text-[13px] sm:ml-[7.5rem] sm:mr-5"
        >
          {changes.length > 0 && (
            <dl className="mb-3 grid grid-cols-[minmax(6rem,auto)_minmax(0,1fr)] gap-x-4 gap-y-1.5">
              {changes.map(([key, value]) => {
                const moved = asChange(value);
                return (
                  <div key={key} className="contents">
                    <dt className="text-[var(--text-muted)]">{fieldName(key)}</dt>
                    <dd className="min-w-0 break-words">
                      {moved ? (
                        <>
                          <span className="text-[var(--text-subtle)] line-through decoration-[var(--border-strong)]">
                            {shown(moved[0])}
                          </span>
                          <span
                            aria-label="changed to"
                            className="mx-1.5 text-[var(--text-subtle)]"
                          >
                            →
                          </span>
                          <span className="font-medium">{shown(moved[1])}</span>
                        </>
                      ) : (
                        <span className="font-medium">{shown(value)}</span>
                      )}
                    </dd>
                  </div>
                );
              })}
            </dl>
          )}
          <p className="flex flex-wrap gap-x-4 gap-y-1 text-[12.5px] text-[var(--text-muted)]">
            <span>
              {new Date(entry.created_at).toLocaleString("en-IN", {
                weekday: "short",
                day: "numeric",
                month: "short",
                year: "numeric",
                hour: "numeric",
                minute: "2-digit",
                second: "2-digit",
              })}
            </span>
            {entry.ip_address && <span className="tabular">From {entry.ip_address}</span>}
            {machine && <span>{machine}</span>}
          </p>
          {entry.resource_id && (
            <button
              type="button"
              onClick={() => onRecord(entry.resource_id!)}
              className="mt-2.5 inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1 text-[12.5px] transition-colors hover:border-[var(--accent)]"
            >
              <Filter aria-hidden className="size-3" />
              Everything about this record
            </button>
          )}
        </div>
      )}
    </li>
  );
}
