"use client";

import { useQueryClient } from "@tanstack/react-query";
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
export function SessionEnded({ message }: { message?: string }) {
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

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 text-center">
      <p className="text-[15px] leading-relaxed text-[var(--text-muted)]">
        {message ?? "Your session has ended."}{" "}
        {cleared ? (
          <a href="/login?ended=1" className="underline underline-offset-2">
            Sign in again
          </a>
        ) : (
          <span>Signing you out…</span>
        )}
      </p>
    </div>
  );
}
