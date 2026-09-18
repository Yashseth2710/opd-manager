import { readFileSync } from "node:fs";
import type { APIRequestContext, Page } from "@playwright/test";
import { addPatient, expect } from "./fixtures";
import { DOCTOR_PROFILE, SHARED_STATE } from "./state";

/** The doctor global setup joined to the shared clinic, and a patient with them. */
export type Profile = { id: string; display_name: string };

export function profile(): Profile {
  return JSON.parse(readFileSync(DOCTOR_PROFILE, "utf8")) as Profile;
}

export async function asTheDesk(
  playwright: { request: { newContext: (options: object) => Promise<APIRequestContext> } },
  baseURL: string | undefined,
) {
  return playwright.request.newContext({ baseURL, storageState: SHARED_STATE });
}

/**
 * Somebody with the doctor now. Whoever was in the room before is finished
 * first, since the tests share the doctor and a doctor sees one at a time.
 */
export async function inTheRoom(
  desk: APIRequestContext,
  deskPage: Page,
  reason: string,
  name: string,
) {
  const doctor = profile();
  const queue = (await (await desk.get(`/api/v1/queue?doctor_id=${doctor.id}`)).json()).data;
  const lane = queue.lanes.find((each: { doctor: Profile }) => each.doctor.id === doctor.id);
  if (lane?.now_seeing) await desk.post(`/api/v1/queue/${lane.now_seeing.id}/complete`);

  const patient = await addPatient(deskPage, { last_name: name });
  const placed = await desk.post("/api/v1/queue/walk-in", {
    data: { patient_id: patient.id, doctor_id: doctor.id, reason },
  });
  expect(placed.ok(), await placed.text()).toBeTruthy();
  const entry = (await placed.json()).data;
  const started = await desk.post(`/api/v1/queue/${entry.id}/start`);
  expect(started.ok(), await started.text()).toBeTruthy();
  return { patient, entry, doctor };
}
