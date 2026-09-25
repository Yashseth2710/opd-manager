"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, Layers, Loader2, Mail, RotateCcw, ShieldCheck } from "lucide-react";
import type { Route } from "next";
import { useParams } from "next/navigation";
import { useState } from "react";
import { Page } from "@/components/layout/shell";
import {
  Empty,
  Failed,
  Loading,
  Meter,
  StatusBadge,
  shortDate,
} from "@/components/platform/parts";
import { ApiFailure } from "@/lib/api";
import { sinceThen } from "@/lib/notifications";
import {
  choosePlan,
  describeStanding,
  getClinic,
  listPlans,
  MEASURES,
  reactivateClinic,
  suspendClinic,
  type ClinicDetail,
  type PlatformEvent,
} from "@/lib/platform";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const BACK = { href: "/admin/clinics" as Route, label: "All clinics" };
const QUIET =
  "inline-flex items-center justify-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] font-medium transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-50";
const PANEL = "rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)]";

function problem(error: unknown): string {
  return error instanceof ApiFailure ? error.message : "That did not go through. Try again.";
}

export default function ClinicPage() {
  const { id } = useParams<{ id: string }>();
  const valid = UUID.test(id);
  const clinic = useQuery({
    queryKey: ["platform", "clinic", id],
    queryFn: () => getClinic(id),
    enabled: valid,
    retry: (count, error) =>
      !(error instanceof ApiFailure && error.status === 404) && count < 1,
  });

  const missing = !valid || (clinic.error instanceof ApiFailure && clinic.error.status === 404);

  if (missing) {
    return (
      <Page title="Clinic not found" back={BACK}>
        <Empty
          heading="There is no clinic at this address"
          body="It may have been typed wrongly, or the clinic no longer exists."
          action={{ label: "See every clinic", href: BACK.href }}
        />
      </Page>
    );
  }

  if (clinic.isPending) {
    return (
      <Page title="Clinic" back={BACK}>
        <Loading what="Opening the clinic…" />
      </Page>
    );
  }

  if (clinic.isError) {
    return (
      <Page title="Clinic" back={BACK}>
        <Failed what="This clinic" retry={() => void clinic.refetch()} />
      </Page>
    );
  }

  return <Clinic clinic={clinic.data} />;
}

