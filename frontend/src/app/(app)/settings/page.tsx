"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, Loader2 } from "lucide-react";
import { useState } from "react";
import { Field, Problem } from "@/components/auth/form";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { Meter } from "@/components/platform/parts";
import { ApiFailure } from "@/lib/api";
import { financialYear } from "@/lib/billing";
import { currentSession } from "@/lib/auth";
import { MEASURES } from "@/lib/platform";
import {
  completeSetup,
  getClinic,
  getPlan,
  getSettings,
  saveClinic,
  saveSettings,
  type Clinic,
  type ClinicSettings,
} from "@/lib/clinic";

export default function SettingsPage() {
  return (
    <Permitted permission="settings:manage">
      <SettingsScreen />
    </Permitted>
  );
}

function SettingsScreen() {
  const queries = useQueryClient();
  const clinic = useQuery({ queryKey: ["clinic"], queryFn: getClinic, retry: false });
  const settings = useQuery({
    queryKey: ["clinic-settings"],
    queryFn: getSettings,
    retry: false,
  });

  if (clinic.isPending || settings.isPending) {
    return (
      <div className="flex min-h-[60vh] items-center justify-center gap-3 text-[var(--text-muted)]">
        <Loader2 className="size-5 animate-spin" />
        <span className="text-[15px]">Loading settings…</span>
      </div>
    );
  }

  if (!clinic.data || !settings.data) {
    return (
      <Page title="Settings">
        <Problem>Settings could not be loaded. Refresh the page to try again.</Problem>
      </Page>
    );
  }

  return (
    <Page
      title="Settings"
      blurb="How this clinic identifies itself, and what it charges."
      action={
        clinic.data.status === "pending" ? (
          <OpenClinicButton onDone={() => void queries.invalidateQueries()} />
        ) : (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-[color-mix(in_srgb,var(--color-state-completed)_13%,transparent)] px-3 py-1 text-[13px] font-medium text-[var(--color-state-completed)]">
            <Check className="size-3.5" />
            Open
          </span>
        )
      }
    >
      <div className="flex flex-col gap-10">
        <ClinicDetails clinic={clinic.data} />
        <FeesAndTiming settings={settings.data} currency={clinic.data.currency} />
        <Bills settings={settings.data} />
        <PlanSection />
      </div>
    </Page>
  );
}

function Section({
  title,
  blurb,
  children,
}: {
  title: string;
  blurb: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h2 className="text-[17px] font-semibold tracking-tight">{title}</h2>
      <p className="mt-1 mb-5 text-[14px] text-[var(--text-muted)]">{blurb}</p>
      {children}
    </section>
  );
}

function SaveRow({ busy, saved }: { busy: boolean; saved: boolean }) {
  return (
    <div className="mt-6 flex items-center gap-3">
      <button
        type="submit"
        disabled={busy}
        className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--primary)] px-4 py-2 text-[14px] font-medium text-[var(--primary-fg)] transition hover:brightness-110 disabled:opacity-50"
      >
        {busy && <Loader2 className="size-4 animate-spin" />}
        {busy ? "Saving" : "Save changes"}
      </button>
      {/* Announced rather than only shown, so it reaches a screen reader. */}
      <span aria-live="polite" className="text-[14px] text-[var(--color-state-completed)]">
        {saved && !busy ? "Saved" : ""}
      </span>
    </div>
  );
}

function ClinicDetails({ clinic }: { clinic: Clinic }) {
  const queries = useQueryClient();
  const [form, setForm] = useState({
    name: clinic.name,
    phone: clinic.phone ?? "",
    email: clinic.email ?? "",
    line1: clinic.address?.line1 ?? "",
    city: clinic.address?.city ?? "",
    state: clinic.address?.state ?? "",
    postal_code: clinic.address?.postal_code ?? "",
  });
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () =>
      saveClinic({
        name: form.name,
        phone: form.phone || null,
        email: form.email || null,
        address: {
          line1: form.line1,
          city: form.city,
          state: form.state,
          postal_code: form.postal_code,
        },
      }),
    onSuccess: () => {
      setSaved(true);
      setFields({});
      setProblem(null);
      void queries.invalidateQueries({ queryKey: ["clinic"] });
    },
    onError: (error) => {
      setSaved(false);
      if (error instanceof ApiFailure && error.fields) setFields(error.fields);
      else setProblem(error instanceof Error ? error.message : "Something went wrong.");
    },
  });

  return (
    <Section title="Clinic details" blurb="What appears on invoices and prescriptions.">
      {problem && <Problem>{problem}</Problem>}
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSaved(false);
          save.mutate();
        }}
        noValidate
        className="flex flex-col gap-4"
      >
        <Field
          label="Clinic name"
          name="name"
          value={form.name}
          onChange={(v) => setForm({ ...form, name: v })}
          error={fields.name}
          required
        />
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Contact number"
            name="phone"
            value={form.phone}
            onChange={(v) => setForm({ ...form, phone: v })}
            error={fields.phone}
            placeholder="+91 22 5555 0100"
          />
          <Field
            label="Clinic email"
            name="email"
            type="email"
            value={form.email}
            onChange={(v) => setForm({ ...form, email: v })}
            error={fields.email}
            placeholder="reception@clinic.com"
          />
        </div>
        <Field
          label="Street address"
          name="line1"
          value={form.line1}
          onChange={(v) => setForm({ ...form, line1: v })}
          error={fields.address}
          placeholder="14 Marine Lines"
        />
        <div className="grid gap-4 sm:grid-cols-3">
          <Field
            label="City"
            name="city"
            value={form.city}
            onChange={(v) => setForm({ ...form, city: v })}
            error={fields.city}
          />
          <Field
            label="State"
            name="state"
            value={form.state}
            onChange={(v) => setForm({ ...form, state: v })}
          />
          <Field
            label="Postcode"
            name="postal_code"
            value={form.postal_code}
            onChange={(v) => setForm({ ...form, postal_code: v })}
          />
        </div>
        <SaveRow busy={save.isPending} saved={saved} />
      </form>
    </Section>
  );
}

