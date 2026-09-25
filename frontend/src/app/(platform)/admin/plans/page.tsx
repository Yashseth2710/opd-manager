"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Pencil } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useState } from "react";
import { Page } from "@/components/layout/shell";
import { Empty, Failed, Loading } from "@/components/platform/parts";
import { ApiFailure } from "@/lib/api";
import { money } from "@/lib/clinic";
import { listPlans, MEASURES, savePlan, whole, type Limits, type Plan } from "@/lib/platform";

const INPUT =
  "w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2 text-[14px] placeholder:text-[var(--text-subtle)] aria-invalid:border-[var(--color-state-noshow)]";
const QUIET =
  "inline-flex items-center gap-2 rounded-[var(--radius-field)] border border-[var(--border-strong)] px-3.5 py-2 text-[14px] font-medium transition-colors hover:bg-[var(--surface-sunken)] disabled:opacity-50";

export default function PlansPage() {
  const plans = useQuery({ queryKey: ["platform", "plans"], queryFn: listPlans });

  return (
    <Page
      title="Plans"
      blurb="What each plan lets a clinic have. A change here reaches every clinic on the plan at once. Prices are shown to clinics, never charged."
      wide
    >
      {plans.isPending ? (
        <Loading what="Reading the plans…" />
      ) : plans.isError ? (
        <Failed what="The plans" retry={() => void plans.refetch()} />
      ) : plans.data.length === 0 ? (
        <Empty heading="No plans" body="Plans are written the first time a clinic registers." />
      ) : (
        <ul className="grid gap-5 lg:grid-cols-3">
          {plans.data.map((plan) => (
            <PlanCard key={plan.id} plan={plan} />
          ))}
        </ul>
      )}
    </Page>
  );
}

function PlanCard({ plan }: { plan: Plan }) {
  const [editing, setEditing] = useState(false);
  return (
    <li className="flex flex-col rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-5">
      {editing ? (
        <PlanForm plan={plan} onClose={() => setEditing(false)} />
      ) : (
        <>
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <h2 className="text-[18px] font-semibold tracking-tight">{plan.name}</h2>
              <p className="mt-0.5 text-[14px] leading-snug text-[var(--text-muted)]">
                {plan.description || "No description"}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setEditing(true)}
              aria-label={`Edit ${plan.name}`}
              className="shrink-0 rounded-[var(--radius-field)] p-2 text-[var(--text-muted)] transition-colors hover:bg-[var(--surface-sunken)] hover:text-[var(--text)]"
            >
              <Pencil className="size-4" />
            </button>
          </div>
          <p className="mt-4 text-[26px] leading-none font-semibold tracking-tight tabular">
            {Number(plan.price_monthly) === 0 ? "Free" : money(plan.price_monthly, "INR")}
            {Number(plan.price_monthly) > 0 && (
              <span className="ml-1 text-[14px] font-normal text-[var(--text-muted)]">
                a month
              </span>
            )}
          </p>
          <dl className="mt-5 flex flex-col gap-2 border-t border-[var(--border)] pt-4 text-[14px]">
            {MEASURES.map((measure) => {
              const cap = plan.limits[measure.limit];
              return (
                <div key={measure.key} className="flex items-baseline justify-between gap-3">
                  <dt className="text-[var(--text-muted)]">{measure.label}</dt>
                  <dd className="shrink-0 font-medium tabular">
                    {cap === null
                      ? "No limit"
                      : `${whole(cap)}${measure.unit ? ` ${measure.unit}` : ""}`}
                  </dd>
                </div>
              );
            })}
          </dl>
          <Link
            href={`/admin/clinics?plan=${plan.id}` as Route}
            className="mt-auto pt-5 text-[14px] text-[var(--text-muted)] underline-offset-2 hover:text-[var(--text)] hover:underline"
          >
            {plan.clinics === 0
              ? "No clinic is on it"
              : `${whole(plan.clinics)} ${plan.clinics === 1 ? "clinic is" : "clinics are"} on it`}
          </Link>
        </>
      )}
    </li>
  );
}

type Draft = {
  name: string;
  description: string;
  price: string;
  limits: Record<keyof Limits, string>;
};

function draftOf(plan: Plan): Draft {
  const limits = {} as Record<keyof Limits, string>;
  for (const measure of MEASURES) {
    const cap = plan.limits[measure.limit];
    limits[measure.limit] = cap === null ? "" : String(cap);
  }
  return {
    name: plan.name,
    description: plan.description,
    price: String(Number(plan.price_monthly)),
    limits,
  };
}