function Clinic({ clinic }: { clinic: ClinicDetail }) {
  const queries = useQueryClient();
  const settled = (updated: ClinicDetail) => {
    queries.setQueryData(["platform", "clinic", clinic.id], updated);
    void queries.invalidateQueries({ queryKey: ["platform", "clinics"] });
    void queries.invalidateQueries({ queryKey: ["platform", "metrics"] });
    void queries.invalidateQueries({ queryKey: ["platform", "plans"] });
  };

  const lastSuspension = clinic.history.find((event) => event.action === "platform.suspended");

  return (
    <Page
      title={clinic.name}
      blurb={`${clinic.slug}, joined ${shortDate(clinic.created_at)}`}
      back={BACK}
      action={<StatusBadge status={clinic.status} />}
      wide
    >
      {clinic.status === "suspended" && (
        <Suspended clinic={clinic} event={lastSuspension} onDone={settled} />
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <div className="flex flex-col gap-6">
          <section aria-labelledby="usage" className={`${PANEL} px-5 py-5`}>
            <h2 id="usage" className="text-[16px] font-semibold tracking-tight">
              What it uses
            </h2>
            <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
              Against what {clinic.standing.plan_name} allows. Counts only.
            </p>
            <div className="mt-5 flex flex-col gap-4">
              {MEASURES.map((measure) => (
                <Meter
                  key={measure.key}
                  label={measure.label}
                  used={clinic.usage[measure.key].used}
                  limit={clinic.usage[measure.key].limit}
                  unit={measure.unit}
                />
              ))}
            </div>
          </section>

          <PlanPanel clinic={clinic} onDone={settled} />
        </div>

        <div className="flex flex-col gap-6">
          <Contact clinic={clinic} />
          {clinic.status !== "suspended" && <Suspend clinic={clinic} onDone={settled} />}
          <History events={clinic.history} />
        </div>
      </div>
    </Page>
  );
}

function Suspended({
  clinic,
  event,
  onDone,
}: {
  clinic: ClinicDetail;
  event?: PlatformEvent;
  onDone: (updated: ClinicDetail) => void;
}) {
  const [asking, setAsking] = useState(false);
  const restore = useMutation({
    mutationFn: () => reactivateClinic(clinic.id),
    onSuccess: (updated) => {
      setAsking(false);
      onDone(updated);
    },
  });
  const reason = typeof event?.changes?.reason === "string" ? event.changes.reason : null;

  return (
    <div
      role="status"
      className="mb-6 rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--color-state-noshow)_40%,transparent)] bg-[color-mix(in_srgb,var(--color-state-noshow)_7%,transparent)] px-5 py-4"
    >
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-[60ch]">
          <p className="flex items-center gap-2 text-[15px] font-semibold text-[var(--color-state-noshow)]">
            <Ban className="size-4 shrink-0" />
            Suspended{event ? ` ${sinceThen(event.created_at)}` : ""}
          </p>
          <p className="mt-1 text-[14px] leading-relaxed">
            {reason ? <>“{reason}”</> : "No reason was recorded."}
            {event && <span className="text-[var(--text-muted)]"> by {event.actor_name}</span>}
          </p>
          <p className="mt-1 text-[13px] text-[var(--text-muted)]">
            Nobody at the clinic can sign in, and its payment links take no money. Everything it
            recorded is kept.
          </p>
        </div>
        {!asking && (
          <button type="button" onClick={() => setAsking(true)} className={QUIET}>
            <RotateCcw className="size-4" />
            Reactivate
          </button>
        )}
      </div>

      {asking && (
        <div className="mt-4 border-t border-[color-mix(in_srgb,var(--color-state-noshow)_25%,transparent)] pt-4">
          <p className="text-[14px] font-medium">
            Let {clinic.name} back in? Its people can sign in again straight away
            {clinic.set_up ? "." : ", and carry on setting up."}
          </p>
          {restore.error && (
            <p role="alert" className="mt-2 text-[14px] text-[var(--color-state-noshow)]">
              {problem(restore.error)}
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              autoFocus
              disabled={restore.isPending}
              onClick={() => restore.mutate()}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-3.5 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06] disabled:opacity-60"
            >
              {restore.isPending && <Loader2 className="size-4 animate-spin" />}
              Yes, reactivate
            </button>
            <button
              type="button"
              disabled={restore.isPending}
              onClick={() => {
                restore.reset();
                setAsking(false);
              }}
              className={QUIET}
            >
              Leave it suspended
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function PlanPanel({
  clinic,
  onDone,
}: {
  clinic: ClinicDetail;
  onDone: (updated: ClinicDetail) => void;
}) {
  const plans = useQuery({ queryKey: ["platform", "plans"], queryFn: listPlans });
  const [picked, setPicked] = useState("");
  const [asking, setAsking] = useState(false);
  const move = useMutation({
    mutationFn: (planId: string) => choosePlan(clinic.id, planId),
    onSuccess: (updated) => {
      setAsking(false);
      setPicked("");
      onDone(updated);
    },
  });
  const target = plans.data?.find((plan) => plan.id === picked);
  const over = target
    ? MEASURES.filter((measure) => {
        const cap = target.limits[measure.limit];
        return cap !== null && clinic.usage[measure.key].used > cap;
      })
    : [];

  return (
    <section aria-labelledby="plan" className={`${PANEL} px-5 py-5`}>
      <h2
        id="plan"
        className="flex items-center gap-2 text-[16px] font-semibold tracking-tight"
      >
        <Layers className="size-4 text-[var(--text-muted)]" />
        Plan
      </h2>
      <p className="mt-1 text-[14px]">{describeStanding(clinic.standing)}</p>
      {clinic.standing.on_trial && (
        <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
          When the trial ends it drops to the free plan, unless a plan is chosen here first.
        </p>
      )}

      <div className="mt-4 flex flex-col gap-2 sm:flex-row">
        <label htmlFor="move-to" className="sr-only">
          Move to plan
        </label>
        <select
          id="move-to"
          value={picked}
          disabled={plans.isPending || move.isPending}
          onChange={(event) => {
            setPicked(event.target.value);
            setAsking(false);
            move.reset();
          }}
          className="min-w-0 flex-1 rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[14px]"
        >
          <option value="">{plans.isError ? "Plans did not load" : "Choose a plan…"}</option>
          {plans.data?.map((plan) => (
            <option key={plan.id} value={plan.id}>
              {plan.name}
              {plan.id === clinic.standing.plan_id ? " (current)" : ""}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={!picked || asking}
          onClick={() => setAsking(true)}
          className={QUIET}
        >
          Move to this plan
        </button>
      </div>

      {asking && target && (
        <div role="alert" className="mt-4 border-t border-[var(--border)] pt-4 text-[14px]">
          <p className="font-medium">
            Put {clinic.name} on {target.name}
            {clinic.standing.on_trial ? " and end its trial" : ""}?
          </p>
          {over.length > 0 && (
            <p className="mt-1 text-[var(--text-muted)]">
              It already has more than {target.name} allows for{" "}
              {over.map((measure) => measure.label.toLowerCase()).join(" and ")}. Nothing is
              taken away, but it cannot add more of those until it fits.
            </p>
          )}
          {move.error && (
            <p className="mt-2 text-[var(--color-state-noshow)]">{problem(move.error)}</p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              autoFocus
              disabled={move.isPending}
              onClick={() => move.mutate(target.id)}
              className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-3.5 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06] disabled:opacity-60"
            >
              {move.isPending && <Loader2 className="size-4 animate-spin" />}
              Yes, move it
            </button>
            <button
              type="button"
              disabled={move.isPending}
              onClick={() => {
                setAsking(false);
                move.reset();
              }}
              className={QUIET}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}

function Contact({ clinic }: { clinic: ClinicDetail }) {
  const rows: [string, React.ReactNode][] = [
    [
      "Run by",
      clinic.owner ? (
        <>
          {clinic.owner.name}
          <a
            href={`mailto:${clinic.owner.email}`}
            title={clinic.owner.email}
            className="mt-0.5 flex min-w-0 items-center gap-1.5 text-[var(--text-muted)] underline-offset-2 hover:text-[var(--text)] hover:underline"
          >
            <Mail className="size-3.5 shrink-0" />
            <span className="truncate">{clinic.owner.email}</span>
          </a>
        </>
      ) : (
        "Nobody holds the administrator role"
      ),
    ],
    ["Clinic phone", clinic.phone || "Not given"],
    ["Clinic email", clinic.email || "Not given"],
    ["City", clinic.city || "Not given"],
    ["Time zone", clinic.timezone],
    ["Setup", clinic.set_up ? "Finished" : "Not finished yet"],
    ["Last sign-in", clinic.last_active_at ? sinceThen(clinic.last_active_at) : "Nobody yet"],
  ];
  return (
    <section aria-labelledby="contact" className={`${PANEL} px-5 py-5`}>
      <h2 id="contact" className="text-[16px] font-semibold tracking-tight">
        The clinic
      </h2>
      <dl className="mt-3 flex flex-col gap-2.5 text-[14px]">
        {rows.map(([label, value]) => (
          <div key={label} className="grid grid-cols-[7.5rem_minmax(0,1fr)] gap-3">
            <dt className="text-[var(--text-muted)]">{label}</dt>
            <dd className="min-w-0 break-words">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-4 flex items-start gap-2 border-t border-[var(--border)] pt-3 text-[12px] leading-relaxed text-[var(--text-subtle)]">
        <ShieldCheck className="mt-0.5 size-3.5 shrink-0" />
        Patients, notes, prescriptions, bills and files stay with the clinic and cannot be
        opened from the platform.
      </p>
    </section>
  );
}

const SHORTEST = 3;
const LONGEST = 300;

function Suspend({
  clinic,
  onDone,
}: {
  clinic: ClinicDetail;
  onDone: (updated: ClinicDetail) => void;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [tried, setTried] = useState(false);
  const stop = useMutation({
    mutationFn: () => suspendClinic(clinic.id, reason.trim()),
    onSuccess: (updated) => {
      setOpen(false);
      setReason("");
      setTried(false);
      onDone(updated);
    },
  });
  const said = reason.trim().replace(/\s+/g, " ");
  const tooShort = said.length < SHORTEST;

  if (!open) {
    return (
      <section className={`${PANEL} px-5 py-5`}>
        <h2 className="text-[16px] font-semibold tracking-tight">Suspend</h2>
        <p className="mt-1 text-[14px] leading-relaxed text-[var(--text-muted)]">
          Stops everyone at the clinic at once. Nothing they recorded is touched, and it can be
          undone.
        </p>
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="mt-4 inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[color-mix(in_srgb,var(--color-state-noshow)_45%,transparent)] px-3.5 py-2 text-[14px] font-medium text-[var(--color-state-noshow)] transition-colors hover:bg-[color-mix(in_srgb,var(--color-state-noshow)_8%,transparent)]"
        >
          <Ban className="size-4" />
          Suspend this clinic
        </button>
      </section>
    );
  }

  return (
    <section
      aria-labelledby="suspend"
      className="rounded-[var(--radius-panel)] border border-[color-mix(in_srgb,var(--color-state-noshow)_45%,transparent)] bg-[var(--surface)] px-5 py-5"
    >
      <h2 id="suspend" className="text-[16px] font-semibold tracking-tight">
        Suspend {clinic.name}?
      </h2>
      <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-[14px] leading-relaxed text-[var(--text-muted)]">
        <li>Everyone there is signed out now and cannot sign back in.</li>
        <li>Links sent to patients stop taking money.</li>
        <li>The clinic sees your name and the reason in its own audit log.</li>
      </ul>
      <form
        noValidate
        className="mt-4 flex flex-col gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          setTried(true);
          if (tooShort || stop.isPending) return;
          stop.mutate();
        }}
      >
        <div>
          <label htmlFor="reason" className="text-[14px] font-medium">
            Why
          </label>
          <textarea
            id="reason"
            value={reason}
            autoFocus
            rows={3}
            maxLength={LONGEST}
            aria-invalid={tried && tooShort}
            aria-describedby="reason-help"
            onChange={(event) => setReason(event.target.value)}
            placeholder="Unpaid since July, three reminders sent"
            className="mt-1.5 w-full resize-y rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[14px] placeholder:text-[var(--text-subtle)] aria-invalid:border-[var(--color-state-noshow)]"
          />
          <p
            id="reason-help"
            className={`mt-1 flex justify-between gap-3 text-[12px] ${
              tried && tooShort
                ? "text-[var(--color-state-noshow)]"
                : "text-[var(--text-subtle)]"
            }`}
          >
            <span>
              {tried && tooShort ? "Say why, in a few words." : "The clinic will read this."}
            </span>
            <span className="tabular">
              {reason.length}/{LONGEST}
            </span>
          </p>
        </div>
        {stop.error && (
          <p role="alert" className="text-[14px] text-[var(--color-state-noshow)]">
            {problem(stop.error)}
          </p>
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            disabled={stop.isPending}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--color-state-noshow)] px-3.5 py-2 text-[14px] font-semibold text-white transition hover:brightness-110 disabled:opacity-60"
          >
            {stop.isPending && <Loader2 className="size-4 animate-spin" />}
            Suspend now
          </button>
          <button
            type="button"
            disabled={stop.isPending}
            onClick={() => {
              setOpen(false);
              setTried(false);
              stop.reset();
            }}
            className={QUIET}
          >
            Keep it running
          </button>
        </div>
      </form>
    </section>
  );
}

function History({ events }: { events: PlatformEvent[] }) {
  return (
    <section aria-labelledby="history" className={`${PANEL} px-5 py-5`}>
      <h2 id="history" className="text-[16px] font-semibold tracking-tight">
        What the platform has done here
      </h2>
      {events.length === 0 ? (
        <p className="mt-2 text-[14px] text-[var(--text-muted)]">
          Nothing yet. Suspensions and plan changes are listed here, and in the clinic&apos;s
          own audit log.
        </p>
      ) : (
        <ol className="mt-3 flex flex-col">
          {events.map((event) => (
            <li
              key={event.id}
              className="relative border-l border-[var(--border-strong)] pb-4 pl-4 last:pb-0"
            >
              <span
                aria-hidden
                className="absolute top-1.5 -left-[4.5px] size-2 rounded-full"
                style={{ backgroundColor: tone(event) }}
              />
              <p className="text-[14px] font-medium">{describe(event)}</p>
              <p className="text-[13px] text-[var(--text-muted)]">
                {event.actor_name.replace(/ \(platform\)$/, "")}, {sinceThen(event.created_at)}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}

function tone(event: PlatformEvent): string {
  if (event.action === "platform.suspended") return "var(--color-state-noshow)";
  if (event.action === "platform.reactivated") return "var(--color-state-completed)";
  return "var(--color-state-confirmed)";
}

function describe(event: PlatformEvent): string {
  const changes = event.changes ?? {};
  if (event.action === "platform.suspended") {
    return typeof changes.reason === "string" ? `Suspended: “${changes.reason}”` : "Suspended";
  }
  if (event.action === "platform.reactivated") return "Reactivated";
  const plan = Array.isArray(changes.plan) ? changes.plan : [];
  return plan.length === 2 ? `Moved from ${plan[0]} to ${plan[1]}` : "Plan changed";
}
