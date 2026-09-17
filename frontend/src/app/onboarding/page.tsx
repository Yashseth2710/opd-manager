import type { Route } from "next";
import { redirect } from "next/navigation";

/**
 * Setup lives in settings rather than a wizard of its own: the same fields,
 * in the same place people go to change them later. This keeps older links
 * working.
 */
export default function OnboardingPage() {
  redirect("/settings" as Route);
}
