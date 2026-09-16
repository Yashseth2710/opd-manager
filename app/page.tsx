"use client";

import { useQuery } from "@tanstack/react-query";
import { Activity, Database, RefreshCw, ServerCog } from "lucide-react";
import { ApiFailure, request } from "@/lib/api";

type Health = {
  status: string;
  environment: string;
  version: string;
  pooled: boolean;
  database: { reachable: boolean; server_version: string | null; latency_ms: number | null };
};

export default function Page() {
  const { data, isPending, isError, error, refetch, isFetching } = useQuery({
    queryKey: ["health"],
    queryFn: () => request<Health>("/health"),
  });

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col justify-center gap-8 px-4 py-16">
      <header className="flex items-center gap-3">
        <span className="grid size-10 place-items-center rounded-[10px] bg-[var(--accent)] font-mono text-lg font-bold text-[var(--accent-fg)]">
          O
        </span>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">OPD Manager</h1>
          <p className="text-sm text-[var(--text-muted)]">
            The modern operating system for outpatient clinics.
          </p>
        </div>
      </header>

      <section
        aria-live="polite"
        className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]"
      >
        <div className="flex items-center justify-between gap-4 border-b border-[var(--border)] px-5 py-4">
          <h2 className="text-base font-semibold">System status</h2>
          <button
            type="button"
            onClick={() => void refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3 py-1.5 text-sm transition hover:bg-[var(--surface-sunken)] disabled:opacity-45"
          >
            <RefreshCw className={`size-4 ${isFetching ? "animate-spin" : ""}`} />
            Check again
          </button>
        </div>

        {isPending && (
          <div className="space-y-3 px-5 py-5">
            {[0, 1, 2].map((row) => (
              <div
                key={row}
                className="h-11 animate-pulse rounded-[var(--radius-field)] bg-[var(--surface-sunken)]"
              />
            ))}
          </div>
        )}

        {isError && (
          <div className="px-5 py-8 text-center">
            <h3 className="font-semibold">The API is not answering</h3>
            <p className="mx-auto mt-1 max-w-sm text-sm text-[var(--text-muted)]">
              {error instanceof ApiFailure
                ? error.message
                : "Nothing responded on /api/v1. Start it with npm run api."}
            </p>
            <button
              type="button"
              onClick={() => void refetch()}
              className="mt-4 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-fg)] transition hover:brightness-110"
            >
              Try again
            </button>
          </div>
        )}

        {data && (
          <dl className="divide-y divide-[var(--border)]">
            <Row
              icon={<ServerCog className="size-4" />}
              label="API"
              value={data.status === "ok" ? "Responding" : data.status}
              detail={`${data.environment} · v${data.version}`}
              good={data.status === "ok"}
            />
            <Row
              icon={<Database className="size-4" />}
              label="Database"
              value={data.database.reachable ? "Connected" : "Unreachable"}
              detail={
                data.database.reachable
                  ? `Postgres ${data.database.server_version ?? "unknown"} · ${data.database.latency_ms ?? "?"} ms${data.pooled ? " · pooled" : ""}`
                  : "Check DATABASE_URL in .env"
              }
              good={data.database.reachable}
            />
            <Row
              icon={<Activity className="size-4" />}
              label="Migrations"
              value="Baseline applied"
              detail="Extensions in place, no tables yet"
              good={null}
            />
          </dl>
        )}
      </section>

      <p className="text-sm text-[var(--text-subtle)]">
        Nothing here is patient data. Everything in this build is synthetic.
      </p>
    </main>
  );
}

function Row({
  icon,
  label,
  value,
  detail,
  good,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  detail: string;
  good: boolean | null;
}) {
  const tone =
    good === null
      ? "text-[var(--text-muted)] bg-[var(--surface-sunken)]"
      : good
        ? "text-[var(--color-state-completed)] bg-[color-mix(in_srgb,var(--color-state-completed)_13%,transparent)]"
        : "text-[var(--color-state-noshow)] bg-[color-mix(in_srgb,var(--color-state-noshow)_12%,transparent)]";

  return (
    <div className="flex items-center gap-4 px-5 py-4">
      <span className="text-[var(--text-subtle)]">{icon}</span>
      <div className="min-w-0">
        <dt className="font-medium">{label}</dt>
        <dd className="truncate text-sm text-[var(--text-muted)]">{detail}</dd>
      </div>
      <span className={`ml-auto shrink-0 rounded-full px-2.5 py-1 text-xs font-medium ${tone}`}>
        {value}
      </span>
    </div>
  );
}
