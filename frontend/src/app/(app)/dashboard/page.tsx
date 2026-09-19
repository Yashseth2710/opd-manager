"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ArrowRight, Loader2 } from "lucide-react";
import Link from "next/link";
import { ClinicDay } from "@/components/dashboard/clinic-day";
import { DoctorDay } from "@/components/dashboard/doctor-day";
import { Skeleton } from "@/components/dashboard/parts";
import { longDate } from "@/lib/appointments";
import { currentSession } from "@/lib/auth";
import { getClinic } from "@/lib/clinic";
import { getToday, greeting, REFRESH_MS } from "@/lib/dashboard";

export default function DashboardPage() {
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const clinic = useQuery({ queryKey: ["clinic"], queryFn: getClinic, retry: false });
  const may = (permission: string) => session.data?.permissions.includes(permission) ?? false;
  const seesDay = may("appointment:read");

  const today = useQuery({
    queryKey: ["dashboard"],
    queryFn: getToday,
    enabled: seesDay,
    refetchInterval: REFRESH_MS,
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
  const clinicName = clinic.data?.name;
  const day = today.data ? longDate(today.data.date) : null;

  return (
    // Wider than the other pages, so the day's two columns have room.
    <div className="mx-auto w-full max-w-5xl px-6 py-10 lg:py-14">
      <header className="mb-8">
        <h1 className="text-[26px] leading-tight font-semibold tracking-tight text-balance">
          {greeting(new Date().getHours())}, {name}
        </h1>
        {(day || clinicName) && (
          <p className="mt-1.5 text-[15px] leading-relaxed text-[var(--text-muted)]">
            {today.data?.view === "doctor"
              ? `Your day for ${day}.`
              : day
                ? `${day}${clinicName ? ` at ${clinicName}` : ""}.`
                : clinicName}
          </p>
        )}
      </header>
      <div className="flex flex-col gap-6">
        {clinic.data?.status === "pending" && (
          <Link
            href="/settings"
            className="flex items-center justify-between gap-4 rounded-[var(--radius-panel)] border border-[var(--accent)] bg-[var(--accent-wash)] px-5 py-4 transition-colors hover:brightness-[0.98]"
          >
            <span>
              <span className="block text-[15px] font-medium">
                Finish setting up the clinic
              </span>
              <span className="mt-0.5 block text-[14px] text-[var(--text-muted)]">
                A contact number and address are still needed before you open.
              </span>
            </span>
            <ArrowRight className="size-4 shrink-0" />
          </Link>
        )}

        {!seesDay ? (
          <p className="text-[15px] leading-relaxed text-[var(--text-muted)]">
            Your role does not include the day&apos;s appointments or queue. An administrator
            can widen it under Staff.
          </p>
        ) : today.isPending ? (
          <Skeleton />
        ) : today.isError && !today.data ? (
          <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-10 text-center">
            <h2 className="text-[17px] font-semibold tracking-tight">The day did not load</h2>
            <p className="mx-auto mt-1.5 max-w-[46ch] text-[15px] text-[var(--text-muted)]">
              Something went wrong reaching the server. Try again in a moment.
            </p>
            <button
              type="button"
              onClick={() => void today.refetch()}
              className="mt-5 inline-flex rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06]"
            >
              Try again
            </button>
          </div>
        ) : today.data.view === "unlinked" ? (
          <div className="rounded-[var(--radius-panel)] border border-dashed border-[var(--border-strong)] px-6 py-10 text-center">
            <h2 className="text-[17px] font-semibold tracking-tight">
              Your account has no day to show yet
            </h2>
            <p className="mx-auto mt-1.5 max-w-[52ch] text-[15px] text-[var(--text-muted)]">
              It is not linked to a doctor profile. An administrator can link it from your
              profile under Doctors, and your patients will show here.
            </p>
          </div>
        ) : (
          <>
            {today.isError && (
              <p
                role="alert"
                className="flex items-center gap-2 text-[13px] text-[var(--color-state-noshow)]"
              >
                <AlertTriangle className="size-3.5" />
                Lost touch with the server. What is shown may be out of date.
              </p>
            )}
            {today.data.view === "doctor" ? (
              <DoctorDay today={today.data} mayBook={may("appointment:create")} />
            ) : (
              <ClinicDay today={today.data} mayBook={may("appointment:create")} />
            )}
          </>
        )}
      </div>
    </div>
  );
}
