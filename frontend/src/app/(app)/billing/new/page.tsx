"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import type { Route } from "next";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { PatientPicker } from "@/components/appointments/patient-picker";
import { BillEditor } from "@/components/billing/editor";
import { Permitted } from "@/components/layout/permitted";
import { Page } from "@/components/layout/shell";
import { ApiFailure } from "@/lib/api";
import { shortDate } from "@/lib/appointments";
import { getStarting } from "@/lib/billing";

export default function NewBillPage() {
  return (
    <Permitted permission="billing:create">
      <Suspense fallback={<Opening />}>
        <NewBill />
      </Suspense>
    </Permitted>
  );
}

function Opening() {
  return (
    <div className="flex min-h-[40vh] items-center justify-center gap-3 text-[var(--text-muted)]">
      <Loader2 className="size-5 animate-spin" />
      <span className="text-[15px]">Getting the bill ready…</span>
    </div>
  );
}

const BACK = { href: "/billing" as Route, label: "Back to billing" };

function NewBill() {
  const router = useRouter();
  const params = useSearchParams();
  const visit = params.get("visit");
  const patient = params.get("patient");

  const start = useQuery({
    queryKey: ["bill-start", { visit, patient }],
    queryFn: () => getStarting({ visit, patient }),
    enabled: Boolean(visit || patient),
    retry: false,
    // A fee changed in settings a moment ago should be the one offered.
    staleTime: 0,
    gcTime: 0,
  });

  if (!visit && !patient) {
    return (
      <Page title="New bill" blurb="Who is it for?" back={BACK}>
        <div className="max-w-xl">
          <PatientPicker
            chosen={null}
            onChoose={(chosen) => {
              if (chosen) router.replace(`/billing/new?patient=${chosen.id}` as Route);
            }}
          />
        </div>
      </Page>
    );
  }

  if (start.isPending) return <Opening />;

  if (start.isError) {
    const words =
      start.error instanceof ApiFailure && start.error.status === 404
        ? "That patient or visit could not be found at your clinic."
        : "The bill could not be started. Try again in a moment.";
    return (
      <Page title="New bill" back={BACK}>
        <p className="text-[15px] text-[var(--text-muted)]">{words}</p>
      </Page>
    );
  }

  const found = start.data;
  const archived = found.patient.status === "archived";

  return (
    <Page
      title={`Bill for ${found.patient.full_name}`}
      blurb={
        found.visit
          ? `The visit on ${shortDate(found.visit.date)}, token ${found.visit.token}${found.doctor ? `, with ${found.doctor.display_name}` : ""}.`
          : "Not tied to a visit. Use it for anything done at the desk."
      }
      back={BACK}
    >
      {found.existing ? (
        <div
          role="status"
          className="rounded-[var(--radius-panel)] border border-[var(--border-strong)] bg-[var(--surface)] px-5 py-4 text-[15px]"
        >
          <p className="font-medium">
            This visit already has a bill
            {found.existing_number ? `, ${found.existing_number}` : ", still a draft"}.
          </p>
          <p className="mt-1 text-[var(--text-muted)]">
            A visit is billed once.{" "}
            {found.existing_number
              ? "To bill it differently, void that one first."
              : "Change the draft there, or delete it to start again."}
          </p>
          <Link
            href={`/billing/${found.existing}` as Route}
            className="mt-3 inline-flex font-medium underline underline-offset-2"
          >
            Open the bill
          </Link>
        </div>
      ) : archived ? (
        <p className="text-[15px] text-[var(--text-muted)]">
          This record is archived. Restore it before raising a bill.
        </p>
      ) : (
        <BillEditor
          context={{
            patientId: found.patient.id,
            visitId: found.visit?.queue_entry_id ?? null,
            currency: found.currency,
            taxPercent: found.tax_percent,
            labTests: found.lab_tests,
          }}
          start={{
            items: found.items,
            discount_amount: "0.00",
            discount_reason: null,
            notes: null,
          }}
        />
      )}
    </Page>
  );
}
