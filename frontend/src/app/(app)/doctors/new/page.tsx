"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useRef, useState } from "react";
import { Problem } from "@/components/auth/form";
import { showFirstProblem } from "@/components/common/first-problem";
import { DoctorFields } from "@/components/doctors/form";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { ApiFailure } from "@/lib/api";
import { getSettings, getStaff } from "@/lib/clinic";
import { addDoctor, cleaned, type DoctorDraft } from "@/lib/doctors";

const BLANK: DoctorDraft = {
  title: "Dr",
  first_name: "",
  last_name: "",
  speciality: "",
  qualifications: "",
  registration_number: "",
  years_of_experience: null,
  phone: "",
  email: "",
  room: "",
  languages: [],
  bio: "",
  consultation_fee: "",
  follow_up_fee: "",
  slot_duration_minutes: null,
  user_id: null,
};

export default function NewDoctorPage() {
  return (
    <Permitted permission="doctor:manage">
      <NewDoctor />
    </Permitted>
  );
}

function NewDoctor() {
  const router = useRouter();
  const queries = useQueryClient();
  const [draft, setDraft] = useState<DoctorDraft>(BLANK);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);

  // A disabled button is not enough. Two clicks in the same tick both reach
  // the handler before React has re-rendered with the pending state, and
  // here that means two profiles for one clinician.
  const inFlight = useRef(false);

  const settings = useQuery({ queryKey: ["settings"], queryFn: getSettings, retry: false });
  const staff = useQuery({ queryKey: ["staff"], queryFn: getStaff, retry: false });

  const change = (changes: Partial<DoctorDraft>) => {
    setDraft((current) => ({ ...current, ...changes }));
    setFields((current) => {
      const next = { ...current };
      for (const key of Object.keys(changes)) delete next[key];
      return next;
    });
  };

  const save = useMutation({
    mutationFn: () => addDoctor(cleaned(draft)),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: (doctor) => {
      void queries.invalidateQueries({ queryKey: ["doctors"] });
      void queries.invalidateQueries({ queryKey: ["specialities"] });
      router.replace(`/doctors/${doctor.id}`);
    },
    onError: (error) => {
      if (!(error instanceof ApiFailure)) {
        setProblem("Something went wrong.");
        return;
      }
      if (error.fields) {
        setFields(error.fields);
        setProblem(null);
        showFirstProblem(error.fields);
        return;
      }
      setProblem(error.message);
    },
  });

  const accounts = (staff.data ?? [])
    .filter((member) => member.status === "active")
    .map((member) => ({
      value: member.id,
      label: `${member.first_name} ${member.last_name} · ${member.email}`,
    }));

  return (
    <Page
      title="Add a doctor"
      blurb="Only a name is required. Hours and leave come after, on their page."
      back={{ href: "/doctors", label: "Back to doctors" }}
    >
      {problem && <Problem>{problem}</Problem>}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setProblem(null);
          if (inFlight.current) return;
          inFlight.current = true;
          save.mutate();
        }}
        noValidate
      >
        <DoctorFields
          draft={draft}
          onChange={change}
          errors={fields}
          clinic={settings.data}
          accounts={accounts}
        />

        <div className="mt-8 flex items-center gap-3 border-t border-[var(--border)] pt-6">
          <button
            type="submit"
            disabled={save.isPending || !draft.first_name.trim()}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2.5 text-[15px] font-semibold text-[var(--color-ink-900)] transition-[filter,transform] duration-150 ease-[var(--ease-out-quint)] hover:brightness-[1.06] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60"
          >
            {save.isPending && <Loader2 className="size-4 animate-spin" />}
            {save.isPending ? "Adding" : "Add doctor"}
          </button>
          <Link
            href="/doctors"
            className="rounded-[var(--radius-field)] px-3 py-2 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
          >
            Cancel
          </Link>
        </div>
      </form>
    </Page>
  );
}
