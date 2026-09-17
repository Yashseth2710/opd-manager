"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { Problem } from "@/components/auth/form";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { Duplicates } from "@/components/patients/duplicates";
import { PatientFields } from "@/components/patients/form";
import { ApiFailure } from "@/lib/api";
import {
  checkDuplicates,
  registerPatient,
  type DuplicateCandidate,
  type PatientDraft,
} from "@/lib/patients";

const BLANK: PatientDraft = {
  first_name: "",
  last_name: "",
  preferred_name: "",
  phone: "",
  alternate_phone: "",
  email: "",
  date_of_birth: "",
  gender: null,
  blood_group: null,
  address: {},
  emergency_contact: {},
  notes: "",
};

/** Strips the empty strings a form produces, which the API reads as values. */
function cleaned(draft: PatientDraft): PatientDraft {
  const blank = (value: unknown) => typeof value === "string" && value.trim() === "";
  const trimmed = Object.fromEntries(
    Object.entries(draft).map(([key, value]) => [key, blank(value) ? null : value]),
  ) as PatientDraft;

  for (const key of ["address", "emergency_contact"] as const) {
    const nested = trimmed[key];
    if (!nested || Object.values(nested).every((value) => !String(value ?? "").trim())) {
      trimmed[key] = null;
    }
  }
  return trimmed;
}

export default function NewPatientPage() {
  return (
    <Permitted permission="patient:create">
      <NewPatient />
    </Permitted>
  );
}

function NewPatient() {
  const router = useRouter();
  const queries = useQueryClient();
  const [draft, setDraft] = useState<PatientDraft>(BLANK);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [problem, setProblem] = useState<string | null>(null);
  const [candidates, setCandidates] = useState<DuplicateCandidate[]>([]);

  // A disabled button is not enough. Two clicks in the same tick both reach
  // the handler before React has re-rendered with the pending state, and
  // here that means two records for one person — the exact thing the rest of
  // this screen exists to prevent.
  const inFlight = useRef(false);

  const change = (changes: Partial<PatientDraft>) => {
    setDraft((current) => ({ ...current, ...changes }));
    setFields((current) => {
      const next = { ...current };
      for (const key of Object.keys(changes)) delete next[key];
      return next;
    });
  };

  // Asked while they are still typing, so the existing record turns up in
  // time to open instead of after a second one has been created.
  useEffect(() => {
    const phone = draft.phone?.trim();
    const email = draft.email?.trim();
    const dialable = Boolean(phone && phone.replace(/\D/g, "").length >= 7);
    const named = Boolean(draft.first_name.trim() && draft.date_of_birth);

    let current = true;
    const timer = setTimeout(() => {
      if (!dialable && !email && !named) {
        setCandidates([]);
        return;
      }
      checkDuplicates({
        first_name: draft.first_name,
        last_name: draft.last_name,
        phone: phone || null,
        email: email || null,
        date_of_birth: draft.date_of_birth || null,
      })
        .then((found) => current && setCandidates(found))
        .catch(() => current && setCandidates([]));
    }, 400);

    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [draft.phone, draft.email, draft.first_name, draft.last_name, draft.date_of_birth]);

  const save = useMutation({
    mutationFn: (confirm: boolean) =>
      registerPatient({ ...cleaned(draft), confirm_duplicate: confirm }),
    onSettled: () => {
      inFlight.current = false;
    },
    onSuccess: (patient) => {
      void queries.invalidateQueries({ queryKey: ["patients"] });
      router.replace(`/patients/${patient.id}`);
    },
    onError: (error) => {
      if (!(error instanceof ApiFailure)) {
        setProblem("Something went wrong.");
        return;
      }
      if (error.code === "PATIENT_DUPLICATE_SUSPECTED") {
        setCandidates((error.candidates as DuplicateCandidate[] | undefined) ?? []);
        setProblem(null);
        window.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      if (error.fields) {
        setFields(error.fields);
        setProblem(null);
        return;
      }
      setProblem(error.message);
    },
  });

  const register = (confirm: boolean) => {
    if (inFlight.current) return;
    inFlight.current = true;
    save.mutate(confirm);
  };

  return (
    <Page
      title="Register a patient"
      blurb="Only a name is required. The rest can follow."
      back={{ href: "/patients", label: "Back to patients" }}
    >
      {problem && <Problem>{problem}</Problem>}

      <Duplicates
        candidates={candidates}
        busy={save.isPending}
        onRegisterAnyway={() => register(true)}
      />

      <form
        onSubmit={(event) => {
          event.preventDefault();
          setProblem(null);
          register(false);
        }}
        noValidate
      >
        <PatientFields draft={draft} onChange={change} errors={fields} />

        <div className="mt-8 flex items-center gap-3 border-t border-[var(--border)] pt-6">
          <button
            type="submit"
            disabled={save.isPending || !draft.first_name.trim()}
            className="inline-flex items-center gap-2 rounded-[var(--radius-field)] bg-[var(--accent)] px-4 py-2.5 text-[15px] font-semibold text-[var(--color-ink-900)] transition-[filter,transform] duration-150 ease-[var(--ease-out-quint)] hover:brightness-[1.06] active:translate-y-px disabled:cursor-not-allowed disabled:opacity-60"
          >
            {save.isPending && <Loader2 className="size-4 animate-spin" />}
            {save.isPending ? "Registering" : "Register patient"}
          </button>
          <Link
            href="/patients"
            className="rounded-[var(--radius-field)] px-3 py-2 text-[14px] text-[var(--text-muted)] transition-colors hover:text-[var(--text)]"
          >
            Cancel
          </Link>
        </div>
      </form>
    </Page>
  );
}
