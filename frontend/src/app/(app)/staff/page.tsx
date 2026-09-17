"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, MailCheck, UserPlus, X } from "lucide-react";
import { useState } from "react";
import { Field, Problem } from "@/components/auth/form";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { ApiFailure } from "@/lib/api";
import {
  changeRole,
  getInvitations,
  getRoles,
  getStaff,
  restoreMember,
  revokeInvitation,
  sendInvitation,
  suspendMember,
  type Invitation,
  type Role,
  type StaffMember,
} from "@/lib/clinic";

export default function StaffPage() {
  return (
    <Permitted permission="staff:manage">
      <StaffScreen />
    </Permitted>
  );
}

function StaffScreen() {
  const queries = useQueryClient();
  const [inviting, setInviting] = useState(false);

  const staff = useQuery({ queryKey: ["staff"], queryFn: getStaff, retry: false });
  const invitations = useQuery({
    queryKey: ["invitations"],
    queryFn: getInvitations,
    retry: false,
  });
  const roles = useQuery({ queryKey: ["roles"], queryFn: getRoles, retry: false });

  // Awaited by whoever calls it. Both lists below are drawn from these
  // queries, so a suspended member goes on looking active, and a sent
  // invitation goes on being absent, for as long as this takes.
  const refresh = () =>
    Promise.all([
      queries.invalidateQueries({ queryKey: ["staff"] }),
      queries.invalidateQueries({ queryKey: ["invitations"] }),
    ]);

  if (staff.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Loading the team…</span>
      </div>
    );
  }

  return (
    <Page
      title="Staff"
      blurb="Everyone who can sign in to this clinic, and what each of them can do."
      action={
        <button
          type="button"
          onClick={() => setInviting(true)}
          className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
        >
          <UserPlus className="size-4" />
          Invite someone
        </button>
      }
    >
      {inviting && (
        <InviteForm
          roles={roles.data ?? []}
          onClose={() => setInviting(false)}
          onSent={async () => {
            await refresh();
            setInviting(false);
          }}
        />
      )}

      <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]">
        {(staff.data ?? []).map((member) => (
          <MemberRow
            key={member.id}
            member={member}
            roles={roles.data ?? []}
            onChanged={refresh}
          />
        ))}
      </ul>

      {(invitations.data?.length ?? 0) > 0 && (
        <section className="mt-10">
          <h2 className="text-[17px] font-semibold tracking-tight">Waiting to accept</h2>
          <p className="mt-1 mb-4 text-[14px] text-[var(--text-muted)]">
            An invitation expires after seven days.
          </p>
          <ul className="divide-y divide-[var(--border)] overflow-hidden rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)]">
            {(invitations.data ?? []).map((invitation) => (
              <InvitationRow key={invitation.id} invitation={invitation} onChanged={refresh} />
            ))}
          </ul>
        </section>
      )}
    </Page>
  );
}

function MemberRow({
  member,
  roles,
  onChanged,
}: {
  member: StaffMember;
  roles: Role[];
  onChanged: () => Promise<unknown>;
}) {
  const [problem, setProblem] = useState<string | null>(null);
  const suspended = member.status !== "active";

  const fail = (error: unknown) =>
    setProblem(error instanceof ApiFailure ? error.message : "Something went wrong.");

  const role = useMutation({
    mutationFn: (slug: string) => changeRole(member.id, slug),
    onSuccess: async () => {
      setProblem(null);
      await onChanged();
    },
    onError: fail,
  });

  const presence = useMutation({
    mutationFn: () => (suspended ? restoreMember(member.id) : suspendMember(member.id)),
    onSuccess: async () => {
      setProblem(null);
      await onChanged();
    },
    onError: fail,
  });

  return (
    <li className="flex flex-col gap-3 px-5 py-4 sm:flex-row sm:flex-wrap sm:items-center sm:gap-4">
      <div className="min-w-0 flex-1">
        <p className="flex items-center gap-2 text-[15px] font-medium">
          <span className="truncate">
            {member.first_name} {member.last_name}
          </span>
          {member.is_you && (
            <span className="shrink-0 rounded-full bg-[var(--surface-sunken)] px-2 py-0.5 text-[12px] font-normal text-[var(--text-muted)]">
              you
            </span>
          )}
          {suspended && (
            <span className="shrink-0 rounded-full bg-[color-mix(in_srgb,var(--color-state-noshow)_12%,transparent)] px-2 py-0.5 text-[12px] font-normal text-[var(--color-state-noshow)]">
              suspended
            </span>
          )}
        </p>
        <p className="truncate text-[14px] text-[var(--text-muted)]">{member.email}</p>
        {problem && (
          <p role="alert" className="mt-1 text-[13px] text-[var(--color-state-noshow)]">
            {problem}
          </p>
        )}
      </div>

      <div className="flex items-center gap-3">
        <label className="sr-only" htmlFor={`role-${member.id}`}>
          Role for {member.first_name}
        </label>
        <select
          id={`role-${member.id}`}
          value={member.role?.slug ?? ""}
          disabled={role.isPending || suspended}
          onChange={(event) => role.mutate(event.target.value)}
          className="flex-1 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-2.5 py-1.5 text-[14px] disabled:opacity-50 sm:flex-none"
        >
          {roles.map((option) => (
            <option key={option.slug} value={option.slug}>
              {option.name}
            </option>
          ))}
        </select>

        <button
          type="button"
          onClick={() => presence.mutate()}
          disabled={presence.isPending || member.is_you}
          title={member.is_you ? "You cannot suspend your own account" : undefined}
          className="rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {presence.isPending ? "…" : suspended ? "Restore" : "Suspend"}
        </button>
      </div>
    </li>
  );
}

