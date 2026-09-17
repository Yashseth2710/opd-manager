"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { currentSession } from "@/lib/auth";

export default function OnboardingPage() {
  const { data, isPending } = useQuery({
    queryKey: ["session"],
    queryFn: currentSession,
    retry: false,
  });

  if (isPending) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Loading…</span>
      </div>
    );
  }

  return (
    <main className="mx-auto w-full max-w-xl px-6 py-20">
      <h1 className="text-[26px] font-semibold tracking-tight text-balance">
        {data?.organization?.name ?? "Your clinic"} is ready
      </h1>
      <p className="mt-3 text-[15px] leading-relaxed text-[var(--text-muted)]">
        You are the administrator. Opening hours, consultation fees and staff invitations are
        the next things to set up.
      </p>

      <Link
        href="/dashboard"
        className="mt-8 inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2.5 text-[15px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
      >
        Go to the clinic
        <ArrowRight className="size-4" />
      </Link>
    </main>
  );
}
