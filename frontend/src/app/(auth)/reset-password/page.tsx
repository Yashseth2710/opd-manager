"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Aside, Field, Heading, Problem, Submit } from "@/components/auth/form";
import { ApiFailure } from "@/lib/api";
import { completeReset } from "@/lib/auth";

export default function ResetPasswordPage() {
  return (
    <Suspense fallback={<Heading title="Choose a new password" />}>
      <ResetForm />
    </Suspense>
  );
}

function ResetForm() {
  const router = useRouter();
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [fieldError, setFieldError] = useState<string | undefined>();
  const [spent, setSpent] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!token) {
    return (
      <>
        <Heading
          title="That link is incomplete"
          blurb="The address is missing the part that identifies your request. Open the link from your email again, or ask for a new one."
        />
        <Link
          href="/forgot-password"
          className="inline-flex w-full items-center justify-center rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2.5 text-[15px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
        >
          Ask for a new link
        </Link>
      </>
    );
  }

  if (spent) {
    return (
      <>
        <Heading
          title="That link has been used"
          blurb="A reset link works once and lasts 30 minutes. Ask for another and we will send a fresh one."
        />
        <Link
          href="/forgot-password"
          className="inline-flex w-full items-center justify-center rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2.5 text-[15px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
        >
          Ask for a new link
        </Link>
        <Aside>
          <Link href="/login" className="underline underline-offset-2">
            Back to sign in
          </Link>
        </Aside>
      </>
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
      await completeReset(token, password);
      router.replace("/login?reset=done");
    } catch (error) {
      if (!(error instanceof ApiFailure)) throw error;
      if (error.code === "TOKEN_INVALID" || error.code === "TOKEN_EXPIRED") setSpent(true);
      else if (error.fields?.password) setFieldError(error.fields.password);
      else setProblem(error.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Heading
        title="Choose a new password"
        blurb="Once you save it, every device signed in to this account is signed out."
      />

      {problem && <Problem>{problem}</Problem>}

      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <Field
          label="New password"
          name="password"
          type="password"
          value={password}
          onChange={setPassword}
          error={fieldError}
          hint="At least 10 characters."
          autoComplete="new-password"
          autoFocus
          required
        />
        <Field
          label="New password again"
          name="confirmation"
          type="password"
          value={confirmation}
          onChange={setConfirmation}
          autoComplete="new-password"
          required
        />
        <Submit busy={busy} busyLabel="Saving">
          Save new password
        </Submit>
      </form>

      <Aside>
        <Link href="/login" className="underline underline-offset-2">
          Back to sign in
        </Link>
      </Aside>
    </>
  );
}