function FeesAndTiming({ settings, currency }: { settings: ClinicSettings; currency: string }) {
  const queries = useQueryClient();
  const [form, setForm] = useState({
    consultation_fee: settings.consultation_fee,
    follow_up_fee: settings.follow_up_fee,
    consultation_duration_minutes: String(settings.consultation_duration_minutes),
    follow_up_window_days: String(settings.follow_up_window_days),
  });
  const [fields, setFields] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () =>
      saveSettings({
        consultation_fee: form.consultation_fee,
        follow_up_fee: form.follow_up_fee,
        consultation_duration_minutes: Number(form.consultation_duration_minutes),
        follow_up_window_days: Number(form.follow_up_window_days),
      }),
    onSuccess: (updated) => {
      setSaved(true);
      setFields({});
      setForm({
        consultation_fee: updated.consultation_fee,
        follow_up_fee: updated.follow_up_fee,
        consultation_duration_minutes: String(updated.consultation_duration_minutes),
        follow_up_window_days: String(updated.follow_up_window_days),
      });
      void queries.invalidateQueries({ queryKey: ["clinic-settings"] });
    },
    onError: (error) => {
      setSaved(false);
      if (error instanceof ApiFailure && error.fields) setFields(error.fields);
    },
  });

  return (
    <Section
      title="Fees and timing"
      blurb={`Amounts are in ${currency}. A follow-up inside the window is charged at the follow-up rate.`}
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSaved(false);
          save.mutate();
        }}
        noValidate
        className="flex flex-col gap-4"
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Consultation fee"
            name="consultation_fee"
            value={form.consultation_fee}
            onChange={(v) => setForm({ ...form, consultation_fee: v })}
            error={fields.consultation_fee}
            hint={`In ${currency}, to two decimal places.`}
          />
          <Field
            label="Follow-up fee"
            name="follow_up_fee"
            value={form.follow_up_fee}
            onChange={(v) => setForm({ ...form, follow_up_fee: v })}
            error={fields.follow_up_fee}
          />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Appointment length"
            name="consultation_duration_minutes"
            value={form.consultation_duration_minutes}
            onChange={(v) => setForm({ ...form, consultation_duration_minutes: v })}
            error={fields.consultation_duration_minutes}
            hint="Minutes"
          />
          <Field
            label="Follow-up window"
            name="follow_up_window_days"
            value={form.follow_up_window_days}
            onChange={(v) => setForm({ ...form, follow_up_window_days: v })}
            error={fields.follow_up_window_days}
            hint="Days"
          />
        </div>
        <SaveRow busy={save.isPending} saved={saved} />
      </form>
    </Section>
  );
}

