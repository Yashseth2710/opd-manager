"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  CalendarDays,
  ChartColumn,
  FlaskConical,
  LayoutDashboard,
  ListOrdered,
  Loader2,
  NotebookPen,
  ReceiptIndianRupee,
  ScrollText,
  Settings,
  Stethoscope,
  UserRound,
  Users,
} from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { SessionEnded } from "@/components/auth/session-ended";
import { SignOutButton } from "@/components/auth/sign-out";
import { Bell } from "@/components/notifications/bell";
import { ThemeMenu } from "@/components/layout/theme-switch";
import { FinderProvider, SearchTrigger } from "@/components/search/finder";
import { ApiFailure } from "@/lib/api";
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
  { href: "/patients", label: "Patients", icon: UserRound, permission: "patient:read" },
  { href: "/doctors", label: "Doctors", icon: Stethoscope, permission: "doctor:read" },
  {
    href: "/appointments",
    label: "Appointments",
    icon: CalendarDays,
    permission: "appointment:read",
  },
  { href: "/queue", label: "Queue", icon: ListOrdered, permission: "appointment:read" },
  {
    href: "/consultations",
    label: "Notes",
    icon: NotebookPen,
    permission: "consultation:read",
  },
  { href: "/lab", label: "Lab", icon: FlaskConical, permission: "lab:read" },
  { href: "/billing", label: "Billing", icon: ReceiptIndianRupee, permission: "billing:read" },
  { href: "/reports", label: "Reports", icon: ChartColumn, permission: "reports:read" },
  { href: "/staff", label: "Staff", icon: Users, permission: "staff:manage" },
  { href: "/audit", label: "Audit log", icon: ScrollText, permission: "audit:read" },
  { href: "/settings", label: "Settings", icon: Settings, permission: "settings:manage" },
];

const SUSPENDED =
  "Nobody at the clinic can use OPD Manager until it is restored. Everything the clinic has recorded is kept exactly as it was. Its administrator can ask for it to be restored.";

function suspendedBy(error: unknown) {
  return error instanceof ApiFailure && error.code === "CLINIC_SUSPENDED";
}

/**
 * Whether anything this page asked for was refused because the clinic was
 * suspended. The API says so on the next request after it happens, from
 * whichever screen someone is on, and every screen should stop the same way.
 */
function useSuspension(): boolean {
  const queries = useQueryClient();
  const [suspended, setSuspended] = useState(false);
  useEffect(() => {
    const heard = queries.getQueryCache().subscribe((event) => {
      if (event.type === "updated" && event.action.type === "error") {
        if (suspendedBy(event.action.error)) setSuspended(true);
      }
    });
    const tried = queries.getMutationCache().subscribe((event) => {
      if (event.type === "updated" && event.action.type === "error") {
        if (suspendedBy(event.action.error)) setSuspended(true);
      }
    });
    return () => {
      heard();
      tried();
    };
  }, [queries]);
  return suspended;
}

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const suspended = useSuspension();
  const { data, isPending, isError, error } = useQuery({
    queryKey: ["session"],
    queryFn: currentSession,
    retry: false,
  });
  const platform = Boolean(data && !data.organization);

  // A platform account has no clinic to show. Its own pages live elsewhere.
  useEffect(() => {
    if (platform) router.replace("/admin" as Route);
  }, [platform, router]);

  if (suspended || suspendedBy(error)) {
    return <SessionEnded heading="This clinic has been suspended" message={SUSPENDED} />;
  }

  if (isPending || platform) {
    return (
      <div className="flex min-h-screen items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Loading your clinic…</span>
      </div>
    );
  }

  if (isError || !data) {
    return <SessionEnded />;
  }

  const allowed = DESTINATIONS.filter(
    (item) => !item.permission || data.permissions.includes(item.permission),
  );

  const pages = [
    ...allowed.flatMap((item) => (item.href ? [{ label: item.label, href: item.href }] : [])),
    { label: "Notifications", href: "/notifications" },
  ];

  return (
    <FinderProvider session={data} pages={pages}>
      <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
        <nav className="flex flex-col gap-1 bg-[var(--rail)] px-3 py-4 text-[var(--rail-text)] lg:min-h-screen lg:px-4 lg:py-6">
          <div className="flex min-w-0 items-center justify-between gap-2">
            <ClinicMark session={data} />
            <div className="flex shrink-0 items-center gap-1">
              {data.organization && (
                <div className="lg:hidden">
                  <SearchTrigger compact />
                </div>
              )}
              {data.organization && <Bell />}
              <div className="lg:hidden">
                <ThemeMenu />
              </div>
              {/* The rail's footer is desktop only, so a phone needs its own. */}
              <div className="lg:hidden">
                <SignOutButton subdued compact />
              </div>
            </div>
          </div>

          {data.organization && (
            <div className="mt-5 hidden items-center gap-1 lg:flex">
              <div className="min-w-0 flex-1">
                <SearchTrigger />
              </div>
              <ThemeMenu />
            </div>
          )}

          <ul className="mt-6 flex gap-1 overflow-x-auto lg:mt-4 lg:flex-col lg:overflow-visible">
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
    </FinderProvider>
  );
}

function ClinicMark({ session }: { session: Session }) {
  return (
    <div className="flex min-w-0 items-center gap-2.5 px-2.5">
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
  back,
  wide,
  children,
}: {
  title: string;
  blurb?: string;
  action?: React.ReactNode;
  /** Sits above the heading, where somebody looks for the way out. */
  back?: { href: Route; label: string };
  /** For a table that needs the room more than the eye needs a short line. */
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={`mx-auto w-full ${wide ? "max-w-6xl" : "max-w-4xl"} px-6 py-10 lg:py-14`}>
      {back && (
        <Link
          href={back.href}
          className="mb-6 inline-flex items-center gap-1.5 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
        >
          <ArrowLeft className="size-3.5" />
          {back.label}
        </Link>
      )}
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
