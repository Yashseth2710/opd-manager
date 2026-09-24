"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Pencil, RotateCcw, UserMinus } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useRef, useState } from "react";
import { Problem } from "@/components/auth/form";
import { showFirstProblem } from "@/components/common/first-problem";
import { Availability } from "@/components/doctors/availability";
import { DoctorFields } from "@/components/doctors/form";
import { Leaves } from "@/components/doctors/leaves";
import { Schedule } from "@/components/doctors/schedule";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { ApiFailure } from "@/lib/api";
import { currentSession } from "@/lib/auth";
import { getSettings, getStaff } from "@/lib/clinic";
import {
  cleaned,
  deactivateDoctor,
  getDoctor,
  initials,
  restoreDoctor,
  saveDoctor,
  type Doctor,
  type DoctorDraft,
  refreshFreeTimes,
} from "@/lib/doctors";
import { readablePhone } from "@/lib/patients";

export default function DoctorPage() {
  return (
    <Permitted permission="doctor:read">
      <Profile />
    </Permitted>
  );
}

function Profile() {
  const id = String(useParams().id);
  const [editing, setEditing] = useState(false);

  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const doctor = useQuery({
    queryKey: ["doctor", id],
    queryFn: () => getDoctor(id),
    retry: false,
  });

  const mayManage = session.data?.permissions.includes("doctor:manage") ?? false;

  if (doctor.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Opening the profile…</span>
      </div>
    );
  }

  if (doctor.isError) {
    const missing =
      doctor.error instanceof ApiFailure && doctor.error.code === "DOCTOR_NOT_FOUND";
    return (
      <Page title={missing ? "No such doctor" : "That profile did not load"}>
        <p className="max-w-[54ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
          {missing
            ? "This doctor does not exist at your clinic. It may have been opened from an old link."
            : "Something went wrong reaching the server. Try again in a moment."}
        </p>
        <Link
          href="/doctors"
          className="mt-6 inline-flex items-center gap-1.5 text-[15px] underline underline-offset-2"
        >
          <ArrowLeft className="size-3.5" />
          Back to doctors
        </Link>
      </Page>
    );
  }

  const record = doctor.data;
  const practising = record.status === "active";

  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-10 lg:py-14">
      <Link
        href="/doctors"
        className="mb-6 inline-flex items-center gap-1.5 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
      >
        <ArrowLeft className="size-3.5" />
        Back to doctors
      </Link>

      <Header
        record={record}
        editing={editing}
        onEdit={() => setEditing(true)}
        mayManage={mayManage}
      />

      {editing ? (
        <EditForm record={record} onDone={() => setEditing(false)} />
      ) : (
        <div className="mt-8 flex flex-col gap-6">
          <div className="grid items-start gap-6 lg:grid-cols-[1fr_20rem]">
            <Details record={record} />
            <Availability doctorId={record.id} />
          </div>

          <Schedule
            doctorId={record.id}
            blocks={record.schedule}
            editable={mayManage && practising}
            slotMinutes={record.slot_duration_minutes}
          />

          <Leaves
            doctorId={record.id}
            leaves={record.leaves}
            editable={mayManage && practising}
          />
        </div>
      )}
    </div>
  );
}

