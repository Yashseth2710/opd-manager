"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArrowLeft, Loader2, Pencil, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Problem } from "@/components/auth/form";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { Allergies } from "@/components/patients/allergies";
import { Duplicates } from "@/components/patients/duplicates";
import { PatientFields } from "@/components/patients/form";
import { ApiFailure } from "@/lib/api";
import { currentSession } from "@/lib/auth";
import {
  archivePatient,
  checkDuplicates,
  getPatient,
  initials,
  readablePhone,
  restorePatient,
  savePatient,
  type DuplicateCandidate,
  type Patient,
  type PatientDraft,
} from "@/lib/patients";

export default function PatientPage() {
  return (
    <Permitted permission="patient:read">
      <Record />
    </Permitted>
  );
}

function Record() {
  const id = String(useParams().id);
  const [editing, setEditing] = useState(false);

  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const patient = useQuery({
    queryKey: ["patient", id],
    queryFn: () => getPatient(id),
    retry: false,
  });

  const may = (permission: string) => session.data?.permissions.includes(permission) ?? false;

  if (patient.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Opening the record…</span>
      </div>
    );
  }

  if (patient.isError) {
    const missing =
      patient.error instanceof ApiFailure && patient.error.code === "PATIENT_NOT_FOUND";
    return (
      <Page title={missing ? "No such patient" : "That record did not load"}>
        <p className="max-w-[54ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
          {missing
            ? "This record does not exist at your clinic. It may have been opened from an old link."
            : "Something went wrong reaching the server. Try again in a moment."}
        </p>
        <Link
          href="/patients"
          className="mt-6 inline-flex items-center gap-1.5 text-[15px] underline underline-offset-2"
        >
          <ArrowLeft className="size-3.5" />
          Back to patients
        </Link>
      </Page>
    );
  }

  const record = patient.data;

  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-10 lg:py-14">
      <Link
        href="/patients"
        className="mb-6 inline-flex items-center gap-1.5 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
      >
        <ArrowLeft className="size-3.5" />
        Back to patients
      </Link>

      <Header
        record={record}
        editing={editing}
        onEdit={() => setEditing(true)}
        mayEdit={may("patient:update")}
        mayArchive={may("patient:archive")}
      />

      {editing ? (
        <EditForm record={record} onDone={() => setEditing(false)} />
      ) : (
        <div className="mt-8 grid gap-6 lg:grid-cols-[1fr_20rem]">
          <Details record={record} />
          <div className="flex flex-col gap-6">
            <Allergies
              patientId={record.id}
              allergies={record.allergies}
              editable={may("patient:update") && record.status === "active"}
            />
            <Provenance record={record} />
          </div>
        </div>
      )}
    </div>
  );
}

function Header({
  record,
  editing,
  onEdit,
  mayEdit,
  mayArchive,
}: {
  record: Patient;
  editing: boolean;
  onEdit: () => void;
  mayEdit: boolean;
  mayArchive: boolean;
}) {
  const queries = useQueryClient();
  const archived = record.status === "archived";

  const presence = useMutation({
    mutationFn: () => (archived ? restorePatient(record.id) : archivePatient(record.id)),
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: ["patient", record.id] });
      void queries.invalidateQueries({ queryKey: ["patients"] });
    },
  });

  const line = [record.age, record.gender, record.blood_group].filter(Boolean).join(" · ");

  return (
    <header className="flex flex-wrap items-start justify-between gap-5">
      <div className="flex min-w-0 items-center gap-4">
        <span
          aria-hidden
          className="grid size-12 shrink-0 place-items-center rounded-full bg-[var(--accent-wash)] text-[16px] font-semibold text-[var(--color-marigold-700)]"
        >
          {initials(record.full_name)}
        </span>
        <div className="min-w-0">
          <h1 className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[26px] leading-tight font-semibold tracking-tight text-balance">
            {record.full_name}
            {archived && (
              <span className="rounded-full bg-[var(--surface-sunken)] px-2.5 py-0.5 text-[13px] font-normal text-[var(--text-muted)]">
                archived
              </span>
            )}
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-2.5 text-[14px] text-[var(--text-muted)]">
            <span className="font-mono text-[13px] text-[var(--text-subtle)]">
              {record.patient_number}
            </span>
            {record.preferred_name && <span>“{record.preferred_name}”</span>}
            {line && <span>{line}</span>}
          </p>
        </div>
      </div>

      {!editing && (
        <div className="flex items-center gap-2">
          {mayEdit && !archived && (
            <button
              type="button"
              onClick={onEdit}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
            >
              <Pencil className="size-3.5" />
              Edit
            </button>
          )}
          {mayArchive && (
            <button
              type="button"
              onClick={() => presence.mutate()}
              disabled={presence.isPending}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-50"
            >
              {archived ? <RotateCcw className="size-3.5" /> : <Archive className="size-3.5" />}
              {presence.isPending ? "…" : archived ? "Restore" : "Archive"}
            </button>
          )}
        </div>
      )}
    </header>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 border-t border-[var(--border)] px-5 py-3 first:border-0 sm:flex-row sm:gap-4">
      <dt className="text-[13px] text-[var(--text-muted)] sm:w-40 sm:shrink-0 sm:pt-0.5">
        {label}
      </dt>
      <dd className="min-w-0 text-[15px] break-words">
        {value || <span className="text-[var(--text-subtle)]">Not recorded</span>}
      </dd>
    </div>
  );
}

