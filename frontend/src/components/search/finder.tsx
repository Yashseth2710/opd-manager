"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CalendarDays,
  CornerDownLeft,
  Loader2,
  ReceiptIndianRupee,
  Search,
  Stethoscope,
  UserRound,
  Users,
} from "lucide-react";
import type { Route } from "next";
import { useRouter } from "next/navigation";
import { Dialog } from "radix-ui";
import { createContext, useContext, useEffect, useId, useMemo, useState } from "react";
import type { Session } from "@/lib/auth";
import {
  forget,
  HEADINGS,
  hits,
  lookedIn,
  recentFor,
  remember,
  search,
  SHORTEST,
  squeezed,
  type Hit,
  type Kind,
} from "@/lib/search";

/** A place in the app the box can take somebody to by name. */
export type Page = { label: string; href: string };

type Opener = { open: () => void };
const FinderContext = createContext<Opener>({ open: () => {} });

const COLOUR: Record<Hit["kind"], string> = {
  page: "var(--text-muted)",
  patients: "var(--color-state-consulting)",
  appointments: "var(--color-state-confirmed)",
  bills: "var(--color-marigold-500)",
  doctors: "var(--color-state-completed)",
  staff: "var(--color-ink-400)",
};

const ICON: Record<Hit["kind"], React.ComponentType<{ className?: string }>> = {
  page: ArrowRight,
  patients: UserRound,
  appointments: CalendarDays,
  bills: ReceiptIndianRupee,
  doctors: Stethoscope,
  staff: Users,
};

// Mirrors what the server will search, so the hint before anything is typed
// promises only what this role can find.
const NEEDS: [Kind, string][] = [
  ["patients", "patient:read"],
  ["appointments", "appointment:read"],
  ["bills", "billing:read"],
  ["doctors", "doctor:read"],
  ["staff", "staff:manage"],
];

const WAIT_MS = 160;

function typingSomewhere(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/**
 * The search box, opened from the rail, with Ctrl K or ⌘K from anywhere, or
 * with / when the cursor is not already in a field.
 */
export function FinderProvider({
  session,
  pages,
  children,
}: {
  session: Session;
  pages: Page[];
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  // A platform account belongs to no clinic, so there is nothing to search.
  const usable = Boolean(session.organization);

  useEffect(() => {
    if (!usable) return;
    const listen = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((was) => !was);
      } else if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.altKey) {
        if (typingSomewhere(event.target)) return;
        event.preventDefault();
        setOpen(true);
      }
    };
    // The box covers the page, so going back or forward is the only way to
    // leave while it is open, and it should not stay over a page it was not
    // opened for.
    const left = () => setOpen(false);
    document.addEventListener("keydown", listen);
    window.addEventListener("popstate", left);
    return () => {
      document.removeEventListener("keydown", listen);
      window.removeEventListener("popstate", left);
    };
  }, [usable]);

  const opener = useMemo(() => ({ open: () => setOpen(true) }), []);

  return (
    <FinderContext.Provider value={opener}>
      {children}
      <Dialog.Root open={usable && open} onOpenChange={setOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="finder-veil fixed inset-0 z-50 bg-[rgb(8_15_26/0.5)]" />
          <Dialog.Content
            aria-describedby={undefined}
            className="finder-panel fixed inset-x-3 top-3 z-50 flex max-h-[calc(100dvh-1.5rem)] flex-col overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface-raised)] text-[var(--text)] shadow-[0_24px_60px_-16px_rgb(8_15_26/0.55)] sm:inset-x-auto sm:top-[12vh] sm:left-1/2 sm:max-h-[76vh] sm:w-[40rem] sm:-translate-x-1/2"
          >
            <Dialog.Title className="sr-only">Search the clinic</Dialog.Title>
            {/* Mounted only while open, so every opening starts empty. */}
            <Finder session={session} pages={pages} close={() => setOpen(false)} />
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </FinderContext.Provider>
  );
}

function shortcut(): string {
  if (typeof navigator === "undefined") return "Ctrl K";
  return /Mac|iPhone|iPad/.test(navigator.userAgent) ? "⌘K" : "Ctrl K";
}

