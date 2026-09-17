"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { signOut } from "@/lib/auth";

export function SignOutButton({
  subdued,
  compact,
}: {
  subdued?: boolean;
  compact?: boolean;
} = {}) {
  const router = useRouter();
  const queries = useQueryClient();
  const [busy, setBusy] = useState(false);

  async function leave() {
    if (busy) return;
    setBusy(true);
    try {
      await signOut();
    } finally {
      // Whatever the server said, this browser is done with the session.
      queries.clear();
      router.replace("/login");
    }
  }

  return (
    <button
      type="button"
      onClick={leave}
      disabled={busy}
      className={`inline-flex shrink-0 items-center gap-2 ${compact ? "w-auto" : "w-full"} rounded-[var(--radius-field)] px-2.5 py-2 text-[14px] transition-colors disabled:opacity-50 ${
        subdued
          ? "text-[var(--rail-text)] hover:bg-white/8 hover:text-white"
          : "w-auto border border-[var(--border-strong)] px-3 hover:bg-[var(--surface-sunken)]"
      }`}
    >
      <LogOut className="size-4" />
      <span className={compact ? "sr-only" : undefined}>
        {busy ? "Signing out" : "Sign out"}
      </span>
    </button>
  );
}
