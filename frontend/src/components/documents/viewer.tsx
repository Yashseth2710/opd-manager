"use client";

import { useMutation } from "@tanstack/react-query";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  ExternalLink,
  FileText,
  Loader2,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { ApiFailure, refreshOnce } from "@/lib/api";
import { shortDate, whenItHappened } from "@/lib/appointments";
import {
  CATEGORIES,
  CATEGORY_WORDS,
  changeDocument,
  fileHref,
  isImage,
  readableSize,
  removeDocument,
  type Category,
  type PatientDocument,
} from "@/lib/documents";
import { todayISO } from "@/lib/doctors";

const FIELD =
  "w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[15px] outline-none transition-[border-color,box-shadow] focus:border-[var(--focus-ring)] focus:shadow-[0_0_0_3px_color-mix(in_srgb,var(--focus-ring)_22%,transparent)] aria-invalid:border-[var(--color-state-noshow)]";

const QUIET_BUTTON =
  "inline-flex items-center gap-1.5 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-50";

/** Wide enough for a browser's own PDF reader to be of any use inside a page. */
function useWide(): boolean {
  return useSyncExternalStore(
    (changed) => {
      const query = window.matchMedia("(min-width: 640px)");
      query.addEventListener("change", changed);
      return () => query.removeEventListener("change", changed);
    },
    () => window.matchMedia("(min-width: 640px)").matches,
    () => true,
  );
}

type Loaded =
  { state: "loading" } | { state: "ready"; url: string } | { state: "failed"; message: string };

/**
 * The file, fetched on the session like any other request, so a session
 * that ran out is renewed first and a file gone from storage says so, where
 * a frame pointed straight at the address would show an error page instead.
 */
