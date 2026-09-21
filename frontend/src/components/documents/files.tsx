"use client";

import { useInfiniteQuery, useQueryClient } from "@tanstack/react-query";
import {
  Check,
  FileText,
  ImageIcon,
  Link2,
  Loader2,
  Paperclip,
  RotateCcw,
  Upload,
  X,
} from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { DocumentViewer } from "@/components/documents/viewer";
import { ApiFailure } from "@/lib/api";
import { shortDate } from "@/lib/appointments";
import { todayISO } from "@/lib/doctors";
import {
  CATEGORIES,
  CATEGORY_WORDS,
  changeDocument,
  isImage,
  listDocuments,
  prepare,
  readableSize,
  titleFrom,
  uploadDocument,
  type Category,
  type PatientDocument,
  type Prepared,
} from "@/lib/documents";
import { localDay } from "@/lib/prescriptions";

const FIELD =
  "w-full min-w-0 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1.5 text-[14px] outline-none transition-[border-color,box-shadow] focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)] disabled:opacity-60 aria-invalid:border-[var(--color-state-noshow)]";

const ACCEPT = ".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp";
const AT_ONCE = 20;
const SHOWN = 20;

type Staged = {
  key: string;
  file: File;
  preview: string | null;
  title: string;
  category: Category;
  dated: string;
  state: "preparing" | "ready" | "refused" | "sending" | "added" | "failed";
  progress: number;
  problem: string | null;
  prepared: Prepared | null;
  /** The same file, already on the record, when it turned out to be a repeat. */
  existing: { id: string; title: string } | null;
};

/**
 * Where on the record the files are going. On the patient's page, anywhere
 * on it; from the notes, onto that visit; from a lab order, as the lab's own
 * copy of that report.
 */
export type Destination = {
  patientId: string;
  patientName: string;
  visit?: string;
  labOrder?: string;
};

