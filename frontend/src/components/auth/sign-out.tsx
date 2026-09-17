"use client";

import { useQueryClient } from "@tanstack/react-query";
import { LogOut } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { signOut } from "@/lib/auth";

export function SignOutButton() {
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
      className="inline-flex shrink-0 items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-2 text-[14px] transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-50"
    >
      <LogOut className="size-4" />
      {busy ? "Signing out" : "Sign out"}
    </button>
  );
}
