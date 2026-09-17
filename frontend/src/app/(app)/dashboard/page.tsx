"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { Page } from "@/components/layout/shell";
import { getClinic, money } from "@/lib/clinic";
import { getSettings } from "@/lib/clinic";
import { currentSession } from "@/lib/auth";

export default function DashboardPage() {
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const clinic = useQuery({ queryKey: ["clinic"], queryFn: getClinic, retry: false });
  const settings = useQuery({
    queryKey: ["clinic-settings"],
    queryFn: getSettings,
    retry: false,
  });

  if (session.isPending || clinic.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Loading…</span>
      </div>
    );
  }

  const name = session.data?.user.first_name ?? "there";

  return (
    <Page title={`Good day, ${name}`} blurb="Nothing here is real patient data.">
      {clinic.data?.status === "pending" && (
        <Link
          href="/settings"
          className="mb-8 flex items-center justify-between gap-4 rounded-[var(--radius-panel)] border border-[var(--accent)] bg-[var(--accent-wash)] px-5 py-4 transition-colors hover:brightness-[0.98]"
        >
          <span>
            <span className="block text-[15px] font-medium">Finish setting up the clinic</span>
            <span className="mt-0.5 block text-[14px] text-[var(--text-muted)]">
              A contact number and address are still needed before you open.
            </span>
          </span>
          <ArrowRight className="size-4 shrink-0" />
        </Link>
      )}

      <dl className="grid gap-px overflow-hidden rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--border)] sm:grid-cols-3">
        <Cell label="Your role" value={(session.data?.role ?? "").replace("-", " ")} />
        <Cell
          label="Consultation fee"
          value={
            settings.data && clinic.data
              ? money(settings.data.consultation_fee, clinic.data.currency)
              : "—"
          }
        />
        <Cell
          label="Appointment length"
          value={settings.data ? `${settings.data.consultation_duration_minutes} minutes` : "—"}
        />
      </dl>

      <p className="mt-10 text-[15px] leading-relaxed text-[var(--text-muted)]">
        Patients, appointments and the queue arrive next.
      </p>
    </Page>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-[var(--surface)] px-5 py-4">
      <dt className="text-[13px] text-[var(--text-subtle)]">{label}</dt>
      <dd className="mt-1 text-[15px] font-medium capitalize">{value}</dd>
    </div>
  );
}
