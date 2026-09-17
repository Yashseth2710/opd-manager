"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Aside, Field, Heading, Problem, Submit } from "@/components/auth/form";
import { ApiFailure } from "@/lib/api";
import { acceptInvitation, previewInvitation } from "@/lib/clinic";

export default function JoinPage() {
  return (
    <Suspense fallback={<Heading title="Joining your clinic" />}>
      <Join />
    </Suspense>
  );
}

function Join() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const invitation = useQuery({
    queryKey: ["invitation", token],
    queryFn: () => previewInvitation(token),
    enabled: Boolean(token),
    retry: false,
  });

  if (!token || invitation.isError) {
    return (
      <>
        <Heading
          title="That invitation is not valid"
          blurb="It may have expired, been cancelled, or already been used. Ask whoever invited you to send another."
        />
        <Aside>
          <Link href="/login" className="underline underline-offset-2">
            Go to sign in
          </Link>
        </Aside>
      </>
    );
  }

  if (invitation.isPending) {
    return (
      <div className="flex items-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <p className="text-[15px]">Checking your invitation…</p>
      </div>
    );
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;

    if (password !== confirmation) {
      setFieldError("Both passwords need to match.");
      return;
    }

    setBusy(true);
    setProblem(null);
    setFieldError(undefined);

    try {
      await acceptInvitation(token, password);
      router.replace("/login?joined=1");
    } catch (error) {
      if (!(error instanceof ApiFailure)) throw error;
      if (error.fields?.password) setFieldError(error.fields.password);
      else setProblem(error.message);
    } finally {
      setBusy(false);
    }
  }

  const { clinic_name, role_name, email, first_name } = invitation.data;

  return (
    <>
      <Heading
        title={first_name ? `Welcome, ${first_name}` : "Welcome"}
        blurb={`You have been added to ${clinic_name} as ${role_name.toLowerCase()}. Choose a password and you are in.`}
      />

      {problem && <Problem>{problem}</Problem>}

      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <div>
          <p className="mb-1.5 text-[14px] font-medium">Your email</p>
          <p className="rounded-[var(--radius-field)] border border-[var(--border)] bg-[var(--surface-sunken)] px-3 py-2.5 text-[15px] text-[var(--text-muted)]">
            {email}
          </p>
          <p className="mt-1.5 text-[13px] text-[var(--text-muted)]">
            This is the address the invitation was sent to, so it cannot be changed here.
          </p>
        </div>

        <Field
          label="Choose a password"
          name="password"
          type="password"
          value={password}
          onChange={setPassword}
          error={fieldError}
          hint="At least 8 characters."
          autoComplete="new-password"
          autoFocus
          required
        />
        <Field
          label="Password again"
          name="confirmation"
          type="password"
          value={confirmation}
          onChange={setConfirmation}
          autoComplete="new-password"
          required
        />

        <Submit busy={busy} busyLabel="Setting up">
          Join {clinic_name}
        </Submit>
      </form>
    </>
  );
}
