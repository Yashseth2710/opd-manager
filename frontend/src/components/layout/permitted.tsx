"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, Lock } from "lucide-react";
import Link from "next/link";
import { SessionEnded } from "@/components/auth/session-ended";
import { currentSession } from "@/lib/auth";

/**
 * Keeps a screen out of the hands of a role that cannot use it.
 *
 * Hiding the link in the rail is not enough: the address can be typed, and a
 * form somebody can fill in but never save is worse than a plain refusal.
 * The API refuses the write regardless; this is so nobody gets that far.
 */
export function Permitted({
  permission,
  children,
}: {
  permission: string;
  children: React.ReactNode;
}) {
  const { data, isPending, isError } = useQuery({
    queryKey: ["session"],
    queryFn: currentSession,
    retry: false,
  });

  if (isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Loading…</span>
      </div>
    );
  }

  if (isError || !data) {
    return <SessionEnded />;
  }

  if (!data.permissions.includes(permission)) {
    return (
      <div className="mx-auto flex min-h-[60vh] max-w-md flex-col items-center justify-center px-6 text-center">
        <span className="mb-4 grid size-11 place-items-center rounded-full bg-[var(--surface-sunken)]">
          <Lock className="size-5 text-[var(--text-subtle)]" />
        </span>
        <h1 className="text-[20px] font-semibold tracking-tight">
          Your role does not cover this
        </h1>
        <p className="mt-2 text-[15px] leading-relaxed text-[var(--text-muted)]">
          An administrator at your clinic decides what each role can see and do, and can change
          it.
        </p>
        <Link
          href="/dashboard"
          className="mt-6 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-4 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)]"
        >
          Back to today
        </Link>
      </div>
    );
  }

  return <>{children}</>;
}