function Header({
  record,
  editing,
  onEdit,
  mayManage,
}: {
  record: Doctor;
  editing: boolean;
  onEdit: () => void;
  mayManage: boolean;
}) {
  const queries = useQueryClient();
  const [problem, setProblem] = useState<string | null>(null);
  const practising = record.status === "active";

  const presence = useMutation({
    mutationFn: () => (practising ? deactivateDoctor(record.id) : restoreDoctor(record.id)),
    onSuccess: async () => {
      setProblem(null);
      // Only the record is waited for. The badge and the buttons are drawn
      // from it, so it has to be here before the screen changes. The free
      // times have their own place to show that they are loading, and
      // holding the whole screen for them means one slow panel can keep a
      // change that already happened off the screen entirely.
      await queries.invalidateQueries({ queryKey: ["doctor", record.id] });
      void refreshFreeTimes(queries, record.id);
      void queries.invalidateQueries({ queryKey: ["doctors"] });
    },
    onError: (error) =>
      setProblem(
        error instanceof Error ? error.message : "That did not go through. Try again.",
      ),
  });

  const line = [record.speciality, record.qualifications, record.room && `Room ${record.room}`]
    .filter(Boolean)
    .join(" · ");

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
          <h1 className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[26px] leading-tight font-semibold tracking-tight break-words text-balance">
            <span className="min-w-0 break-words">{record.display_name}</span>
            {!practising && (
              <span className="rounded-full bg-[var(--surface-sunken)] px-2.5 py-0.5 text-[13px] font-normal text-[var(--text-muted)]">
                stood down
              </span>
            )}
          </h1>
          {line && <p className="mt-1 text-[14px] text-[var(--text-muted)]">{line}</p>}
        </div>
      </div>

      {!editing && mayManage && (
        <div className="flex items-center gap-2">
          {practising && (
            <button
              type="button"
              onClick={onEdit}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
            >
              <Pencil className="size-3.5" />
              Edit
            </button>
          )}
          <button
            type="button"
            onClick={() => presence.mutate()}
            disabled={presence.isPending}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-50"
          >
            {practising ? (
              <UserMinus className="size-3.5" />
            ) : (
              <RotateCcw className="size-3.5" />
            )}
            {presence.isPending ? "…" : practising ? "Stand down" : "Bring back"}
          </button>
        </div>
      )}

      {problem && (
        <p role="alert" className="w-full text-[13px] text-[var(--color-state-noshow)]">
          {problem}
        </p>
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

/** Says where a figure came from, so nobody wonders why it moved. */
function Fee({ amount, fromClinic }: { amount: string; fromClinic: boolean }) {
  return (
    <>
      <span className="tabular">₹{amount}</span>
      {fromClinic && (
        <span className="ml-2 text-[13px] text-[var(--text-muted)]">following the clinic</span>
      )}
    </>
  );
}

function Details({ record }: { record: Doctor }) {
  return (
    <dl className="overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
      <Row
        label="Consultation"
        value={<Fee amount={record.consultation_fee} fromClinic={record.fee_from_clinic} />}
      />
      <Row
        label="Follow-up"
        value={
          <Fee amount={record.follow_up_fee} fromClinic={record.follow_up_fee_from_clinic} />
        }
      />
      <Row
        label="Appointment length"
        value={
          <>
            <span className="tabular">{record.slot_duration_minutes} minutes</span>
            {record.own_slot_duration_minutes === null && (
              <span className="ml-2 text-[13px] text-[var(--text-muted)]">
                following the clinic
              </span>
            )}
          </>
        }
      />
      <Row label="Registration number" value={record.registration_number} />
      <Row
        label="Years in practice"
        value={record.years_of_experience === null ? null : String(record.years_of_experience)}
      />
      <Row label="Phone" value={readablePhone(record.phone)} />
      <Row label="Email" value={record.email} />
      <Row
        label="Languages"
        value={
          record.languages?.length ? (
            <span className="flex flex-wrap gap-1.5">
              {record.languages.map((language) => (
                <span
                  key={language}
                  className="rounded-full bg-[var(--surface-sunken)] px-2.5 py-0.5 text-[13px]"
                >
                  {language}
                </span>
              ))}
            </span>
          ) : null
        }
      />
      <Row
        label="Signs in as"
        value={
          record.account_name ?? (
            <span className="text-[var(--text-subtle)]">No account yet</span>
          )
        }
      />
      <Row
        label="About"
        value={record.bio && <span className="whitespace-pre-wrap">{record.bio}</span>}
      />
    </dl>
  );
}

function EditForm({ record, onDone }: { record: Doctor; onDone: () => void }) {
  const queries = useQueryClient();
  const settings = useQuery({ queryKey: ["settings"], queryFn: getSettings, retry: false });
  const staff = useQuery({ queryKey: ["staff"], queryFn: getStaff, retry: false });

  const [draft, setDraft] = useState<DoctorDraft>({
    title: record.title,
    first_name: record.first_name,
    last_name: record.last_name,
    speciality: record.speciality ?? "",
    qualifications: record.qualifications ?? "",
    registration_number: record.registration_number ?? "",
    years_of_experience: record.years_of_experience,
    phone: record.phone ?? "",
    email: record.email ?? "",
    room: record.room ?? "",
    languages: record.languages ?? [],
    bio: record.bio ?? "",
    // The doctor's own figures, not the ones that apply, so an empty box
    // still means "follow the clinic" after a round trip through the form.
    consultation_fee: record.own_consultation_fee ?? "",
    follow_up_fee: record.own_follow_up_fee ?? "",
    slot_duration_minutes: record.own_slot_duration_minutes,
    user_id: record.user_id,
  });
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const inFlight = useRef(false);

  const save = useMutation({
    mutationFn: () => saveDoctor(record.id, cleaned(draft)),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: async () => {
      // The details behind the form are drawn from the record, so that one
      // is waited for. The rest can land in their own time.
      await queries.invalidateQueries({ queryKey: ["doctor", record.id] });
      void refreshFreeTimes(queries, record.id);
      void queries.invalidateQueries({ queryKey: ["doctors"] });
      void queries.invalidateQueries({ queryKey: ["specialities"] });
      onDone();
    },
    onError: (error) => {
      if (error instanceof ApiFailure && error.fields) {
        setFields(error.fields);
        setProblem(null);
        showFirstProblem(error.fields);
      } else {
        setProblem(error instanceof Error ? error.message : "Something went wrong.");
      }
    },
  });

  const accounts = (staff.data ?? [])
    .filter((member) => member.status === "active")
    .map((member) => ({
      value: member.id,
      label: `${member.first_name} ${member.last_name} · ${member.email}`,
    }));

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

      <DoctorFields
        draft={draft}
        onChange={(changes) => setDraft((current) => ({ ...current, ...changes }))}
        errors={fields}
        clinic={settings.data}
        accounts={accounts}
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