/** The field in the rail on a wide screen, and a plain icon on a phone. */
export function SearchTrigger({ compact }: { compact?: boolean }) {
  const { open } = useContext(FinderContext);

  if (compact) {
    return (
      <button
        type="button"
        onClick={open}
        aria-label="Search"
        className="grid size-9 place-items-center rounded-[var(--radius-field)] text-[var(--rail-text)] transition-colors hover:bg-white/8 hover:text-white"
      >
        <Search className="size-[18px]" />
      </button>
    );
  }

  return (
    <button
      type="button"
      onClick={open}
      aria-keyshortcuts="Control+K Meta+K"
      className="group flex w-full items-center gap-2.5 rounded-[var(--radius-field)] bg-white/[0.06] px-2.5 py-2 text-left text-[14px] text-[var(--rail-text)] ring-1 ring-white/[0.08] transition-colors ring-inset hover:bg-white/10 hover:text-white"
    >
      <Search className="size-4 shrink-0" />
      <span className="flex-1">Search</span>
      <kbd className="rounded-[4px] border border-white/15 px-1.5 py-px font-sans text-[11px] text-[var(--color-ink-300)] group-hover:text-[var(--rail-text)]">
        {shortcut()}
      </kbd>
    </button>
  );
}

function Finder({
  session,
  pages,
  close,
}: {
  session: Session;
  pages: Page[];
  close: () => void;
}) {
  const router = useRouter();
  const listId = useId();
  const [typed, setTyped] = useState("");
  const [term, setTerm] = useState("");
  const [chosen, setChosen] = useState<string | null>(null);
  const [recent, setRecent] = useState<Hit[]>(() => recentFor(session.user.id));

  // Asks once somebody pauses, not on every key.
  useEffect(() => {
    const next = squeezed(typed);
    const timer = setTimeout(() => setTerm(next), next.length < SHORTEST ? 0 : WAIT_MS);
    return () => clearTimeout(timer);
  }, [typed]);

  const searching = term.length >= SHORTEST;
  const found = useQuery({
    queryKey: ["search", term],
    queryFn: ({ signal }) => search(term, signal),
    enabled: searching,
    placeholderData: keepPreviousData,
    staleTime: 30_000,
    retry: false,
  });

  const clinic = session.organization!;
  const now = squeezed(typed).toLowerCase();
  const pageHits: Hit[] =
    now.length >= SHORTEST
      ? pages
          .filter((page) => page.label.toLowerCase().includes(now))
          .map((page) => ({
            kind: "page" as const,
            id: page.href,
            title: page.label,
            detail: "",
            href: page.href,
          }))
      : [];

  const showingRecent = now.length < SHORTEST;
  const recordHits = searching && found.data ? hits(found.data, clinic) : [];
  const shown = showingRecent ? recent : [...pageHits, ...recordHits];
  const key = (hit: Hit) => `${hit.kind}:${hit.id}`;
  const active = shown.find((hit) => key(hit) === chosen) ?? shown[0];
  const optionId = (hit: Hit) => `${listId}-${key(hit).replace(/[^a-zA-Z0-9-]/g, "")}`;

  useEffect(() => {
    if (!active) return;
    document.getElementById(optionId(active))?.scrollIntoView({ block: "nearest" });
    // optionId is derived from listId, which never changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  function go(hit: Hit) {
    remember(session.user.id, hit);
    close();
    router.push(hit.href as Route);
  }

  function move(step: number) {
    if (!shown.length) return;
    const at = active ? shown.indexOf(active) : -1;
    const next = shown[(at + step + shown.length) % shown.length];
    if (next) setChosen(key(next));
  }

  function onKeyDown(event: React.KeyboardEvent<HTMLInputElement>) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      move(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
    } else if (event.key === "Enter" && active) {
      event.preventDefault();
      go(active);
    }
  }

  const kinds = NEEDS.filter(([, needs]) => session.permissions.includes(needs)).map(
    ([kind]) => kind,
  );
  const waiting = searching && (found.isFetching || term !== squeezed(typed));
  const stale = found.isPlaceholderData || (searching && term !== squeezed(typed));
  const nothing =
    searching && !found.isFetching && found.isSuccess && !stale && shown.length === 0;

  return (
    <>
      <div className="flex items-center gap-3 border-b border-[var(--border)] px-4">
        <Search aria-hidden className="size-[18px] shrink-0 text-[var(--text-muted)]" />
        <input
          autoFocus
          value={typed}
          onChange={(event) => {
            setTyped(event.target.value);
            setChosen(null);
          }}
          onKeyDown={onKeyDown}
          maxLength={100}
          role="combobox"
          aria-label="Search the clinic"
          aria-autocomplete="list"
          aria-expanded={shown.length > 0}
          aria-controls={listId}
          aria-activedescendant={active ? optionId(active) : undefined}
          placeholder={
            kinds.includes("bills")
              ? "A name, phone number, patient ID or bill number"
              : "A name, phone number or patient ID"
          }
          spellCheck={false}
          autoComplete="off"
          enterKeyHint="go"
          className="h-14 min-w-0 flex-1 bg-transparent text-[16px] outline-none placeholder:text-[var(--text-subtle)] sm:text-[17px]"
        />
        {waiting && (
          <Loader2
            aria-hidden
            className="size-4 shrink-0 animate-spin text-[var(--text-subtle)]"
          />
        )}
        <Dialog.Close
          aria-label="Close search"
          className="shrink-0 rounded-[var(--radius-field)] px-2 py-1 text-[13px] font-medium text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
        >
          <span className="sm:hidden">Cancel</span>
          <kbd className="hidden rounded-[4px] border border-[var(--border-strong)] px-1.5 py-px font-sans text-[11px] sm:inline">
            Esc
          </kbd>
        </Dialog.Close>
      </div>

      <p aria-live="polite" className="sr-only">
        {showingRecent
          ? ""
          : waiting
            ? "Searching"
            : found.isError
              ? "Search did not load"
              : `${shown.length} ${shown.length === 1 ? "result" : "results"}`}
      </p>

      <div
        id={listId}
        role="listbox"
        aria-label={showingRecent ? "Opened lately" : "Results"}
        className={`min-h-0 flex-1 overflow-y-auto overscroll-contain pb-2 transition-opacity ${
          stale && shown.length ? "opacity-60" : ""
        }`}
      >
        {showingRecent ? (
          recent.length ? (
            <Group
              heading="Opened lately"
              action={
                <button
                  type="button"
                  onClick={() => {
                    setRecent([]);
                    forget(session.user.id);
                  }}
                  className="rounded-[4px] px-1.5 py-0.5 text-[12px] text-[var(--text-subtle)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
                >
                  Clear
                </button>
              }
            >
              {recent.map((hit) => (
                <Row
                  key={key(hit)}
                  id={optionId(hit)}
                  hit={hit}
                  typed=""
                  active={hit === active}
                  onPoint={() => setChosen(key(hit))}
                  onPick={() => go(hit)}
                />
              ))}
            </Group>
          ) : (
            <Hint kinds={kinds} />
          )
        ) : found.isError && !found.data ? (
          <div className="px-5 py-8 text-center">
            <p className="text-[14px] font-medium">Search did not load</p>
            <p className="mt-1 text-[13px] text-[var(--text-muted)]">
              Check the connection, then try again.
            </p>
            <button
              type="button"
              onClick={() => found.refetch()}
              className="mt-3 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[13px] font-medium transition-colors hover:bg-[var(--surface-sunken)]"
            >
              Try again
            </button>
          </div>
        ) : nothing ? (
          <div className="px-5 py-8 text-center">
            <p className="text-[14px] font-medium">
              Nothing matches <span className="break-all">“{term}”</span>
            </p>
            <p className="mx-auto mt-1 max-w-[42ch] text-[13px] leading-relaxed text-[var(--text-muted)]">
              Looked through {lookedIn(found.data?.searched ?? kinds)}. A few letters of a name
              {kinds.includes("bills")
                ? ", the last digits of a phone or a bill number are"
                : " or the last digits of a phone are"}{" "}
              usually enough.
            </p>
          </div>
        ) : (
          groupsOf(shown).map(([kind, group]) => (
            <Group key={kind} heading={HEADINGS[kind]}>
              {group.map((hit) => (
                <Row
                  key={key(hit)}
                  id={optionId(hit)}
                  hit={hit}
                  typed={now}
                  active={hit === active}
                  onPoint={() => setChosen(key(hit))}
                  onPick={() => go(hit)}
                />
              ))}
            </Group>
          ))
        )}
        {searching && !shown.length && !found.data && !found.isError && (
          <p className="px-5 py-8 text-center text-[13px] text-[var(--text-muted)]">
            Searching…
          </p>
        )}
      </div>

      <div className="hidden items-center gap-4 border-t border-[var(--border)] bg-[var(--surface-sunken)] px-4 py-2 text-[12px] text-[var(--text-muted)] sm:flex">
        <span>
          <Key>↑</Key> <Key>↓</Key> to move
        </span>
        <span>
          <Key>Enter</Key> to open
        </span>
        <span className="ml-auto">
          <Key>/</Key> opens this from anywhere
        </span>
      </div>
    </>
  );
}

