import { request, type FullConfig } from "@playwright/test";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { MORNINGS } from "./fixtures";
import {
  ACCOUNTS,
  DOCTOR_PROFILE,
  DOCTOR_STATE,
  EMPTY_STATE,
  PASSWORD,
  SHARED_STATE,
} from "./state";

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
async function register(baseURL: string, into: string): Promise<string> {
  const api = await request.newContext({ baseURL });
  const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;

  const email = `priya.${stamp}@sunrisecare.org`;
  const created = await api.post("/api/v1/auth/register", {
    data: {
      clinic_name: `Sunrise Clinic ${stamp}`,
      first_name: "Priya",
      last_name: "Nair",
      email,
      password: PASSWORD,
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
  return email;
}

/**
 * The link in the invitation the API meant to email.
 *
 * With no email provider set up the API writes the message to its log
 * instead, which is the only place the link exists: it is never returned to
 * whoever sent the invitation.
 */
async function invitationLink(log: string, email: string): Promise<string> {
  const address = email.replace(/[.+]/g, "\\$&");
  const pattern = new RegExp(`to:\\s+${address}\\s+subject:[^\\n]*\\s+link:\\s+(\\S+)`);
  for (let attempt = 0; attempt < 40; attempt += 1) {
    const found = pattern.exec(await readFile(log, "utf8").catch(() => ""));
    if (found?.[1]) return found[1];
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  throw new Error(`No invitation for ${email} turned up in ${log}.`);
}

/**
 * A doctor who works at the shared clinic, joined the way anybody joins:
 * invited by the administrator, following the link, choosing a password.
 * Notes are only ever written by a doctor, so the screens for them cannot be
 * tested from the administrator's session.
 */
async function joinAsDoctor(baseURL: string): Promise<string> {
  const log = process.env.E2E_API_LOG;
  if (!log) {
    throw new Error(
      "Set E2E_API_LOG to the file the API is logging to. The doctor these tests " +
        "sign in as joins through an invitation link, and with no email provider " +
        "the API only writes that link to its log.",
    );
  }

  const admin = await request.newContext({ baseURL, storageState: SHARED_STATE });
  const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  const email = `meera.${stamp}@sunrisecare.org`;

  const invited = await admin.post("/api/v1/staff/invitations", {
    data: { email, first_name: "Meera", last_name: "Iyer", role_slug: "doctor" },
  });
  if (!invited.ok()) throw new Error(`Could not invite the doctor: ${await invited.text()}`);

  const token = new URL(await invitationLink(log, email)).searchParams.get("token");
  const doctor = await request.newContext({ baseURL });
  const joined = await doctor.post("/api/v1/invitations/accept", {
    data: { token, password: PASSWORD },
  });
  if (!joined.ok()) throw new Error(`The doctor could not join: ${await joined.text()}`);

  const staff = (await (await admin.get("/api/v1/staff")).json()).data as {
    id: string;
    email: string;
  }[];
  const account = staff.find((member) => member.email === email);
  if (!account) throw new Error("The doctor who joined is not on the staff list.");

  const profile = await admin.post("/api/v1/doctors", {
    data: {
      first_name: "Meera",
      last_name: `Iyer ${stamp}`,
      speciality: "General medicine",
      slot_duration_minutes: 15,
      room: "2",
      user_id: account.id,
    },
  });
  if (!profile.ok()) throw new Error(`Could not add the doctor: ${await profile.text()}`);
  const made = (await profile.json()).data;
  const hours = await admin.put(`/api/v1/doctors/${made.id}/schedule`, {
    data: { blocks: MORNINGS },
  });
  if (!hours.ok()) throw new Error(`Could not set the doctor's hours: ${await hours.text()}`);

  await writeFile(DOCTOR_STATE, JSON.stringify(await doctor.storageState(), null, 2));
  await writeFile(
    DOCTOR_PROFILE,
    JSON.stringify({ id: made.id, display_name: made.display_name }, null, 2),
  );
  await doctor.dispose();
  await admin.dispose();
  return email;
}

export default async function globalSetup(config: FullConfig) {
  const baseURL = config.projects[0]?.use.baseURL ?? "http://localhost:3000";
  const accounts = {
    [SHARED_STATE]: await register(baseURL, SHARED_STATE),
    [EMPTY_STATE]: await register(baseURL, EMPTY_STATE),
  };
  accounts[DOCTOR_STATE] = await joinAsDoctor(baseURL);
  await writeFile(ACCOUNTS, JSON.stringify(accounts, null, 2));
}