function useFile(document: PatientDocument, onFailed: () => void): Loaded {
  const [loaded, setLoaded] = useState<Loaded>({ state: "loading" });

  useEffect(() => {
    let current = true;
    let url: string | null = null;
    const fetchIt = () => fetch(fileHref(document.id), { credentials: "include" });

    (async () => {
      try {
        let response = await fetchIt();
        if (response.status === 401 && (await refreshOnce())) response = await fetchIt();
        if (!response.ok) {
          let message = "The file could not be opened. Try again in a moment.";
          try {
            const body = (await response.json()) as { error?: { message?: string } };
            message = body.error?.message ?? message;
          } catch {
            // Not the API answering.
          }
          if (current) {
            setLoaded({ state: "failed", message });
            onFailed();
          }
          return;
        }
        const blob = await response.blob();
        url = URL.createObjectURL(blob);
        if (current) setLoaded({ state: "ready", url });
      } catch {
        if (current) {
          setLoaded({
            state: "failed",
            message: "Could not reach the server. Check your connection and try again.",
          });
          onFailed();
        }
      }
    })();

    return () => {
      current = false;
      if (url) URL.revokeObjectURL(url);
    };
    // Fetched once per file; the callback changing does not make it a new file.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [document.id]);

  return loaded;
}

export function DocumentViewer({
  documents,
  index,
  patientName,
  onIndex,
  onClose,
  onChanged,
  onRemoved,
}: {
  documents: PatientDocument[];
  index: number;
  patientName: string;
  onIndex: (index: number) => void;
  onClose: () => void;
  onChanged: (document: PatientDocument) => void;
  onRemoved: (document: PatientDocument) => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const document = documents[index];
  const [editing, setEditing] = useState(false);
  const [removing, setRemoving] = useState(false);
  // A file that would not open has nothing to download or open elsewhere.
  const [unavailable, setUnavailable] = useState<string | null>(null);

  useEffect(() => {
    const element = dialog.current;
    if (element && !element.open) element.showModal();
  }, []);

  const step = (by: number) => {
    const next = index + by;
    if (next < 0 || next >= documents.length) return;
    setEditing(false);
    setRemoving(false);
    onIndex(next);
  };

  if (!document) return null;
  const at = `${index + 1} of ${documents.length}`;

  return (
    <dialog
      ref={dialog}
      aria-labelledby="viewer-title"
      onClose={onClose}
      onKeyDown={(event) => {
        const typing = (event.target as HTMLElement).closest("input, select, textarea");
        if (typing || editing) return;
        if (event.key === "ArrowLeft") step(-1);
        if (event.key === "ArrowRight") step(1);
      }}
      onClick={(event) => {
        // A click on the dimmed backdrop lands on the dialog element itself.
        if (event.target === event.currentTarget) dialog.current?.close();
      }}
      className="m-0 h-dvh max-h-none w-full max-w-none bg-[var(--surface)] p-0 text-[var(--text)] backdrop:bg-[rgb(8_15_26/0.72)] sm:m-auto sm:h-[min(92dvh,56rem)] sm:w-[min(94vw,64rem)] sm:rounded-[var(--radius-panel)] sm:border sm:border-[var(--border)] sm:shadow-[0_24px_64px_rgb(8_15_26/0.35)]"
    >
      <div className="flex h-full flex-col">
        <header className="flex flex-wrap items-start gap-x-4 gap-y-2 border-b border-[var(--border)] px-4 py-3 sm:px-5">
          <div className="min-w-0 flex-1">
            <h2
              id="viewer-title"
              className="text-[17px] leading-snug font-semibold break-words"
            >
              {document.title}
            </h2>
            <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
              {[
                CATEGORY_WORDS[document.category],
                document.dated ? `dated ${shortDate(document.dated)}` : null,
                `added ${whenItHappened(document.uploaded_at)}${
                  document.uploaded_by ? ` by ${document.uploaded_by}` : ""
                }`,
                readableSize(document.size_bytes),
              ]
                .filter(Boolean)
                .join(", ")}
            </p>
            {document.lab_order_number && (
              <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
                The lab&apos;s report for{" "}
                <Link
                  href={`/lab/${document.lab_order_id}` as Route}
                  className="underline underline-offset-2 hover:text-[var(--text)]"
                >
                  {document.lab_test_name} ({document.lab_order_number})
                </Link>
              </p>
            )}
          </div>
          <div className="flex items-center gap-1">
            {documents.length > 1 && (
              <>
                <button
                  type="button"
                  onClick={() => step(-1)}
                  disabled={index === 0}
                  aria-label="Previous file"
                  className="grid size-9 place-items-center rounded-[var(--radius-field)] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-30"
                >
                  <ChevronLeft className="size-5" />
                </button>
                <span className="px-1 text-[13px] text-[var(--text-muted)] tabular">{at}</span>
                <button
                  type="button"
                  onClick={() => step(1)}
                  disabled={index === documents.length - 1}
                  aria-label="Next file"
                  className="grid size-9 place-items-center rounded-[var(--radius-field)] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-30"
                >
                  <ChevronRight className="size-5" />
                </button>
              </>
            )}
            <button
              type="button"
              onClick={() => dialog.current?.close()}
              aria-label="Close"
              className="grid size-9 place-items-center rounded-[var(--radius-field)] transition-colors hover:bg-[var(--surface-sunken)]"
            >
              <X className="size-5" />
            </button>
          </div>
        </header>

        <Shown
          key={document.id}
          document={document}
          onFailed={() => setUnavailable(document.id)}
        />

        <footer className="flex flex-col gap-3 border-t border-[var(--border)] px-4 py-3 sm:px-5">
          {editing ? (
            <EditDetails
              key={document.id}
              document={document}
              onDone={(changed) => {
                setEditing(false);
                if (changed) onChanged(changed);
              }}
            />
          ) : removing ? (
            <ConfirmRemove
              document={document}
              patientName={patientName}
              onKeep={() => setRemoving(false)}
              onRemoved={() => {
                setRemoving(false);
                onRemoved(document);
              }}
            />
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              {unavailable !== document.id && (
                <>
                  <a
                    href={fileHref(document.id)}
                    target="_blank"
                    rel="noopener"
                    className={QUIET_BUTTON}
                  >
                    <ExternalLink className="size-4" />
                    Open in a new tab
                  </a>
                  <a href={fileHref(document.id, true)} download className={QUIET_BUTTON}>
                    <Download className="size-4" />
                    Download
                  </a>
                </>
              )}
              {document.can_change && (
                <>
                  <button
                    type="button"
                    onClick={() => setEditing(true)}
                    className={QUIET_BUTTON}
                  >
                    <Pencil className="size-4" />
                    Edit details
                  </button>
                  <button
                    type="button"
                    onClick={() => setRemoving(true)}
                    className="ml-auto inline-flex items-center gap-1.5 rounded-[var(--radius-field)] px-3 py-1.5 text-[14px] text-[var(--color-state-noshow)] transition-colors hover:bg-[color-mix(in_srgb,var(--color-state-noshow)_10%,transparent)]"
                  >
                    <Trash2 className="size-4" />
                    Remove
                  </button>
                </>
              )}
            </div>
          )}
        </footer>
      </div>
    </dialog>
  );
}

function Shown({ document, onFailed }: { document: PatientDocument; onFailed: () => void }) {
  const loaded = useFile(document, onFailed);
  const wide = useWide();

  return (
    <div className="relative min-h-0 flex-1 bg-[var(--surface-sunken)]">
      {loaded.state === "loading" ? (
        <p className="absolute inset-0 flex items-center justify-center gap-2 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" />
          Opening the file…
        </p>
      ) : loaded.state === "failed" ? (
        <div
          role="alert"
          className="absolute inset-0 flex flex-col items-center justify-center gap-2 px-6 text-center"
        >
          <FileText className="size-8 text-[var(--text-subtle)]" />
          <p className="max-w-[44ch] text-[15px]">{loaded.message}</p>
        </div>
      ) : isImage(document.content_type) ? (
        <div className="absolute inset-0 overflow-auto p-3 sm:p-5">
          {/* eslint-disable-next-line @next/next/no-img-element -- a private file on a session, not something to optimise */}
          <img
            src={loaded.url}
            alt={document.title}
            className="mx-auto h-full w-auto max-w-full object-contain"
          />
        </div>
      ) : wide ? (
        <iframe
          src={loaded.url}
          title={document.title}
          className="absolute inset-0 size-full"
        />
      ) : (
        // Phone browsers do not draw a PDF inside a page; they hand it to
        // their own reader instead.
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 px-6 text-center">
          <span className="grid size-14 place-items-center rounded-[var(--radius-panel)] bg-[var(--surface)] text-[12px] font-semibold tracking-wide text-[var(--color-state-noshow)] shadow-sm">
            PDF
          </span>
          <p className="max-w-[36ch] text-[15px]">
            {document.original_name}, {readableSize(document.size_bytes)}
          </p>
          <a
            href={fileHref(document.id)}
            target="_blank"
            rel="noopener"
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2.5 text-[15px] font-semibold text-[var(--primary-fg)]"
          >
            <ExternalLink className="size-4" />
            Open the PDF
          </a>
        </div>
      )}
    </div>
  );
}

function EditDetails({
  document,
  onDone,
}: {
  document: PatientDocument;
  onDone: (changed: PatientDocument | null) => void;
}) {
  const [title, setTitle] = useState(document.title);
  const [category, setCategory] = useState<Category>(document.category);
  const [dated, setDated] = useState(document.dated ?? "");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const today = todayISO();

  const save = useMutation({
    mutationFn: () =>
      changeDocument(document.id, {
        title: title.trim(),
        ...(document.lab_order_id ? {} : { category }),
        dated: dated || null,
      }),
    onSuccess: (changed) => onDone(changed),
    onError: (error) => {
      if (error instanceof ApiFailure && error.fields) setFields(error.fields);
      else
        setProblem(
          error instanceof ApiFailure ? error.message : "That did not save. Try again.",
        );
    },
  });

  return (
    <form
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        setProblem(null);
        const found: Record<string, string> = {};
        if (!title.trim()) found.title = "Give it a name.";
        if (dated && dated > today) found.dated = "The date on it cannot be after today.";
        setFields(found);
        if (Object.keys(found).length || save.isPending) return;
        save.mutate();
      }}
      className="flex flex-col gap-3"
    >
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[minmax(0,1fr)_14rem_10rem]">
        <label className="flex flex-col gap-1 text-[13px] text-[var(--text-muted)]">
          Name
          <input
            autoFocus
            value={title}
            maxLength={120}
            onChange={(event) => setTitle(event.target.value)}
            aria-invalid={Boolean(fields.title)}
            className={FIELD}
          />
          {fields.title && (
            <span className="text-[13px] text-[var(--color-state-noshow)]">{fields.title}</span>
          )}
        </label>
        <label className="flex flex-col gap-1 text-[13px] text-[var(--text-muted)]">
          Kind
          <select
            value={category}
            disabled={Boolean(document.lab_order_id)}
            onChange={(event) => setCategory(event.target.value as Category)}
            className={FIELD}
          >
            {CATEGORIES.map((each) => (
              <option key={each} value={each}>
                {CATEGORY_WORDS[each]}
              </option>
            ))}
          </select>
          {fields.category && (
            <span className="text-[13px] text-[var(--color-state-noshow)]">
              {fields.category}
            </span>
          )}
        </label>
        <label className="flex flex-col gap-1 text-[13px] text-[var(--text-muted)]">
          Date on it
          <input
            type="date"
            value={dated}
            max={today}
            onChange={(event) => setDated(event.target.value)}
            aria-invalid={Boolean(fields.dated)}
            className={FIELD}
          />
          {fields.dated && (
            <span className="text-[13px] text-[var(--color-state-noshow)]">{fields.dated}</span>
          )}
        </label>
      </div>
      {problem && (
        <p role="alert" className="text-[14px] text-[var(--color-state-noshow)]">
          {problem}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="submit"
          disabled={save.isPending}
          className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2 text-[14px] font-semibold text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-60"
        >
          {save.isPending && <Loader2 className="size-4 animate-spin" />}
          Save
        </button>
        <button type="button" onClick={() => onDone(null)} className={QUIET_BUTTON}>
          Cancel
        </button>
      </div>
    </form>
  );
}

function ConfirmRemove({
  document,
  patientName,
  onKeep,
  onRemoved,
}: {
  document: PatientDocument;
  patientName: string;
  onKeep: () => void;
  onRemoved: () => void;
}) {
  const remove = useMutation({
    mutationFn: () => removeDocument(document.id),
    onSuccess: onRemoved,
  });

  return (
    <div role="alert" className="flex flex-col gap-2 text-[14px]">
      <p className="font-medium">
        Take “{document.title}” off {patientName}&apos;s record?
      </p>
      <p className="text-[var(--text-muted)]">
        The file is deleted, for everyone, and cannot be brought back.
      </p>
      {remove.error && (
        <p className="text-[var(--color-state-noshow)]">
          {remove.error instanceof ApiFailure
            ? remove.error.message
            : "That did not go through. Try again."}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          autoFocus
          onClick={() => remove.mutate()}
          disabled={remove.isPending}
          className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--color-state-noshow)] px-3.5 py-2 text-[14px] font-semibold text-white hover:brightness-110 disabled:opacity-60"
        >
          {remove.isPending && <Loader2 className="size-4 animate-spin" />}
          Yes, remove it
        </button>
        <button type="button" onClick={onKeep} className={QUIET_BUTTON}>
          Keep it
        </button>
      </div>
    </div>
  );
}