export function DocumentsPanel({
  destination,
  heading,
  mayUpload,
  closedBecause,
  emptyWords,
  filters = false,
  hideWhenEmpty = false,
  plain = false,
  description,
}: {
  destination: Destination;
  heading: string;
  mayUpload: boolean;
  /** Why nothing can be added here, when that is the case. */
  closedBecause?: string | null;
  emptyWords: string;
  filters?: boolean;
  hideWhenEmpty?: boolean;
  /** Without a panel of its own, as one section among others on a page. */
  plain?: boolean;
  description?: string;
}) {
  const queries = useQueryClient();
  const headingId = useId();
  const [category, setCategory] = useState<Category | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const staging = useStaging(destination, () => {
    void queries.invalidateQueries({ queryKey: ["documents", destination.patientId] });
  });
  const canAdd = mayUpload && !closedBecause;

  const found = useInfiniteQuery({
    queryKey: [
      "documents",
      destination.patientId,
      { visit: destination.visit, labOrder: destination.labOrder, category },
    ],
    queryFn: ({ pageParam }) =>
      listDocuments(destination.patientId, {
        visit: destination.visit,
        labOrder: destination.labOrder,
        category: category ?? undefined,
        limit: SHOWN,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (last, pages) => {
      const shown = pages.reduce((sum, page) => sum + page.items.length, 0);
      return shown < last.total ? shown : undefined;
    },
    retry: false,
  });
  const items = found.data?.pages.flatMap((page) => page.items) ?? [];
  const counts = found.data?.pages[0]?.counts ?? {};
  const everything = Object.values(counts).reduce((sum, count) => sum + (count ?? 0), 0);
  // The counts cover the whole record; a panel for one visit or one test
  // counts only what it lists.
  const shownCount = filters ? everything : (found.data?.pages[0]?.total ?? 0);
  const kinds = CATEGORIES.filter((each) => counts[each]);

  const refresh = () =>
    void queries.invalidateQueries({ queryKey: ["documents", destination.patientId] });

  if (
    hideWhenEmpty &&
    !canAdd &&
    found.isSuccess &&
    items.length === 0 &&
    staging.staged.length === 0
  ) {
    return null;
  }

  return (
    <section
      aria-labelledby={headingId}
      onDragEnter={(event) => {
        if (!canAdd || !event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        setDragging(true);
      }}
      onDragOver={(event) => {
        if (!canAdd || !event.dataTransfer.types.includes("Files")) return;
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }}
      onDragLeave={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null))
          setDragging(false);
      }}
      onDrop={(event) => {
        if (!canAdd) return;
        event.preventDefault();
        setDragging(false);
        staging.add(Array.from(event.dataTransfer.files));
      }}
      className={`relative min-w-0 ${
        plain
          ? "max-w-[75ch]"
          : "rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-4"
      }`}
    >
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
        <div className="min-w-0">
          <h2 id={headingId} className="text-[15px] font-semibold">
            {heading}
            {shownCount > 0 && (
              <span className="ml-2 text-[13px] font-normal text-[var(--text-muted)] tabular">
                {shownCount}
              </span>
            )}
          </h2>
          {description && <p className="text-[13px] text-[var(--text-muted)]">{description}</p>}
        </div>
        {canAdd && (
          <button
            type="button"
            onClick={staging.pick}
            disabled={staging.busy}
            className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-50"
          >
            <Paperclip className="size-4" />
            Add files
          </button>
        )}
        {staging.input}
      </div>

      {mayUpload && closedBecause && (
        <p className="mt-2 text-[13px] text-[var(--text-muted)]">{closedBecause}</p>
      )}

      {staging.staged.length > 0 && (
        <Staging staging={staging} fixedCategory={Boolean(destination.labOrder)} />
      )}

      {filters && kinds.length > 1 && (
        <div role="group" aria-label="Show only" className="mt-3 flex flex-wrap gap-1.5">
          <Chip on={category === null} onClick={() => setCategory(null)}>
            All <span className="tabular opacity-70">{everything}</span>
          </Chip>
          {kinds.map((each) => (
            <Chip key={each} on={category === each} onClick={() => setCategory(each)}>
              {CATEGORY_WORDS[each]} <span className="tabular opacity-70">{counts[each]}</span>
            </Chip>
          ))}
        </div>
      )}

      {found.isPending ? (
        <p className="mt-3 inline-flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" /> Looking…
        </p>
      ) : found.isError ? (
        <p className="mt-3 text-[14px] text-[var(--text-muted)]">
          {found.error instanceof ApiFailure && found.error.status === 403
            ? "You do not have access to files on this record."
            : "The files did not load. Try again in a moment."}
        </p>
      ) : items.length === 0 ? (
        staging.staged.length === 0 &&
        (canAdd ? (
          <button
            type="button"
            onClick={staging.pick}
            className="mt-3 flex w-full flex-col items-center gap-1 rounded-[var(--radius-field)] border border-dashed border-[var(--border-strong)] px-4 py-5 text-center transition-colors hover:border-[var(--focus-ring)] hover:bg-[var(--accent-wash)]"
          >
            <Upload aria-hidden className="size-5 text-[var(--text-muted)]" />
            <span className="text-[14px]">{emptyWords}</span>
            <span className="text-[12px] text-[var(--text-muted)]">
              PDFs and photos, up to 4 MB each. Drop them here or tap to choose.
            </span>
          </button>
        ) : (
          <p className="mt-2 text-[14px] text-[var(--text-muted)]">No files yet.</p>
        ))
      ) : (
        <>
          <ul className="-mx-2 mt-2 flex flex-col">
            {items.map((item, index) => (
              <li key={item.id}>
                <Row
                  document={item}
                  showWhere={!destination.visit && !destination.labOrder}
                  onOpen={() => setOpen(index)}
                />
              </li>
            ))}
          </ul>
          {found.hasNextPage && (
            <button
              type="button"
              onClick={() => void found.fetchNextPage()}
              disabled={found.isFetchingNextPage}
              className="mt-2 inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[13px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-60"
            >
              {found.isFetchingNextPage && <Loader2 className="size-3.5 animate-spin" />}
              Show more
            </button>
          )}
        </>
      )}

      {dragging && (
        <div
          aria-hidden
          className="pointer-events-none absolute inset-0 grid place-items-center rounded-[var(--radius-panel)] border-2 border-dashed border-[var(--accent)] bg-[color-mix(in_srgb,var(--surface)_88%,var(--accent))] text-[15px] font-medium"
        >
          Drop to add to {destination.patientName}&apos;s record
        </div>
      )}

      {open !== null && items[open] && (
        <DocumentViewer
          documents={items}
          index={open}
          patientName={destination.patientName}
          onIndex={setOpen}
          onClose={() => setOpen(null)}
          onChanged={refresh}
          onRemoved={() => {
            setOpen(null);
            refresh();
          }}
        />
      )}
    </section>
  );
}