function Details({ record }: { record: Patient }) {
  const address = record.address ?? {};
  const contact = record.emergency_contact ?? {};

  const written = [
    address.line1,
    address.line2,
    address.city,
    address.state,
    address.postal_code,
  ]
    .filter((part) => String(part ?? "").trim())
    .join(", ");

  const emergency = [contact.name, contact.relationship && `(${contact.relationship})`]
    .filter(Boolean)
    .join(" ");

  return (
    <dl className="overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
      <Row label="Phone" value={readablePhone(record.phone)} />
      <Row label="Alternate phone" value={readablePhone(record.alternate_phone)} />
      <Row label="Email" value={record.email} />
      <Row
        label="Date of birth"
        value={
          record.date_of_birth
            ? new Date(record.date_of_birth).toLocaleDateString("en-IN", {
                day: "numeric",
                month: "long",
                year: "numeric",
              })
            : null
        }
      />
      <Row label="Address" value={written} />
      <Row
        label="Emergency contact"
        value={
          emergency ? (
            <>
              {emergency}
              {contact.phone && (
                <span className="block text-[14px] text-[var(--text-muted)] tabular">
                  {readablePhone(contact.phone)}
                </span>
              )}
            </>
          ) : null
        }
      />
      <Row
        label="Notes"
        value={record.notes && <span className="whitespace-pre-wrap">{record.notes}</span>}
      />
    </dl>
  );
}

function Provenance({ record }: { record: Patient }) {
  const when = new Date(record.created_at).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  });

  return (
    <p className="px-1 text-[13px] leading-relaxed text-[var(--text-muted)]">
      Registered {when}
      {record.registered_by_name ? ` by ${record.registered_by_name}` : ""}.
      {record.status === "archived" &&
        " Archived records keep everything attached to them; only the day-to-day lists hide them."}
    </p>
  );
}

function EditForm({ record, onDone }: { record: Patient; onDone: () => void }) {
  const queries = useQueryClient();
  const [draft, setDraft] = useState<PatientDraft>({
    first_name: record.first_name,
    last_name: record.last_name,
    preferred_name: record.preferred_name ?? "",
    phone: record.phone ?? "",
    alternate_phone: record.alternate_phone ?? "",
    email: record.email ?? "",
    date_of_birth: record.date_of_birth ?? "",
    gender: record.gender,
    blood_group: record.blood_group,
    address: record.address ?? {},
    emergency_contact: record.emergency_contact ?? {},
    notes: record.notes ?? "",
  });
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<DuplicateCandidate[]>([]);
  // Same reason as registering: two clicks land before the pending state
  // has had a chance to disable anything.
  const inFlight = useRef(false);

  // Correcting a number to one already on file is the other way two records
  // become one person's split history. This one warns and never blocks:
  // whoever is editing has the record in front of them.
  useEffect(() => {
    const phone = draft.phone?.trim();
    const email = draft.email?.trim();
    const untouched = phone === (record.phone ?? "") && email === (record.email ?? "");

    let current = true;
    const timer = setTimeout(() => {
      if (untouched) {
        setCandidates([]);
        return;
      }
      checkDuplicates({
        first_name: draft.first_name,
        last_name: draft.last_name,
        phone: phone || null,
        email: email || null,
        date_of_birth: draft.date_of_birth || null,
        exclude_id: record.id,
      })
        .then((found) => current && setCandidates(found))
        .catch(() => current && setCandidates([]));
    }, 400);

    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [
    draft.phone,
    draft.email,
    draft.first_name,
    draft.last_name,
    draft.date_of_birth,
    record,
  ]);

  const save = useMutation({
    mutationFn: () =>
      savePatient(record.id, {
        ...draft,
        preferred_name: draft.preferred_name?.trim() || null,
        phone: draft.phone?.trim() || null,
        alternate_phone: draft.alternate_phone?.trim() || null,
        email: draft.email?.trim() || null,
        date_of_birth: draft.date_of_birth || null,
        notes: draft.notes?.trim() || null,
      }),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: ["patient", record.id] });
      void queries.invalidateQueries({ queryKey: ["patients"] });
      onDone();
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.fields) setFields(error.fields);
      else setProblem(error instanceof Error ? error.message : "Something went wrong.");
    },
  });

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        setProblem(null);
        setFields({});
        if (inFlight.current) return;
        inFlight.current = true;
        save.mutate();
      }}
      noValidate
      className="mt-8"
    >
      {problem && <Problem>{problem}</Problem>}

      <Duplicates candidates={candidates} />

      <PatientFields
        draft={draft}
        onChange={(changes) => setDraft((current) => ({ ...current, ...changes }))}
        errors={fields}
      />

      <div className="mt-8 flex items-center gap-3 border-t border-[var(--border)] pt-6">
        <button
          type="submit"
          disabled={save.isPending || !draft.first_name.trim()}
          className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2.5 text-[15px] font-semibold text-[var(--color-ink-900)] transition-[filter,transform] duration-150 ease-[var(--ease-out-quint)] hover:brightness-[1.06] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60"
        >
          {save.isPending && <Loader2 className="size-4 animate-spin" />}
          {save.isPending ? "Saving" : "Save changes"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded-[var(--radius-field)] px-3 py-2 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