function Bills({ settings }: { settings: ClinicSettings }) {
  const queries = useQueryClient();
  const [form, setForm] = useState({
    invoice_prefix: settings.invoice_prefix,
    tax_percent: settings.tax_percent,
    gstin: settings.gstin,
  });
  const [fields, setFields] = useState<Record<string, string>>({});
  const [saved, setSaved] = useState(false);

  const save = useMutation({
    mutationFn: () =>
      saveSettings({
        invoice_prefix: form.invoice_prefix,
        tax_percent: form.tax_percent || "0",
        gstin: form.gstin,
      }),
    onSuccess: (updated) => {
      setSaved(true);
      setFields({});
      setForm({
        invoice_prefix: updated.invoice_prefix,
        tax_percent: updated.tax_percent,
        gstin: updated.gstin,
      });
      void queries.invalidateQueries({ queryKey: ["clinic-settings"] });
    },
    onError: (error) => {
      setSaved(false);
      if (error instanceof ApiFailure && error.fields) setFields(error.fields);
    },
  });

  return (
    <Section
      title="Bills"
      blurb="How bills are numbered, and the tax on them. Most outpatient care carries no GST, so leave the rate at 0 unless yours does."
    >
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSaved(false);
          save.mutate();
        }}
        noValidate
        className="flex flex-col gap-4"
      >
        <div className="grid gap-4 sm:grid-cols-3">
          <Field
            label="Bill number prefix"
            name="invoice_prefix"
            value={form.invoice_prefix}
            onChange={(v) => setForm({ ...form, invoice_prefix: v })}
            error={fields.invoice_prefix}
            hint={`Bills read ${form.invoice_prefix.trim().toUpperCase() || "INV"}/${financialYear()}/0001.`}
          />
          <Field
            label="Tax rate"
            name="tax_percent"
            value={form.tax_percent}
            onChange={(v) => setForm({ ...form, tax_percent: v })}
            error={fields.tax_percent}
            hint="Percent, on new bills only"
          />
          <Field
            label="GSTIN"
            name="gstin"
            value={form.gstin}
            onChange={(v) => setForm({ ...form, gstin: v })}
            error={fields.gstin}
            hint="Printed on bills. Leave empty if not registered."
          />
        </div>
        <SaveRow busy={save.isPending} saved={saved} />
      </form>
    </Section>
  );
}

function PlanSection() {
  const session = useQuery({ queryKey: ["session"], queryFn: currentSession, retry: false });
  const allowed = session.data?.permissions.includes("subscription:manage") ?? false;
  const plan = useQuery({ queryKey: ["clinic-plan"], queryFn: getPlan, enabled: allowed });

  if (!allowed) return null;

  let blurb = "What the clinic's plan allows, and how much of it is in use.";
  if (plan.data?.on_trial && plan.data.trial_ends_at) {
    const ends = new Date(plan.data.trial_ends_at).toLocaleDateString("en-IN", {
      day: "numeric",
      month: "long",
    });
    blurb = `You are trying ${plan.data.trying_name} until ${ends}. After that the clinic moves to ${plan.data.after_trial_name}, unless a plan has been chosen for it.`;
  } else if (plan.data?.trial_over) {
    blurb = `The trial has ended, so the clinic is on ${plan.data.name}.`;
  }

  return (
    <Section title="Plan" blurb={blurb}>
      {plan.isPending ? (
        <div className="flex items-center gap-2 text-[14px] text-[var(--text-muted)]">
          <Loader2 className="size-4 animate-spin" />
          Reading the plan…
        </div>
      ) : plan.isError ? (
        <Problem>The plan did not load. Refresh the page to try again.</Problem>
      ) : (
        <div className="rounded-[var(--radius-panel)] border border-[var(--border)] bg-[var(--surface)] px-5 py-5">
          <p className="text-[16px] font-semibold">
            {plan.data.name}
            <span className="ml-2 text-[14px] font-normal text-[var(--text-muted)]">
              {plan.data.description}
            </span>
          </p>
          <div className="mt-4 flex flex-col gap-4">
            {MEASURES.map((measure) => (
              <Meter
                key={measure.key}
                label={measure.label}
                used={plan.data.usage[measure.key].used}
                limit={plan.data.usage[measure.key].limit}
                unit={measure.unit}
                fullNote="Full. Nothing more of this can be added until there is room."
              />
            ))}
          </div>
          <p className="mt-5 border-t border-[var(--border)] pt-3 text-[13px] text-[var(--text-muted)]">
            Plans are changed by the OPD Manager team. Nothing is charged in this build.
          </p>
        </div>
      )}
    </Section>
  );
}

function OpenClinicButton({ onDone }: { onDone: () => void }) {
  const [problem, setProblem] = useState<string | null>(null);
  const open = useMutation({
    mutationFn: completeSetup,
    // Cleared as the attempt starts, so a stale complaint does not sit
    // under the button while it is working.
    onMutate: () => setProblem(null),
    onSuccess: () => {
      setProblem(null);
      onDone();
    },
    onError: (error) => {
      const missing =
        error instanceof ApiFailure && error.fields
          ? Object.values(error.fields).join(" ")
          : "Something went wrong.";
      setProblem(missing);
    },
  });

  return (
    <div className="text-right">
      <button
        type="button"
        onClick={() => open.mutate()}
        disabled={open.isPending}
        className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2 text-[14px] font-semibold text-[var(--color-ink-900)] transition hover:brightness-[1.06] disabled:opacity-50"
      >
        {open.isPending && <Loader2 className="size-4 animate-spin" />}
        Open the clinic
      </button>
      {problem && (
        <p
          role="alert"
          className="mt-2 max-w-[28ch] text-[13px] text-[var(--color-state-noshow)]"
        >
          {problem}
        </p>
      )}
    </div>
  );
}