function Chip({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[13px] transition-colors ${
        on
          ? "border-[var(--primary)] bg-[var(--primary)] text-[var(--primary-fg)]"
          : "border-[var(--border-strong)] hover:bg-[var(--surface-sunken)]"
      }`}
    >
      {children}
    </button>
  );
}

/** A PDF and a photo look different at a glance, and that is most of what a glance needs. */
function Kind({ type }: { type: string }) {
  const photo = isImage(type);
  return (
    <span
      aria-hidden
      className="grid size-9 shrink-0 place-items-center rounded-[var(--radius-field)]"
      style={{
        background: `color-mix(in srgb, ${
          photo ? "var(--color-state-consulting)" : "var(--color-state-noshow)"
        } 12%, transparent)`,
        color: photo ? "var(--color-state-consulting)" : "var(--color-state-noshow)",
      }}
    >
      {photo ? <ImageIcon className="size-4" /> : <FileText className="size-4" />}
    </span>
  );
}

function Row({
  document,
  showWhere,
  onOpen,
}: {
  document: PatientDocument;
  showWhere: boolean;
  onOpen: () => void;
}) {
  const visit = showWhere && !document.lab_order_number ? document.visit_date : null;
  // A file from a visit is dated by the visit, unless the paper says otherwise.
  const when = document.dated
    ? shortDate(document.dated)
    : visit
      ? null
      : `added ${shortDate(localDay(document.uploaded_at))}`;
  const where = !showWhere
    ? null
    : document.lab_order_number
      ? `${document.lab_test_name}, ${document.lab_order_number}`
      : visit
        ? `from the visit on ${shortDate(visit)}`
        : null;

  return (
    <button
      type="button"
      onClick={onOpen}
      className="flex w-full items-center gap-3 rounded-[var(--radius-field)] px-2 py-2 text-left transition-colors hover:bg-[var(--surface-sunken)]"
    >
      <Kind type={document.content_type} />
      <span className="min-w-0 flex-1">
        <span className="block text-[14px] font-medium break-words">{document.title}</span>
        <span className="block text-[13px] text-[var(--text-muted)]">
          {[CATEGORY_WORDS[document.category], when, where].filter(Boolean).join(", ")}
        </span>
      </span>
      <span className="hidden shrink-0 text-[12px] text-[var(--text-subtle)] tabular sm:block">
        {readableSize(document.size_bytes)}
      </span>
    </button>
  );
}

// --- Choosing and sending ----------------------------------------------------

function useStaging(destination: Destination, onAdded: () => void) {
  const [staged, setStaged] = useState<Staged[]>([]);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const stopper = useRef<AbortController | null>(null);
  // Two clicks can land before the first has re-rendered anything.
  const sending = useRef(false);
  const previews = useRef(new Set<string>());

  const patch = (key: string, changes: Partial<Staged>) =>
    setStaged((current) =>
      current.map((each) => (each.key === key ? { ...each, ...changes } : each)),
    );

  // Photos shown while choosing are let go of when they leave the list.
  useEffect(() => {
    const held = previews.current;
    return () => held.forEach((url) => URL.revokeObjectURL(url));
  }, []);

  // Closing the tab mid-upload loses whatever had not gone yet.
  useEffect(() => {
    if (!busy) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [busy]);

  const add = (files: File[]) => {
    if (files.length === 0) return;
    const room = AT_ONCE - staged.length;
    setNotice(
      files.length > room
        ? `Up to ${AT_ONCE} files at a time. The first ${Math.max(room, 0)} were added.`
        : null,
    );
    const taken = files.slice(0, Math.max(room, 0)).map<Staged>((file) => {
      const preview = file.type.startsWith("image/") ? URL.createObjectURL(file) : null;
      if (preview) previews.current.add(preview);
      return {
        key: `${file.name}-${file.size}-${file.lastModified}-${Math.random()}`,
        file,
        preview,
        title: titleFrom(file.name),
        category: "lab_report",
        dated: "",
        state: "preparing",
        progress: 0,
        problem: null,
        prepared: null,
        existing: null,
      };
    });
    setStaged((current) => [...current, ...taken]);
    for (const each of taken) {
      prepare(each.file)
        .then((prepared) => patch(each.key, { state: "ready", prepared }))
        .catch((error: unknown) =>
          patch(each.key, {
            state: "refused",
            problem: error instanceof Error ? error.message : "This file cannot be added.",
          }),
        );
    }
  };

  const drop = (key: string) =>
    setStaged((current) => {
      const leaving = current.find((each) => each.key === key);
      if (leaving?.preview) {
        URL.revokeObjectURL(leaving.preview);
        previews.current.delete(leaving.preview);
      }
      return current.filter((each) => each.key !== key);
    });

  const clear = () => {
    stopper.current?.abort();
    for (const each of staged) if (each.preview) URL.revokeObjectURL(each.preview);
    previews.current.clear();
    setStaged([]);
    setNotice(null);
  };

  const send = async (only?: string) => {
    if (sending.current) return;
    const today = todayISO();
    let blocked = false;
    for (const each of staged) {
      if (only && each.key !== only) continue;
      if (each.state !== "ready" && each.state !== "failed") continue;
      if (!each.title.trim()) {
        patch(each.key, { problem: "Give it a name." });
        blocked = true;
      } else if (each.dated && each.dated > today) {
        patch(each.key, { problem: "The date on it cannot be after today." });
        blocked = true;
      }
    }
    if (blocked) return;

    const going = staged.filter(
      (each) =>
        (!only || each.key === only) &&
        (each.state === "ready" || each.state === "failed") &&
        each.prepared,
    );
    if (going.length === 0) return;

    sending.current = true;
    setBusy(true);
    const stop = new AbortController();
    stopper.current = stop;
    let added = 0;
    // One at a time: a clinic's upstream is usually one phone's worth of
    // mobile data, and the progress means more when it is one file's.
    for (const each of going) {
      if (stop.signal.aborted) break;
      const prepared = each.prepared as Prepared;
      patch(each.key, { state: "sending", progress: 0, problem: null });
      try {
        await uploadDocument(
          destination.patientId,
          prepared.blob,
          prepared.name,
          {
            category: destination.labOrder ? "lab_report" : each.category,
            title: each.title,
            dated: each.dated || undefined,
            visit: destination.visit,
            labOrder: destination.labOrder,
          },
          (progress) => patch(each.key, { progress }),
          stop.signal,
        );
        added += 1;
        patch(each.key, { state: "added", progress: 1 });
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          patch(each.key, { state: "ready", progress: 0 });
          break;
        }
        // Worth another go only when the trouble was on the way: the network,
        // the server, or too many at once. The file itself will not change.
        const passing =
          !(error instanceof ApiFailure) ||
          error.status === 0 ||
          error.status === 429 ||
          error.status >= 500;
        const repeat =
          error instanceof ApiFailure && error.code === "DOC_ALREADY_UPLOADED"
            ? (error.candidates?.[0] as { id: string; title: string } | undefined)
            : undefined;
        patch(each.key, {
          state: passing ? "failed" : "refused",
          problem:
            error instanceof ApiFailure ? error.message : "This one did not go. Try again.",
          existing: repeat ?? null,
        });
      }
    }
    sending.current = false;
    setBusy(false);
    stopper.current = null;
    if (added > 0) onAdded();
    // What went in leaves the list; what did not stays, saying why.
    setTimeout(
      () =>
        setStaged((current) => {
          const left = current.filter((each) => each.state !== "added");
          for (const each of current)
            if (each.state === "added" && each.preview) URL.revokeObjectURL(each.preview);
          return left;
        }),
      700,
    );
  };

  // From a test's page, a repeat is usually the report already put on the
  // record from somewhere else; it can be put with this test instead.
  const takeExisting = async (key: string, existing: { id: string; title: string }) => {
    if (!destination.labOrder || sending.current) return;
    sending.current = true;
    setBusy(true);
    try {
      await changeDocument(existing.id, { lab_order_id: destination.labOrder });
      patch(key, { state: "added", problem: null, existing: null });
      onAdded();
      setTimeout(() => drop(key), 700);
    } catch (error) {
      patch(key, {
        problem:
          error instanceof ApiFailure ? error.message : "That did not go through. Try again.",
        existing: null,
      });
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };

  return {
    staged,
    busy,
    notice,
    takeExisting,
    add,
    drop,
    clear,
    send,
    patch,
    stop: () => stopper.current?.abort(),
    pick: () => input.current?.click(),
    input: (
      <input
        ref={input}
        type="file"
        multiple
        accept={ACCEPT}
        hidden
        aria-hidden
        data-testid="document-input"
        onChange={(event) => {
          add(Array.from(event.target.files ?? []));
          // The same file can be chosen again after it is taken off the list.
          event.target.value = "";
        }}
      />
    ),
  };
}

type StagingControls = ReturnType<typeof useStaging>;

function Staging({
  staging,
  fixedCategory,
}: {
  staging: StagingControls;
  fixedCategory: boolean;
}) {
  const { staged, busy } = staging;
  const sendable = staged.filter(
    (each) => each.state === "ready" || (each.state === "failed" && each.prepared),
  ).length;
  const preparing = staged.some((each) => each.state === "preparing");
  const today = todayISO();

  return (
    <div className="mt-3 flex flex-col gap-3 rounded-[var(--radius-field)] border border-[var(--border)] bg-[var(--surface-sunken)] p-3">
      <ul className="flex flex-col gap-2" aria-label="Files to add">
        {staged.map((each) => {
          const locked = busy || each.state === "sending" || each.state === "added";
          const refused = each.state === "refused";
          const existing = each.existing;
          return (
            <li
              key={each.key}
              className="flex items-start gap-2.5 rounded-[var(--radius-field)] border border-[var(--border)] bg-[var(--surface)] p-2.5"
            >
              {each.preview && !refused ? (
                // eslint-disable-next-line @next/next/no-img-element -- a local preview of a file not sent yet
                <img
                  src={each.preview}
                  alt=""
                  className="size-9 shrink-0 rounded-[var(--radius-field)] object-cover"
                />
              ) : (
                <Kind type={each.file.type || "application/pdf"} />
              )}

              <div className="@container flex min-w-0 flex-1 flex-col gap-1.5">
                {refused ? (
                  <p className="pt-1.5 text-[14px] font-medium break-words">{each.file.name}</p>
                ) : (
                  <>
                    <input
                      aria-label={`Name for ${each.file.name}`}
                      value={each.title}
                      maxLength={120}
                      disabled={locked}
                      onChange={(event) =>
                        staging.patch(each.key, { title: event.target.value, problem: null })
                      }
                      aria-invalid={each.problem === "Give it a name."}
                      className={FIELD}
                    />
                    <div className="grid min-w-0 grid-cols-1 gap-2 @2xs:grid-cols-[minmax(0,1fr)_minmax(0,9.5rem)]">
                      <select
                        aria-label={`Kind of file for ${each.file.name}`}
                        value={fixedCategory ? "lab_report" : each.category}
                        disabled={locked || fixedCategory}
                        onChange={(event) =>
                          staging.patch(each.key, { category: event.target.value as Category })
                        }
                        className={FIELD}
                      >
                        {CATEGORIES.map((category) => (
                          <option key={category} value={category}>
                            {CATEGORY_WORDS[category]}
                          </option>
                        ))}
                      </select>
                      <input
                        type="date"
                        aria-label={`Date on ${each.file.name}, if it has one`}
                        title="The date printed on it, if it has one"
                        value={each.dated}
                        max={today}
                        disabled={locked}
                        onChange={(event) =>
                          staging.patch(each.key, { dated: event.target.value, problem: null })
                        }
                        className={FIELD}
                      />
                    </div>
                  </>
                )}
                <p className="text-[12px] break-words text-[var(--text-muted)]">
                  {refused ? "" : `${each.file.name}, `}
                  {readableSize(each.prepared?.blob.size ?? each.file.size)}
                  {each.prepared?.shrunk &&
                    `, made smaller from ${readableSize(each.file.size)}`}
                </p>
                {each.state === "sending" && (
                  <div
                    role="progressbar"
                    aria-label={`Sending ${each.file.name}`}
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={Math.round(each.progress * 100)}
                    className="h-1.5 overflow-hidden rounded-full bg-[var(--border)]"
                  >
                    <div
                      className="h-full rounded-full bg-[var(--accent)] transition-[width] duration-200"
                      style={{ width: `${Math.max(4, each.progress * 100)}%` }}
                    />
                  </div>
                )}
                {each.problem && (
                  <p role="alert" className="text-[13px] text-[var(--color-state-noshow)]">
                    {each.problem}
                  </p>
                )}
                {existing && fixedCategory && !busy && (
                  <button
                    type="button"
                    onClick={() => void staging.takeExisting(each.key, existing)}
                    className="inline-flex w-fit items-center gap-1 text-[13px] font-medium underline underline-offset-2"
                  >
                    <Link2 className="size-3.5" /> Put “{existing.title}” with this test
                  </button>
                )}
                {each.state === "failed" && each.prepared && !busy && (
                  <button
                    type="button"
                    onClick={() => void staging.send(each.key)}
                    className="inline-flex w-fit items-center gap-1 text-[13px] underline-offset-2 hover:underline"
                  >
                    <RotateCcw className="size-3.5" /> Try again
                  </button>
                )}
                {each.state === "added" && (
                  <span className="inline-flex items-center gap-1 text-[13px] text-[var(--color-state-completed)]">
                    <Check className="size-4" /> Added
                  </span>
                )}
              </div>

              {each.state === "preparing" ? (
                <Loader2 className="m-2 size-4 shrink-0 animate-spin text-[var(--text-muted)]" />
              ) : (
                !locked && (
                  <button
                    type="button"
                    onClick={() => staging.drop(each.key)}
                    aria-label={`Leave out ${each.file.name}`}
                    className="grid size-8 shrink-0 place-items-center rounded-[var(--radius-field)] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
                  >
                    <X className="size-4" />
                  </button>
                )
              )}
            </li>
          );
        })}
      </ul>

      {staging.notice && (
        <p className="text-[13px] text-[var(--text-muted)]">{staging.notice}</p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        {(sendable > 0 || preparing || busy) && (
          // Stays where it is while sending, so a second click on it lands on
          // a button that is waiting rather than on one that stops.
          <button
            type="button"
            onClick={() => void staging.send()}
            disabled={busy || sendable === 0 || preparing}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--accent-fg)] transition-[filter,transform] duration-150 hover:brightness-[1.06] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60"
          >
            {busy ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
            {busy ? "Sending…" : sendable === 1 ? "Add the file" : `Add ${sendable} files`}
          </button>
        )}
        {busy ? (
          <button
            type="button"
            onClick={staging.stop}
            className="rounded-[var(--radius-field)] px-3 py-2 text-[14px] text-[var(--text-muted)] underline-offset-4 hover:text-[var(--text)] hover:underline"
          >
            Stop
          </button>
        ) : (
          <>
            {staged.length < AT_ONCE && (
              <button
                type="button"
                onClick={staging.pick}
                className="rounded-[var(--radius-field)] px-3 py-2 text-[14px] text-[var(--text-muted)] underline-offset-4 hover:text-[var(--text)] hover:underline"
              >
                Choose more
              </button>
            )}
            <button
              type="button"
              onClick={staging.clear}
              className="rounded-[var(--radius-field)] px-3 py-2 text-[14px] text-[var(--text-muted)] underline-offset-4 hover:text-[var(--text)] hover:underline"
            >
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  );
}