function check(draft: Draft): Record<string, string> {
  const problems: Record<string, string> = {};
  if (draft.name.trim().length < 2) problems.name = "Give the plan a name.";
  if (!/^\d{1,7}(\.\d{1,2})?$/.test(draft.price.trim())) {
    problems.price_monthly = "A price in rupees, like 1499 or 1499.50.";
  }
  for (const measure of MEASURES) {
    const typed = draft.limits[measure.limit].trim();
    if (typed === "") continue;
    if (!/^\d+$/.test(typed) || Number(typed) < 1) {
      problems[`limits.${measure.limit}`] = "A whole number above zero, or blank for no limit.";
    }
  }
  return problems;
}

function PlanForm({ plan, onClose }: { plan: Plan; onClose: () => void }) {
  const queries = useQueryClient();
  const [draft, setDraft] = useState(() => draftOf(plan));
  const [tried, setTried] = useState(false);
  const save = useMutation({
    mutationFn: () => {
      const limits = {} as Limits;
      for (const measure of MEASURES) {
        const typed = draft.limits[measure.limit].trim();
        limits[measure.limit] = typed === "" ? null : Number(typed);
      }
      return savePlan(plan.id, {
        name: draft.name.trim(),
        description: draft.description.trim(),
        price_monthly: draft.price.trim(),
        limits,
      });
    },
    onSuccess: () => {
      void queries.invalidateQueries({ queryKey: ["platform"] });
      onClose();
    },
  });

  const local = tried ? check(draft) : {};
  const remote = save.error instanceof ApiFailure ? (save.error.fields ?? {}) : {};
  const problems = { ...remote, ...local };

  const field = (key: string, label: string, input: React.ReactNode) => (
    <div key={key}>
      <label htmlFor={`${plan.id}-${key}`} className="text-[13px] font-medium">
        {label}
      </label>
      <div className="mt-1">{input}</div>
      {problems[key] && (
        <p
          id={`${plan.id}-${key}-problem`}
          className="mt-1 text-[12px] text-[var(--color-state-noshow)]"
        >
          {problems[key]}
        </p>
      )}
    </div>
  );

  return (
    <form
      noValidate
      className="flex flex-col gap-3.5"
      onSubmit={(event) => {
        event.preventDefault();
        setTried(true);
        if (Object.keys(check(draft)).length || save.isPending) return;
        save.mutate();
      }}
    >
      <h2 className="text-[16px] font-semibold tracking-tight">Edit {plan.name}</h2>
      {field(
        "name",
        "Name",
        <input
          id={`${plan.id}-name`}
          value={draft.name}
          maxLength={64}
          aria-invalid={Boolean(problems.name)}
          onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          className={INPUT}
        />,
      )}
      {field(
        "description",
        "Who it is for",
        <input
          id={`${plan.id}-description`}
          value={draft.description}
          maxLength={300}
          onChange={(event) => setDraft({ ...draft, description: event.target.value })}
          className={INPUT}
        />,
      )}
      {field(
        "price_monthly",
        "Price a month, in rupees",
        <input
          id={`${plan.id}-price_monthly`}
          value={draft.price}
          inputMode="decimal"
          aria-invalid={Boolean(problems.price_monthly)}
          onChange={(event) => setDraft({ ...draft, price: event.target.value })}
          className={`${INPUT} tabular`}
        />,
      )}
      <fieldset className="flex flex-col gap-3 border-t border-[var(--border)] pt-3">
        <legend className="sr-only">Limits</legend>
        <p className="text-[12px] text-[var(--text-subtle)]">Leave a limit blank for none.</p>
        {MEASURES.map((measure) =>
          field(
            `limits.${measure.limit}`,
            `${measure.label}${measure.unit ? ` (${measure.unit})` : ""}`,
            <input
              id={`${plan.id}-limits.${measure.limit}`}
              value={draft.limits[measure.limit]}
              inputMode="numeric"
              placeholder="No limit"
              aria-invalid={Boolean(problems[`limits.${measure.limit}`])}
              onChange={(event) =>
                setDraft({
                  ...draft,
                  limits: { ...draft.limits, [measure.limit]: event.target.value },
                })
              }
              className={`${INPUT} tabular`}
            />,
          ),
        )}
      </fieldset>
      {save.error && !Object.keys(remote).length && (
        <p role="alert" className="text-[14px] text-[var(--color-state-noshow)]">
          {save.error instanceof ApiFailure
            ? save.error.message
            : "That did not save. Try again."}
        </p>
      )}
      <div className="flex flex-wrap gap-2 pt-1">
        <button
          type="submit"
          disabled={save.isPending}
          className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-3.5 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06] disabled:opacity-60"
        >
          {save.isPending && <Loader2 className="size-4 animate-spin" />}
          Save {plan.name}
        </button>
        <button type="button" disabled={save.isPending} onClick={onClose} className={QUIET}>
          Cancel
        </button>
      </div>
    </form>
  );
}
