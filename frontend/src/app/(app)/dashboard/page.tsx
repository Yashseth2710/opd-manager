"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { currentSession } from "@/lib/auth";
import { SignOutButton } from "@/components/auth/sign-out";

export default function DashboardPage() {
  const { data, isPending, isError } = useQuery({
    queryKey: ["session"],
    queryFn: currentSession,
    retry: false,
  });

  if (isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Loading your clinic…</span>
      </div>
    );
  }

  if (isError || !data) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <p className="text-[15px] text-[var(--text-muted)]">
          Your session has ended.{" "}
          <a href="/login" className="underline underline-offset-2">
            Sign in again
          </a>
          .
        </p>
      </div>
    );
  }

  return (
    <main className="mx-auto w-full max-w-3xl px-6 py-14">
      <div className="flex items-start justify-between gap-6">
        <div>
          <h1 className="text-[26px] font-semibold tracking-tight">
            {data.organization?.name ?? "Your clinic"}
          </h1>
          <p className="mt-1.5 text-[15px] text-[var(--text-muted)]">
            Signed in as {data.user.first_name} {data.user.last_name}
          </p>
        </div>
        <SignOutButton />
      </div>

      <dl className="mt-10 grid gap-px overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--border)] sm:grid-cols-3">
        <Cell label="Role" value={data.role.replace("-", " ")} />
        <Cell label="Clinic address" value={data.organization?.slug ?? "—"} mono />
        <Cell label="Permissions" value={String(data.permissions.length)} />
      </dl>

      <p className="mt-10 text-[15px] leading-relaxed text-[var(--text-muted)]">
        Patients, appointments and the queue arrive next. Nothing here is real patient data.
      </p>
    </main>
  );
}

function Cell({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="bg-[var(--surface)] px-5 py-4">
      <dt className="text-[13px] text-[var(--text-subtle)]">{label}</dt>
      <dd className={`mt-1 text-[15px] font-medium ${mono ? "font-mono text-[13px]" : ""}`}>
        {value}
      </dd>
    </div>
  );
}
