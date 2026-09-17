"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
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
import { describeWait, previewSlug, registerClinic } from "@/lib/auth";

export default function RegisterPage() {
  const router = useRouter();
  const [firstName, setFirstName] = useState("");
  const [lastName, setLastName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [clinicName, setClinicName] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [pending, setPending] = useState<{ email: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setProblem(null);
    setFields({});

    try {
      const result = await registerClinic({
        clinic_name: clinicName,
        first_name: firstName,
        last_name: lastName,
        email,
        password,
      });

      if (result.session) {
        router.replace("/settings");
        return;
      }
      setPending({ email });
    } catch (error) {
      if (!(error instanceof ApiFailure)) throw error;
      if (error.fields) setFields(error.fields);
      else if (error.code === "RATE_LIMITED") {
        setProblem(
          `Too many clinics created from this device. Try again in ${describeWait(error.retryAfterSeconds)}.`,
        );
      } else setProblem(error.message);
    } finally {
      setBusy(false);
    }
  }

  if (pending) {
    return (
      <>
        <Heading
          title="Confirm your email"
          blurb={`We sent a link to ${pending.email}. Open it to finish setting up your clinic.`}
        />
        <p className="text-[14px] leading-relaxed text-[var(--text-muted)]">
          The link works once and expires in 30 minutes.
        </p>
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
        title="Set up your clinic"
        blurb="You will be its administrator, and can invite doctors and reception staff once you are in."
      />

      {problem && <Problem>{problem}</Problem>}

      <form onSubmit={submit} noValidate className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <Field
            label="First name"
            name="first_name"
            value={firstName}
            onChange={setFirstName}
            autoComplete="given-name"
            autoFocus
            required
          />
          <Field
            label="Last name"
            name="last_name"
            value={lastName}
            onChange={setLastName}
            autoComplete="family-name"
            required
          />
        </div>

        <Field
          label="Email"
          name="email"
          type="email"
          value={email}
          onChange={setEmail}
          error={fields.email}
          autoComplete="email"
          required
          placeholder="you@clinic.com"
        />

        <Field
          label="Password"
          name="password"
          type="password"
          value={password}
          onChange={setPassword}
          error={fields.password}
          hint="At least 8 characters. A phrase you can remember beats a short scramble."
          autoComplete="new-password"
          required
        />

        <div className="mt-2 border-t border-[var(--border)] pt-5">
          <Field
            label="Clinic name"
            name="clinic_name"
            value={clinicName}
            onChange={setClinicName}
            error={fields.clinic_name}
            required
            placeholder="Sunrise Family Clinic"
            hint={
              clinicName.trim().length > 1 ? (
                <>
                  Your clinic address will be{" "}
                  <span className="font-mono text-[12px] text-[var(--text)]">
                    {previewSlug(clinicName)}
                  </span>
                </>
              ) : (
                "You can change how this reads later, in settings."
              )
            }
          />
        </div>

        <Submit busy={busy} busyLabel="Setting up">
          Create clinic
        </Submit>
      </form>

      <DemoEmailNotice />

      <Aside>
        Already have an account?{" "}
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
