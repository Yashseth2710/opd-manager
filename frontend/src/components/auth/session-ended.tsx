"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Ban } from "lucide-react";
import { useEffect, useState } from "react";
import { signOut } from "@/lib/auth";

/**
 * Shown when the app finds the session behind it is gone.
 *
 * It signs out on the way past rather than only offering a link. The marker
 * cookie that tells the router a session is probably live outlasts the
 * session itself — it is set for the refresh token's full week, while the
 * session behind it can end at any point inside that week. A stale marker
 * sends anyone opening the sign-in page back to the dashboard, which sends
 * them here, which is a loop with no way out of it by clicking. Clearing the
 * marker is what breaks it, and only the server can: the cookie is httpOnly.
 */
export function SessionEnded({ message, heading }: { message?: string; heading?: string }) {
  const queries = useQueryClient();
  const [cleared, setCleared] = useState(false);

  useEffect(() => {
    let current = true;
    void signOut()
      .catch(() => undefined)
      .finally(() => {
        if (!current) return;
        queries.clear();
        setCleared(true);
      });
    return () => {
      current = false;
    };
  }, [queries]);

  const link = cleared ? (
    <a href="/login?ended=1" className="underline underline-offset-2">
      Sign in again
    </a>
  ) : (
    <span>Signing you out…</span>
  );

  if (heading) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6 py-12">
        <div
          role="alert"
          className="w-full max-w-md rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--color-state-noshow)_35%,transparent)] bg-[var(--surface)] px-6 py-7"
        >
          <p className="flex items-center gap-2 text-[18px] font-semibold tracking-tight">
            <Ban className="size-5 shrink-0 text-[var(--color-state-noshow)]" />
            {heading}
          </p>
          <p className="mt-2 text-[15px] leading-relaxed text-[var(--text-muted)]">{message}</p>
          <p className="mt-5 text-[14px] font-medium">{link}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 text-center">
      <p className="text-[15px] leading-relaxed text-[var(--text-muted)]">
        {message ?? "Your session has ended."} {link}
      </p>
    </div>
  );
}
