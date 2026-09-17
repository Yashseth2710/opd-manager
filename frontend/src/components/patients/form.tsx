"use client";

import { useId } from "react";
import { Field } from "@/components/auth/form";
import {
  BLOOD_GROUPS,
  GENDERS,
  type BloodGroup,
  type Gender,
  type PatientDraft,
} from "@/lib/patients";

/** A select that wears the same clothes as the text fields around it. */
export function Choice({
  label,
  value,
  onChange,
  options,
  placeholder = "Not recorded",
  error,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
  error?: string;
}) {
  const id = useId();
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-[14px] font-medium">
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        aria-invalid={error ? true : undefined}
        className={`w-full rounded-[var(--radius-field)] border bg-[var(--surface)] px-3 py-2.5 text-[15px] transition-colors ${
          error
            ? "border-[var(--color-state-noshow)]"
            : "border-[var(--border-strong)] hover:border-[var(--color-paper-400)]"
        } ${value ? "" : "text-[var(--text-subtle)]"}`}
      >
        <option value="">{placeholder}</option>
        {options.map((option) => (
          <option key={option.value} value={option.value} className="text-[var(--text)]">
            {option.label}
          </option>
        ))}
      </select>
      {error && <p className="mt-1.5 text-[13px] text-[var(--color-state-noshow)]">{error}</p>}
    </div>
  );
}

export function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-t border-[var(--border)] pt-6 first:border-0 first:pt-0">
      <h2 className="text-[15px] font-semibold tracking-tight">{title}</h2>
      {hint && <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">{hint}</p>}
      <div className="mt-4 grid gap-4 sm:grid-cols-2">{children}</div>
    </section>
  );
}

const today = () => new Date().toISOString().slice(0, 10);

/**
 * Every field of a patient record, laid out in the order somebody at a desk
 * actually collects them: who, how to reach them, where they live, who to
 * call. Shared by registration and by editing, so the two can never drift
 * into asking for different things.
 */
export function PatientFields({
  draft,
  onChange,
  errors,
}: {
  draft: PatientDraft;
  onChange: (changes: Partial<PatientDraft>) => void;
  errors: Record<string, string>;
}) {
  const address = draft.address ?? {};
  const contact = draft.emergency_contact ?? {};

  const setAddress = (changes: Partial<typeof address>) =>
    onChange({ address: { ...address, ...changes } });
  const setContact = (changes: Partial<typeof contact>) =>
    onChange({ emergency_contact: { ...contact, ...changes } });

  return (
    <div className="flex flex-col gap-7">
      <Section title="Who they are">
        <Field
          label="First name"
          name="first_name"
          value={draft.first_name}
          onChange={(v) => onChange({ first_name: v })}
          error={errors.first_name}
          autoFocus
          required
        />
        <Field
          label="Last name"
          name="last_name"
          value={draft.last_name}
          onChange={(v) => onChange({ last_name: v })}
          error={errors.last_name}
        />
        <Field
          label="Known as"
          name="preferred_name"
          value={draft.preferred_name ?? ""}
          onChange={(v) => onChange({ preferred_name: v })}
          error={errors.preferred_name}
          hint="What they are actually called, if it is not the name above."
        />
        <Field
          label="Date of birth"
          name="date_of_birth"
          type="date"
          value={draft.date_of_birth ?? ""}
          onChange={(v) => onChange({ date_of_birth: v })}
          error={errors.date_of_birth}
          hint={`Age is worked out from this. Nothing after ${today()}.`}
        />
        <Choice
          label="Gender"
          value={draft.gender ?? ""}
          onChange={(v) => onChange({ gender: (v || null) as Gender | null })}
          error={errors.gender}
          options={GENDERS.map((value) => ({
            value,
            label: value.charAt(0).toUpperCase() + value.slice(1),
          }))}
        />
        <Choice
          label="Blood group"
          value={draft.blood_group ?? ""}
          onChange={(v) => onChange({ blood_group: (v || null) as BloodGroup | null })}
          error={errors.blood_group}
          options={BLOOD_GROUPS.map((value) => ({ value, label: value }))}
        />
      </Section>

      <Section title="How to reach them">
        <Field
          label="Phone"
          name="phone"
          type="tel"
          value={draft.phone ?? ""}
          onChange={(v) => onChange({ phone: v })}
          error={errors.phone}
          placeholder="98200 11223"
        />
        <Field
          label="Alternate phone"
          name="alternate_phone"
          type="tel"
          value={draft.alternate_phone ?? ""}
          onChange={(v) => onChange({ alternate_phone: v })}
          error={errors.alternate_phone}
        />
        <Field
          label="Email"
          name="email"
          type="email"
          value={draft.email ?? ""}
          onChange={(v) => onChange({ email: v })}
          error={errors.email}
          placeholder="them@example.com"
        />
      </Section>

      <Section title="Where they live">
        <Field
          label="Address"
          name="line1"
          value={address.line1 ?? ""}
          onChange={(v) => setAddress({ line1: v })}
          error={errors["address.line1"]}
        />
        <Field
          label="Area"
          name="line2"
          value={address.line2 ?? ""}
          onChange={(v) => setAddress({ line2: v })}
        />
        <Field
          label="City"
          name="city"
          value={address.city ?? ""}
          onChange={(v) => setAddress({ city: v })}
        />
        <Field
          label="State"
          name="state"
          value={address.state ?? ""}
          onChange={(v) => setAddress({ state: v })}
        />
        <Field
          label="PIN code"
          name="postal_code"
          value={address.postal_code ?? ""}
          onChange={(v) => setAddress({ postal_code: v })}
        />
      </Section>

      <Section title="In an emergency" hint="Who the clinic calls if it cannot reach them.">
        <Field
          label="Name"
          name="contact_name"
          value={contact.name ?? ""}
          onChange={(v) => setContact({ name: v })}
        />
        <Field
          label="Relationship"
          name="contact_relationship"
          value={contact.relationship ?? ""}
          onChange={(v) => setContact({ relationship: v })}
          placeholder="Spouse, son, neighbour"
        />
        <Field
          label="Phone"
          name="contact_phone"
          type="tel"
          value={contact.phone ?? ""}
          onChange={(v) => setContact({ phone: v })}
        />
      </Section>

      <section className="border-t border-[var(--border)] pt-6">
        <h2 className="text-[15px] font-semibold tracking-tight">Anything else</h2>
        <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
          Standing notes about this person. Not a place for consultation notes.
        </p>
        <textarea
          name="notes"
          value={draft.notes ?? ""}
          onChange={(event) => onChange({ notes: event.target.value })}
          rows={3}
          maxLength={4000}
          className="mt-4 w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2.5 text-[15px] transition-colors hover:border-[var(--color-paper-400)]"
        />
      </section>
    </div>
  );
}