function groupsOf(shown: Hit[]): [Hit["kind"], Hit[]][] {
  const groups = new Map<Hit["kind"], Hit[]>();
  for (const hit of shown) groups.set(hit.kind, [...(groups.get(hit.kind) ?? []), hit]);
  return [...groups.entries()];
}

function Group({
  heading,
  action,
  children,
}: {
  heading: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  const headingId = useId();
  return (
    <div role="group" aria-labelledby={headingId} className="pt-2">
      <div className="flex items-center justify-between px-4 pt-1 pb-1">
        <p id={headingId} className="text-[12px] font-medium text-[var(--text-subtle)]">
          {heading}
        </p>
        {action}
      </div>
      {children}
    </div>
  );
}

function Row({
  id,
  hit,
  typed,
  active,
  onPoint,
  onPick,
}: {
  id: string;
  hit: Hit;
  typed: string;
  active: boolean;
  onPoint: () => void;
  onPick: () => void;
}) {
  const Icon = ICON[hit.kind];
  const colour = COLOUR[hit.kind];
  return (
    <div
      id={id}
      role="option"
      aria-selected={active}
      onMouseMove={active ? undefined : onPoint}
      onClick={onPick}
      className={`mx-1.5 flex cursor-pointer items-center gap-3 rounded-[var(--radius-field)] px-2.5 py-2 ${
        active ? "bg-[var(--accent-wash)]" : ""
      }`}
    >
      <span
        aria-hidden
        className="grid size-8 shrink-0 place-items-center rounded-[7px]"
        style={{ color: colour, background: `color-mix(in srgb, ${colour} 14%, transparent)` }}
      >
        <Icon className="size-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate text-[14.5px] font-medium">
            <Marked text={hit.title} typed={typed} />
          </span>
          {hit.flag && (
            <span className="shrink-0 rounded-[4px] bg-[var(--surface-sunken)] px-1.5 py-px text-[11.5px] text-[var(--text-muted)]">
              {hit.flag}
            </span>
          )}
        </span>
        {hit.detail && (
          <span className="mt-0.5 block truncate text-[13px] text-[var(--text-muted)] tabular">
            <Marked text={hit.detail} typed={typed} />
          </span>
        )}
      </span>
      <CornerDownLeft
        aria-hidden
        className={`size-4 shrink-0 text-[var(--text-subtle)] ${active ? "" : "invisible"}`}
      />
    </div>
  );
}

/** The part of a line the typed text matched, so the eye lands on why it is here. */
function Marked({ text, typed }: { text: string; typed: string }) {
  if (typed.length < SHORTEST) return text;
  const at = text.toLowerCase().indexOf(typed);
  if (at < 0) return text;
  return (
    <>
      {text.slice(0, at)}
      <mark className="rounded-[2px] bg-[var(--accent-wash)] text-inherit shadow-[inset_0_-2px_0_var(--accent)]">
        {text.slice(at, at + typed.length)}
      </mark>
      {text.slice(at + typed.length)}
    </>
  );
}

function Key({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="rounded-[4px] border border-[var(--border-strong)] bg-[var(--surface-raised)] px-1.5 py-px font-sans text-[11px] text-[var(--text)]">
      {children}
    </kbd>
  );
}

function Hint({ kinds }: { kinds: Kind[] }) {
  const tries: [Kind, string][] = [
    ["patients", "a patient by name, by ID like PT-000123, or by the last digits of a phone"],
    ["appointments", "their bookings still to come, found by the patient's name"],
    ["bills", "a bill number, like 2026-27/0042"],
    ["doctors", "a doctor or a speciality"],
    ["staff", "a colleague's name or email"],
  ];
  const offered = tries.filter(([kind]) => kinds.includes(kind));
  return (
    <div className="px-5 py-6">
      <p className="text-[14px] font-medium">Search {lookedIn(kinds)}</p>
      <ul className="mt-2 space-y-1 text-[13px] text-[var(--text-muted)]">
        {offered.map(([kind, example]) => (
          <li key={kind} className="flex items-baseline gap-2">
            <span
              aria-hidden
              className="size-1.5 shrink-0 translate-y-[-1px] rounded-full"
              style={{ background: COLOUR[kind] }}
            />
            {example}
          </li>
        ))}
      </ul>
    </div>
  );
}
