import { request, type FullConfig } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { EMPTY_STATE, SHARED_STATE } from "./state";

/**
 * Two clinics, once per run.
 *
 * Setting up a clinic is rate limited to a handful an hour from one address,
 * which is the right behaviour for a sign-up form and means a run cannot
 * register casually. Doing it here rather than in a fixture also survives a
 * worker being restarted after a failure, which would otherwise spend a
 * registration every time something went wrong.
 *
 * One clinic is shared by almost everything, with each test naming its own
 * doctors. The other is never written to, so the screen a clinic sees before
 * it has added anybody can be tested at all.
 */
async function register(baseURL: string, into: string) {
  const api = await request.newContext({ baseURL });
  const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

  const created = await api.post("/api/v1/auth/register", {
    data: {
      clinic_name: `Sunrise Clinic ${stamp}`,
      first_name: "Priya",
      last_name: "Nair",
      email: `priya.${stamp}@sunrisecare.org`,
      password: "a properly long password",
    },
  });

  if (!created.ok()) {
    throw new Error(`Could not set up a clinic to test against: ${await created.text()}`);
  }
  if (!(await created.json()).data?.session) {
    throw new Error(
      "Registration asked for email confirmation instead of signing in. These " +
        "tests need an API with no email provider configured: blank " +
        "BREVO_API_KEY and RESEND_API_KEY.",
    );
  }

  await mkdir(dirname(into), { recursive: true });
  await writeFile(into, JSON.stringify(await api.storageState(), null, 2));
  await api.dispose();
}

export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0]?.use.baseURL ?? "http://localhost:3000";
  await register(baseURL, SHARED_STATE);
  await register(baseURL, EMPTY_STATE);
}