function InvitationRow({
  invitation,
  onChanged,
}: {
  invitation: Invitation;
  onChanged: () => Promise<unknown>;
}) {
  const revoke = useMutation({
    mutationFn: () => revokeInvitation(invitation.id),
    onSuccess: onChanged,
  });

  return (
    <li className="flex flex-wrap items-center gap-4 bg-[var(--surface)] px-5 py-3.5">
      <MailCheck className="size-4 shrink-0 text-[var(--text-subtle)]" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px]">{invitation.email}</p>
        <p className="text-[13px] text-[var(--text-muted)]">
          {invitation.role.name} · invited by {invitation.invited_by_name}
        </p>
      </div>
      <button
        type="button"
        onClick={() => revoke.mutate()}
        disabled={revoke.isPending}
        className="inline-flex items-center gap-1.5 rounded-[var(--radius-field)] px-2.5 py-1.5 text-[14px] text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)] disabled:opacity-50"
      >
        <X className="size-3.5" />
        Cancel
      </button>
    </li>
  );
}

function InviteForm({
  roles,
  onClose,
  onSent,
}: {
  roles: Role[];
  onClose: () => void;
  onSent: () => Promise<unknown>;
}) {
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    email: "",
    role_slug: "receptionist",
  });
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);

  const send = useMutation({
    mutationFn: () => sendInvitation(form),
    onSuccess: onSent,
    onError: (error) => {
      if (error instanceof ApiFailure && error.fields) setFields(error.fields);
      else setProblem(error instanceof Error ? error.message : "Something went wrong.");
    },
  });

  return (
    <div className="mb-8 rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] p-5">
      <h2 className="mb-1 text-[17px] font-semibold tracking-tight">Invite someone</h2>
      <p className="mb-5 text-[14px] text-[var(--text-muted)]">
        They get a link to set their own password. It joins them to this clinic, with the role
        you pick here.
      </p>

      {problem && <Problem>{problem}</Problem>}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setFields({});
          setProblem(null);
          send.mutate();
        }}
        noValidate
        className="flex flex-col gap-4"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="First name"
            name="first_name"
            value={form.first_name}
            onChange={(v) => setForm({ ...form, first_name: v })}
            error={fields.first_name}
            autoFocus
            required
          />
          <Field
            label="Last name"
            name="last_name"
            value={form.last_name}
            onChange={(v) => setForm({ ...form, last_name: v })}
            error={fields.last_name}
            required
          />
        </div>
        <Field
          label="Email"
          name="email"
          type="email"
          value={form.email}
          onChange={(v) => setForm({ ...form, email: v })}
          error={fields.email}
          required
          placeholder="them@clinic.com"
        />

        <div>
          <label htmlFor="invite-role" className="mb-1.5 block text-[14px] font-medium">
            Role
          </label>
          <select
            id="invite-role"
            value={form.role_slug}
            onChange={(event) => setForm({ ...form, role_slug: event.target.value })}
            className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2.5 text-[15px]"
          >
            {roles.map((role) => (
              <option key={role.slug} value={role.slug}>
                {role.name}
              </option>
            ))}
          </select>
          <p className="mt-1.5 text-[13px] text-[var(--text-muted)]">
            {roles.find((role) => role.slug === form.role_slug)?.description}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={send.isPending}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2 text-[14px] font-medium text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-50"
          >
            {send.isPending && <Loader2 className="size-4 animate-spin" />}
            {send.isPending ? "Sending" : "Send invitation"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="rounded-[var(--radius-field)] px-3 py-2 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
          >
            Cancel
          </button>
        </div>
      </form>
    </div>
  );
}
