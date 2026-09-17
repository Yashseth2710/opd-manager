"use client";

import { Field } from "@/components/auth/form";
import { Choice, Section } from "@/components/patients/form";
import { TITLES, type DoctorDraft, type Title } from "@/lib/doctors";

/** A number box that reads back as money, and is blank when it is blank. */
function Amount({
  label,
  name,
  value,
  onChange,
  error,
  hint,
}: {
  label: string;
  name: string;
  value: string;
  onChange: (value: string) => void;
  error?: string;
  hint?: React.ReactNode;
}) {
  return (
    <Field
      label={label}
      name={name}
      type="number"
      value={value}
      onChange={onChange}
      error={error}
      hint={hint}
      placeholder="Clinic default"
    />
  );
}

/**
 * Everything on a doctor's profile, in the order somebody setting up a
 * clinic works through it: who they are, what they practise, what they
 * charge, how to reach them. Shared by adding and by editing, so the two
 * cannot drift into asking for different things.
 */
export function DoctorFields({
  draft,
  onChange,
  errors,
  clinic,
  accounts,
}: {
  draft: DoctorDraft;
  onChange: (changes: Partial<DoctorDraft>) => void;
  errors: Record<string, string>;
  /**
   * The clinic's own figures, or undefined until they arrive.
   *
   * Every hint below that names one is hidden while it is undefined. A form
   * that says "the clinic charges zero" for the second before it knows is
   * telling somebody a number they might decide not to type over.
   */
  clinic?: {
    consultation_fee: string;
    follow_up_fee: string;
    consultation_duration_minutes: number;
  };
  accounts: { value: string; label: string }[];
}) {
  return (
    <div className="flex flex-col gap-7">
      <Section title="Who they are">
        <Choice
          label="Title"
          value={draft.title}
          onChange={(value) => onChange({ title: (value || "Dr") as Title })}
          options={TITLES.map((title) => ({ value: title, label: title }))}
          placeholder="Dr"
          error={errors.title}
        />
        <Field
          label="First name"
          name="first_name"
          value={draft.first_name}
          onChange={(value) => onChange({ first_name: value })}
          error={errors.first_name}
          autoFocus
          required
        />
        <Field
          label="Last name"
          name="last_name"
          value={draft.last_name}
          onChange={(value) => onChange({ last_name: value })}
          error={errors.last_name}
        />
        <Field
          label="Consulting room"
          name="room"
          value={draft.room ?? ""}
          onChange={(value) => onChange({ room: value })}
          error={errors.room}
          placeholder="3"
        />
      </Section>

      <Section title="What they practise">
        <Field
          label="Speciality"
          name="speciality"
          value={draft.speciality ?? ""}
          onChange={(value) => onChange({ speciality: value })}
          error={errors.speciality}
          placeholder="Paediatrics"
        />
        <Field
          label="Qualifications"
          name="qualifications"
          value={draft.qualifications ?? ""}
          onChange={(value) => onChange({ qualifications: value })}
          error={errors.qualifications}
          placeholder="MBBS, MD"
        />
        <Field
          label="Registration number"
          name="registration_number"
          value={draft.registration_number ?? ""}
          onChange={(value) => onChange({ registration_number: value })}
          error={errors.registration_number}
          hint="Their medical council number. No two doctors here can share one."
        />
        <Field
          label="Years in practice"
          name="years_of_experience"
          type="number"
          value={
            draft.years_of_experience === null ? "" : String(draft.years_of_experience ?? "")
          }
          onChange={(value) =>
            onChange({ years_of_experience: value === "" ? null : Number(value) })
          }
          error={errors.years_of_experience}
        />
        <Field
          label="Languages"
          name="languages"
          value={(draft.languages ?? []).join(", ")}
          onChange={(value) =>
            onChange({ languages: value.split(",").map((one) => one.trim()) })
          }
          error={errors.languages}
          hint="Separated by commas. Patients ask."
          placeholder="Hindi, Marathi, English"
        />
      </Section>

      <Section
        title="What they charge"
        hint="Leave a box empty to follow the clinic's figure, so raising it later reaches them too."
      >
        <Amount
          label="Consultation fee"
          name="consultation_fee"
          value={draft.consultation_fee ?? ""}
          onChange={(value) => onChange({ consultation_fee: value })}
          error={errors.consultation_fee}
          hint={clinic && `The clinic charges ₹${clinic.consultation_fee}.`}
        />
        <Amount
          label="Follow-up fee"
          name="follow_up_fee"
          value={draft.follow_up_fee ?? ""}
          onChange={(value) => onChange({ follow_up_fee: value })}
          error={errors.follow_up_fee}
          hint={clinic && `The clinic charges ₹${clinic.follow_up_fee}.`}
        />
        <Field
          label="Appointment length"
          name="slot_duration_minutes"
          type="number"
          value={
            draft.slot_duration_minutes === null
              ? ""
              : String(draft.slot_duration_minutes ?? "")
          }
          onChange={(value) =>
            onChange({ slot_duration_minutes: value === "" ? null : Number(value) })
          }
          error={errors.slot_duration_minutes}
          hint={
            clinic
              ? `Minutes. The clinic books ${clinic.consultation_duration_minutes}.`
              : "Minutes."
          }
          placeholder={clinic ? String(clinic.consultation_duration_minutes) : ""}
        />
      </Section>

      <Section title="How to reach them">
        <Field
          label="Phone"
          name="phone"
          type="tel"
          value={draft.phone ?? ""}
          onChange={(value) => onChange({ phone: value })}
          error={errors.phone}
          placeholder="98200 33445"
        />
        <Field
          label="Email"
          name="email"
          type="email"
          value={draft.email ?? ""}
          onChange={(value) => onChange({ email: value })}
          error={errors.email}
          placeholder="them@example.com"
        />
        <Choice
          label="Signs in as"
          value={draft.user_id ?? ""}
          onChange={(value) => onChange({ user_id: value || null })}
          options={accounts}
          placeholder="No account yet"
          error={errors.user_id}
        />
      </Section>

      <section className="border-t border-[var(--border)] pt-6">
        <h2 className="text-[15px] font-semibold tracking-tight">About them</h2>
        <p className="mt-0.5 text-[13px] text-[var(--text-muted)]">
          A short introduction. Patients see this when they choose who to book with.
        </p>
        <textarea
          name="bio"
          value={draft.bio ?? ""}
          onChange={(event) => onChange({ bio: event.target.value })}
          rows={3}
          maxLength={2000}
          className="mt-4 w-full rounded-[var(--radius-field)] border border-[var(--border-strong)] bg-[var(--surface)] px-3 py-2.5 text-[15px] transition-colors hover:border-[var(--color-paper-400)]"
        />
      </section>
    </div>
  );
}
