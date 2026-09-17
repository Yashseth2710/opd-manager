"use client";

import Link from "next/link";
import { useState } from "react";
import {
  Aside,
  DemoEmailNotice,
  Field,
  Heading,
  Problem,
  Submit,
} from "@/components/auth/form";
import { ApiFailure } from "@/lib/api";
import { describeWait, requestReset } from "@/lib/auth";

export default function ForgotPasswordPage() {
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
      await requestReset(email);
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
        {/* Worded so it reads the same whether or not the address has an
            account, because the server answers both identically. */}
        <Heading
          title="Check your email"
          blurb={`If ${email} has an account, a link to choose a new password is on its way.`}
        />
        <p className="text-[14px] leading-relaxed text-[var(--text-muted)]">
          The link works once and expires in 30 minutes. Your current password keeps working
          until you choose a new one.
        </p>
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
        title="Reset your password"
        blurb="Tell us the email you sign in with and we will send a link to set a new password."
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
          Send the link
        </Submit>
      </form>

      <Aside>
        Remembered it?{" "}
        <Link
          href="/login"
          className="font-medium text-[var(--text)] underline underline-offset-2"
        >
          Sign in
        </Link>
      </Aside>
    </>
  );
}
