"use client";

import { useQuery } from "@tanstack/react-query";
import {
  CalendarDays,
  LayoutDashboard,
  ListOrdered,
  Loader2,
  Settings,
  UserRound,
  Users,
} from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { SignOutButton } from "@/components/auth/sign-out";
import { currentSession, type Session } from "@/lib/auth";

/**
 * A place to go, or a place there will be one. Anything not built yet has no
 * href at all: the router would not accept a route that does not exist, and
 * a link that goes nowhere is worse than a label that admits it.
 */
type Destination = {
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  href?: Route;
  /** Hidden from anyone whose role does not carry this. */
  permission?: string;
};

const DESTINATIONS: Destination[] = [
  { href: "/dashboard", label: "Today", icon: LayoutDashboard },
  { label: "Patients", icon: UserRound, permission: "patient:read" },
  { label: "Appointments", icon: CalendarDays, permission: "appointment:read" },
  { label: "Queue", icon: ListOrdered, permission: "queue:checkin" },
  { href: "/staff", label: "Staff", icon: Users, permission: "staff:manage" },
  { href: "/settings", label: "Settings", icon: Settings, permission: "settings:manage" },
];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
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
      <div className="flex min-h-screen items-center justify-center px-6 text-center">
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

  const allowed = DESTINATIONS.filter(
    (item) => !item.permission || data.permissions.includes(item.permission),
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <nav className="flex flex-col gap-1 bg-[var(--rail)] px-3 py-4 text-[var(--rail-text)] lg:min-h-screen lg:px-4 lg:py-6">
        <div className="flex items-center justify-between gap-3">
          <ClinicMark session={data} />
          {/* The rail's footer is desktop only, so a phone needs its own. */}
          <div className="lg:hidden">
            <SignOutButton subdued compact />
          </div>
        </div>

        <ul className="mt-6 flex gap-1 overflow-x-auto lg:flex-col lg:overflow-visible">
          {allowed.map((item) => (
            <li key={item.label}>
              <RailLink
                item={item}
                active={Boolean(item.href) && pathname.startsWith(item.href!)}
              />
            </li>
          ))}
        </ul>

        <div className="mt-auto hidden pt-6 lg:block">
          <p className="mb-3 px-2.5 text-[13px] leading-snug">
            {data.user.first_name} {data.user.last_name}
            <span className="mt-0.5 block text-[12px] text-[var(--color-ink-300)] capitalize">
              {data.role.replace("-", " ")}
            </span>
          </p>
          <SignOutButton subdued />
        </div>
      </nav>

      <main className="min-w-0">{children}</main>
    </div>
  );
}

function ClinicMark({ session }: { session: Session }) {
  return (
    <div className="flex items-center gap-2.5 px-2.5">
      <span className="grid size-8 shrink-0 place-items-center rounded-[7px] bg-[var(--accent)] text-[15px] leading-none font-bold text-[var(--color-ink-900)]">
        {session.organization?.name.trim().charAt(0).toUpperCase() ?? "O"}
      </span>
      <span className="min-w-0 truncate text-[14px] font-semibold text-white">
        {session.organization?.name ?? "OPD Manager"}
      </span>
    </div>
  );
}

function RailLink({ item, active }: { item: Destination; active: boolean }) {
  const Icon = item.icon;
  const shared =
    "flex items-center gap-2.5 rounded-[var(--radius-field)] px-2.5 py-2 text-[14px] whitespace-nowrap transition-colors";

  if (!item.href) {
    return (
      <span
        aria-disabled
        title="Not built yet"
        className={`${shared} cursor-default text-[var(--color-ink-400)]`}
      >
        <Icon className="size-4 shrink-0" />
        {item.label}
      </span>
    );
  }

  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`${shared} ${
        active
          ? "bg-[var(--accent)] font-medium text-[var(--color-ink-900)]"
          : "hover:bg-white/8 hover:text-white"
      }`}
    >
      <Icon className="size-4 shrink-0" />
      {item.label}
    </Link>
  );
}

export function Page({
  title,
  blurb,
  action,
  children,
}: {
  title: string;
  blurb?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-10 lg:py-14">
      <header className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[26px] leading-tight font-semibold tracking-tight text-balance">
            {title}
          </h1>
          {blurb && (
            <p className="mt-1.5 max-w-[60ch] text-[15px] leading-relaxed text-[var(--text-muted)]">
              {blurb}
            </p>
          )}
        </div>
        {action}
      </header>
      {children}
    </div>
  );
}
