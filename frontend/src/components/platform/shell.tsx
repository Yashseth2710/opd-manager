"use client";

import { useQuery } from "@tanstack/react-query";
import { Building2, Gauge, Layers, Loader2, ShieldCheck } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { SessionEnded } from "@/components/auth/session-ended";
import { SignOutButton } from "@/components/auth/sign-out";
import { Mark } from "@/components/brand/mark";
import { ThemeMenu } from "@/components/layout/theme-switch";
import { currentSession } from "@/lib/auth";

const PLACES: { href: Route; label: string; icon: typeof Gauge; exact?: boolean }[] = [
  { href: "/admin" as Route, label: "Overview", icon: Gauge, exact: true },
  { href: "/admin/clinics" as Route, label: "Clinics", icon: Building2 },
  { href: "/admin/plans" as Route, label: "Plans", icon: Layers },
];

/**
 * The frame around the platform's pages. It looks like the clinic's rail on
 * purpose, so the same person moving between the two is never lost, and says
 * "Platform" under the name so they always know which side they are on.
 */
export function PlatformShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { data, isPending, isError } = useQuery({
    queryKey: ["session"],
    queryFn: currentSession,
    retry: false,
  });
  const clinicAccount = Boolean(data?.organization);

  // Somebody from a clinic has nothing here. The API refuses them anyway;
  // this only saves them a page of errors.
  useEffect(() => {
    if (clinicAccount) router.replace("/dashboard");
  }, [clinicAccount, router]);

  if (isError) return <SessionEnded />;

  if (isPending || !data || clinicAccount) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Opening the platform…</span>
      </div>
    );
  }

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <nav className="flex flex-col gap-1 bg-[var(--rail)] px-3 py-4 text-[var(--rail-text)] lg:min-h-screen lg:px-4 lg:py-6">
        <div className="flex min-w-0 items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2.5 px-2.5">
            <Mark className="size-8 shrink-0" />
            <span className="min-w-0">
              <span className="block truncate text-[14px] leading-tight font-semibold text-white">
                OPD Manager
              </span>
              <span className="flex items-center gap-1 text-[12px] leading-tight text-[var(--accent)]">
                <ShieldCheck className="size-3" />
                Platform
              </span>
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <ThemeMenu />
            <div className="lg:hidden">
              <SignOutButton subdued compact />
            </div>
          </div>
        </div>

        <ul className="mt-6 flex gap-1 overflow-x-auto lg:mt-8 lg:flex-col lg:overflow-visible">
          {PLACES.map(({ href, label, icon: Icon, exact }) => {
            const active = exact ? pathname === href : pathname.startsWith(href);
            return (
              <li key={href}>
                <Link
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`flex items-center gap-2.5 rounded-[var(--radius-field)] px-2.5 py-2 text-[14px] whitespace-nowrap transition-colors ${
                    active
                      ? "bg-[var(--accent)] font-medium text-[var(--color-ink-900)]"
                      : "hover:bg-white/8 hover:text-white"
                  }`}
                >
                  <Icon className="size-4 shrink-0" />
                  {label}
                </Link>
              </li>
            );
          })}
        </ul>

        <div className="mt-auto hidden pt-6 lg:block">
          <p className="mb-4 px-2.5 text-[12px] leading-relaxed text-[var(--color-ink-300)]">
            Clinics, plans and counts. Patient records are never shown here.
          </p>
          <p className="mb-3 px-2.5 text-[13px] leading-snug">
            {data.user.first_name} {data.user.last_name}
            <span className="mt-0.5 block text-[12px] text-[var(--color-ink-300)]">
              Platform administrator
            </span>
          </p>
          <SignOutButton subdued />
        </div>
      </nav>

      <main className="min-w-0">{children}</main>
    </div>
  );
}
