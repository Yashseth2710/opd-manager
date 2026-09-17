"use client";

import { CheckCircle2, Loader2 } from "lucide-react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import {
  Aside,
  DemoEmailNotice,
  Field,
  Heading,
  Problem,
  Submit,
} from "@/components/auth/form";
import { ApiFailure } from "@/lib/api";
import { confirmEmail, describeWait, resendConfirmation } from "@/lib/auth";

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={<Heading title="Confirming your email" />}>
      <Verify />
    </Suspense>
  );
}

type Outcome = "working" | "confirmed" | "unusable" | "no-token";

function Verify() {
  const token = useSearchParams().get("token");
  const [outcome, setOutcome] = useState<Outcome>(token ? "working" : "no-token");
  // Strict mode mounts effects twice in development. Without this the token
  // is redeemed on the first pass and reported unusable on the second.
  const attempted = useRef(false);

  useEffect(() => {
    if (!token || attempted.current) return;
    attempted.current = true;

    confirmEmail(token)
      .then(() => setOutcome("confirmed"))
      .catch(() => setOutcome("unusable"));
  }, [token]);

  if (outcome === "working") {
    return (
      <div className="flex items-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <p className="text-[15px]">Confirming your email…</p>
      </div>
    );
  }

  if (outcome === "confirmed") {
    return (
      <>
        <div className="mb-5 grid size-11 place-items-center rounded-full bg-[color-mix(in_srgb,var(--color-state-completed)_14%,transparent)]">
          <CheckCircle2 className="size-6 text-[var(--color-state-completed)]" />
        </div>
        <Heading
          title="Email confirmed"
          blurb="Your address is verified. You can sign in now."
        />
        <Link
          href="/login"
          className="inline-flex w-full items-center justify-center rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2.5 text-[15px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
        >
          Sign in
        </Link>
      </>
    );
  }

  return <ResendForm expired={outcome === "unusable"} />;
}

function ResendForm({ expired }: { expired: boolean }) {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setProblem(null);

    try {
      await resendConfirmation(email);
      setSent(true);
    } catch (error) {
      if (!(error instanceof ApiFailure)) throw error;
      setProblem(
        error.code === "RATE_LIMITED"
          ? `Too many requests for this email. Try again in ${describeWait(error.retryAfterSeconds)}.`
          : error.message,
      );
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <>
        <Heading
          title="Check your email"
          blurb={`If ${email} is waiting to be confirmed, a new link is on its way.`}
        />
        <DemoEmailNotice />
        <Aside>
          <Link href="/login" className="underline underline-offset-2">
            Back to sign in
          </Link>
        </Aside>
      </>
    );
  }

  return (
    <>
      <Heading
        title={expired ? "That link no longer works" : "Confirm your email"}
        blurb={
          expired
            ? "A confirmation link works once and lasts 30 minutes. Tell us your email and we will send another."
            : "Tell us the email you signed up with and we will send a confirmation link."
        }
      />

      {problem && <Problem>{problem}</Problem>}

      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <Field
          label="Email"
          name="email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          autoFocus
          required
          placeholder="you@clinic.com"
        />
        <Submit busy={busy} busyLabel="Sending">
          Send a new link
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
