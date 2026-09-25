"use client";

import type { Route } from "next";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Aside, Field, Heading, Problem, Submit } from "@/components/auth/form";
import { ApiFailure } from "@/lib/api";
import { describeWait, signIn, type ClinicChoice, type Session } from "@/lib/auth";

export default function LoginPage() {
  return (
    <Suspense fallback={<Heading title="Sign in" />}>
      <SignInForm />
    </Suspense>
  );
}

function SignInForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = params.get("next");
  const justReset = params.get("reset") === "done";
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [choices, setChoices] = useState<ClinicChoice[] | null>(null);
  const [clinic, setClinic] = useState("");
  const [problem, setProblem] = useState<React.ReactNode>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setProblem(null);

    try {
      const session = await signIn({
        email,
        password,
        ...(clinic ? { organization_slug: clinic } : {}),
      });
      // Only a path within the app, so a crafted ?next= cannot bounce
      // someone to another site straight after they sign in.
      const safeNext =
        next && next.startsWith("/") && !next.startsWith("//") ? (next as Route) : null;
      router.replace(safeNext ?? landing(session));
    } catch (error) {
      if (!(error instanceof ApiFailure)) throw error;
      setProblem(explain(error, setChoices, setClinic));
    } finally {
      setBusy(false);
    }
  }

  if (choices) {
    return (
      <>
        <Heading
          title="Which clinic?"
          blurb="This email is used at more than one clinic. Pick the one you are signing in to."
        />
        <ul className="flex flex-col gap-2">
          {choices.map((choice) => (
            <li key={choice.slug}>
              <button
                type="button"
                onClick={() => {
                  setClinic(choice.slug);
                  setChoices(null);
                }}
                className="w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] px-4 py-3 text-left transition-colors hover:border-[var(--accent)] hover:bg-[var(--accent-wash)]"
              >
                <span className="block text-[15px] font-medium">{choice.name}</span>
                <span className="block font-mono text-[12px] text-[var(--text-subtle)]">
                  {choice.slug}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </>
    );
  }

  return (
    <>
      <Heading title="Sign in" blurb="Pick up where the clinic left off." />

      {justReset && (
        <p className="mb-5 rounded-[var(--radius-field)] border border-[color-mix(in_srgb,var(--color-state-completed)_35%,transparent)] bg-[color-mix(in_srgb,var(--color-state-completed)_9%,transparent)] px-3.5 py-3 text-[14px]">
          Your password has been changed. Sign in with the new one.
        </p>
      )}

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
        <Field
          label="Password"
          name="password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
          required
        />

        {clinic && (
          <p className="text-[13px] text-[var(--text-muted)]">
            Signing in to <span className="font-mono text-[12px]">{clinic}</span>.{" "}
            <button
              type="button"
              onClick={() => setClinic("")}
              className="underline underline-offset-2 hover:text-[var(--text)]"
            >
              Change
            </button>
          </p>
        )}

        <Submit busy={busy} busyLabel="Signing in">
          Sign in
        </Submit>
      </form>

      <p className="mt-4 text-center text-[14px]">
        <Link
          href="/forgot-password"
          className="text-[var(--text-muted)] underline underline-offset-2 hover:text-[var(--text)]"
        >
          Forgotten your password?
        </Link>
      </p>

      <Aside>
        New here?{" "}
        <Link
          href="/register"
          className="font-medium text-[var(--text)] underline underline-offset-2"
        >
          Set up your clinic
        </Link>
      </Aside>
    </>
  );
}

/** A platform account has no clinic to open, only the platform's own pages. */
function landing(session: Session): Route {
  if (!session.organization) return "/admin" as Route;
  return session.organization.onboarding_completed_at ? "/dashboard" : "/settings";
}

function explain(
  error: ApiFailure,
  setChoices: (choices: ClinicChoice[]) => void,
  setClinic: (slug: string) => void,
): React.ReactNode {
  switch (error.code) {
    case "CLINIC_CHOICE_REQUIRED":
      setChoices(error.choices ?? []);
      setClinic("");
      return null;
    case "ACCOUNT_LOCKED":
      return `Too many attempts on this email. Try again in ${describeWait(error.retryAfterSeconds)}.`;
    case "RATE_LIMITED":
      return `Too many sign-in attempts from this device. Try again in ${describeWait(error.retryAfterSeconds)}.`;
    case "EMAIL_NOT_VERIFIED":
      return (
        <>
          Confirm your email address before signing in. Check your inbox, or{" "}
          <Link href="/verify-email" className="underline underline-offset-2">
            send the link again
          </Link>
          .
        </>
      );
    default:
      return error.message;
  }
}
