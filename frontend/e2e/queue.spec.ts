import type { Page } from "@playwright/test";
import { addBooking, addDoctor, addPatient, bookableDoctor, expect, test } from "./fixtures";

/** The clinic's today, which is the queue's, whatever this machine thinks. */
async function clinicToday(page: Page): Promise<string> {
  const answer = await page.request.get("/api/v1/queue");
  expect(answer.ok(), await answer.text()).toBeTruthy();
  return (await answer.json()).data.date;
}

async function walkIn(page: Page, patientId: string, doctorId: string) {
  const made = await page.request.post("/api/v1/queue/walk-in", {
    data: { patient_id: patientId, doctor_id: doctorId },
  });
  expect(made.ok(), await made.text()).toBeTruthy();
  return (await made.json()).data;
}

/**
 * Somebody booked for later today, so there is something to check in.
 *
 * The doctor sits all day in five-minute appointments, so there is a slot
 * still ahead at any hour but the last few minutes before midnight, when
 * the test says so and stands down rather than failing.
 */
async function bookedLaterToday(page: Page, doctorName: string, patientName: string) {
  const doctor = await addDoctor(page, { last_name: doctorName, slot_duration_minutes: 5 });
  const hours = await page.request.put(`/api/v1/doctors/${doctor.id}/schedule`, {
    data: {
      blocks: Array.from({ length: 7 }, (_, day) => ({
        day_of_week: day,
        start_time: "00:00",
        end_time: "23:55",
      })),
    },
  });
  expect(hours.ok(), await hours.text()).toBeTruthy();

  const today = await clinicToday(page);
  const plan = await page.request.get(
    `/api/v1/doctors/${doctor.id}/availability?date=${today}`,
  );
  const free = (await plan.json()).data.slots.find(
    (slot: { state: string }) => slot.state === "free",
  );
  test.skip(!free, "No appointment left today to book into.");

  const patient = await addPatient(page, { last_name: patientName });
  const booking = await addBooking(page, {
    patient_id: patient.id,
    doctor_id: doctor.id,
    date: today,
    start_time: free.start_time.slice(0, 5),
  });
  return { doctor, patient, booking };
}

test("a walk-in is added, called, seen and finished", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { last_name: `Walk${tag}`, room: "4" });
  await addPatient(page, { last_name: `Walker${tag}` });

  await page.goto(`/queue?doctor=${doctor.id}`);
  await page.getByRole("button", { name: "Add a walk-in" }).click();
  await page.getByLabel("Find the patient").fill(`Walker${tag}`);
  await page.getByRole("button", { name: new RegExp(`Asha Walker${tag}`) }).click();
  await page
    .getByRole("region", { name: "Add a walk-in" })
    .getByLabel("Doctor")
    .selectOption(doctor.id);
  await page.getByLabel(/Why they came/).fill("Fever since last night");
  await page.getByRole("button", { name: "Add to the queue" }).click();

  await expect(page.getByRole("status")).toContainText(
    `Asha is token 1 with ${doctor.display_name}.`,
  );
  const lane = page.getByRole("region", { name: doctor.display_name });
  await expect(lane.getByText("Walk-in, Fever since last night")).toBeVisible();

  await lane.getByRole("button", { name: "Call token 1" }).click();
  await expect(lane.getByText("Called", { exact: true })).toBeVisible();
  // While somebody is called, nobody else can be.
  await expect(lane.getByRole("button", { name: /Call token/ })).toHaveCount(0);

  await lane.getByRole("button", { name: "They are in" }).click();
  await expect(lane.getByText("With the doctor", { exact: true })).toBeVisible();

  await lane.getByRole("button", { name: "Finish" }).click();
  await expect(lane.getByText("Done today (1 seen)")).toBeVisible();
  await expect(lane.getByText(/^Nobody is waiting/)).toBeVisible();
});

test("a booked patient is checked in from the list of who is still to arrive", async ({
  page,
  tag,
}) => {
  const { doctor, booking } = await bookedLaterToday(page, `Arrive${tag}`, `Early${tag}`);

  await page.goto(`/queue?doctor=${doctor.id}`);
  const lane = page.getByRole("region", { name: doctor.display_name });
  await lane.getByRole("button", { name: `Check in Asha Early${tag}` }).click();

  await expect(page.getByRole("status")).toContainText("Asha is token 1");
  await expect(lane.getByText("Still to arrive")).toHaveCount(0);
  await expect(lane.getByRole("link", { name: `Asha Early${tag}` })).toBeVisible();

  // The appointment knows where they are.
  await page.goto(`/appointments/${booking.id}`);
  await expect(
    page.getByText(`Checked in and waiting for ${doctor.display_name}.`),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel appointment" })).toHaveCount(0);
  await expect(page.getByRole("listitem").filter({ hasText: "Checked in" })).toBeVisible();
});

test("checking in from the appointment, then taking it back", async ({ page, tag }) => {
  const { doctor, booking } = await bookedLaterToday(page, `Undo${tag}`, `Mistake${tag}`);

  await page.goto(`/appointments/${booking.id}`);
  await page.getByRole("button", { name: "Check in" }).click();
  await expect(
    page.getByText(`Checked in and waiting for ${doctor.display_name}.`),
  ).toBeVisible();

  await page.getByRole("link", { name: "Open the queue" }).click();
  await expect(page).toHaveURL(new RegExp(`/queue\\?doctor=${doctor.id}`));
  const lane = page.getByRole("region", { name: doctor.display_name });
  await lane.getByRole("button", { name: "More for token 1" }).click();
  await page.getByRole("menuitem", { name: "Undo check-in" }).click();

  await expect(page.getByRole("status")).toContainText("Check-in for Asha taken back.");
  await expect(lane.getByRole("button", { name: `Check in Asha Mistake${tag}` })).toBeVisible();

  await page.goto(`/appointments/${booking.id}`);
  await expect(page.getByRole("button", { name: "Check in" })).toBeVisible();
  await expect(
    page.getByRole("listitem").filter({ hasText: "Check-in taken back" }),
  ).toBeVisible();
});

test("the undo on the notice takes a walk-in straight back out", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { last_name: `Oops${tag}` });
  await addPatient(page, { last_name: `Oops${tag}` });

  await page.goto(`/queue?doctor=${doctor.id}`);
  await page.getByRole("button", { name: "Add a walk-in" }).click();
  await page.getByLabel("Find the patient").fill(`Oops${tag}`);
  await page.getByRole("button", { name: new RegExp(`Asha Oops${tag}`) }).click();
  await page
    .getByRole("region", { name: "Add a walk-in" })
    .getByLabel("Doctor")
    .selectOption(doctor.id);
  await page.getByRole("button", { name: "Add to the queue" }).click();

  const notice = page.getByRole("status");
  await expect(notice).toContainText("token 1");
  await notice.getByRole("button", { name: "Undo" }).click();

  await expect(notice).toContainText("Check-in taken back.");
  const lane = page.getByRole("region", { name: doctor.display_name });
  await expect(lane.getByText(/^Nobody is waiting/)).toBeVisible();
});

test("not here when called, back in the line, and then gone", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { last_name: `Skip${tag}` });
  const asha = await addPatient(page, { last_name: `First${tag}` });
  const bina = await addPatient(page, { first_name: "Bina", last_name: `Second${tag}` });
  await walkIn(page, asha.id, doctor.id);
  await walkIn(page, bina.id, doctor.id);

  await page.goto(`/queue?doctor=${doctor.id}`);
  const lane = page.getByRole("region", { name: doctor.display_name });
  await lane.getByRole("button", { name: "Call token 1" }).click();
  await lane.getByRole("button", { name: "Not here" }).click();

  await expect(lane.getByText("Missed their call")).toBeVisible();
  await expect(lane.getByRole("button", { name: "Call token 2" })).toBeVisible();

  await lane.getByRole("button", { name: "Back in the line" }).click();
  // Back to their own number, which is ahead of the next arrival.
  await expect(lane.getByRole("button", { name: "Call token 1" })).toBeVisible();

  await lane.getByRole("button", { name: "More for token 1" }).click();
  await page.getByRole("menuitem", { name: "They left" }).click();
  await lane.getByRole("button", { name: "Keep them" }).click();
  await expect(lane.getByRole("button", { name: "Call token 1" })).toBeVisible();

  await lane.getByRole("button", { name: "More for token 1" }).click();
  await page.getByRole("menuitem", { name: "They left" }).click();
  await lane.getByRole("button", { name: "Yes, they left" }).click();
  await expect(lane.getByRole("button", { name: "Call token 2" })).toBeVisible();
  await expect(lane.getByText("Done today (1 left)")).toBeVisible();
});

test("marking somebody urgent puts them at the front", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { last_name: `Urgent${tag}` });
  const asha = await addPatient(page, { last_name: `Calm${tag}` });
  const bina = await addPatient(page, { first_name: "Bina", last_name: `Chest${tag}` });
  await walkIn(page, asha.id, doctor.id);
  await walkIn(page, bina.id, doctor.id);

  await page.goto(`/queue?doctor=${doctor.id}`);
  const lane = page.getByRole("region", { name: doctor.display_name });
  await expect(lane.getByRole("button", { name: "Call token 1" })).toBeVisible();

  const menu = lane.getByRole("button", { name: "More for token 2" });
  await menu.focus();
  await page.keyboard.press("Enter");
  // The menu opens onto its first item and the arrows move through it.
  await expect(page.getByRole("menuitem").first()).toBeFocused();
  await page.getByRole("menuitem", { name: "Mark urgent" }).click();

  await expect(lane.getByRole("button", { name: "Call token 2" })).toBeVisible();
  await expect(lane.getByText("Urgent", { exact: true })).toBeVisible();
});

test("somebody already in one line is not put in another", async ({ page, tag }) => {
  const first = await bookableDoctor(page, { last_name: `One${tag}` });
  const second = await bookableDoctor(page, { last_name: `Two${tag}` });
  const asha = await addPatient(page, { last_name: `Twice${tag}` });
  await walkIn(page, asha.id, first.id);

  await page.goto(`/queue?doctor=${second.id}`);
  await page.getByRole("button", { name: "Add a walk-in" }).click();
  await page.getByLabel("Find the patient").fill(`Twice${tag}`);
  await page.getByRole("button", { name: new RegExp(`Asha Twice${tag}`) }).click();
  await page
    .getByRole("region", { name: "Add a walk-in" })
    .getByLabel("Doctor")
    .selectOption(second.id);
  await page.getByRole("button", { name: "Add to the queue" }).click();

  await expect(
    page.getByText(`Asha is already in the queue for ${first.display_name}, token 1.`),
  ).toBeVisible();
});

test("the walk-in form asks for the patient before sending anything", async ({ page }) => {
  await page.goto("/queue");
  await page.getByRole("button", { name: "Add a walk-in" }).click();
  await page.getByRole("button", { name: "Add to the queue" }).click();

  await expect(page.getByText("Find the patient first.")).toBeVisible();
});

test("the waiting-room screen shows numbers and rooms, never names", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { last_name: `Board${tag}`, room: "7" });
  const asha = await addPatient(page, { last_name: `Private${tag}` });
  const bina = await addPatient(page, { first_name: "Bina", last_name: `Hidden${tag}` });
  const called = await walkIn(page, asha.id, doctor.id);
  await walkIn(page, bina.id, doctor.id);
  const answer = await page.request.post(`/api/v1/queue/${called.id}/call`);
  expect(answer.ok(), await answer.text()).toBeTruthy();

  await page.goto(`/queue/board?doctor=${doctor.id}`);
  const column = page.getByRole("region", { name: doctor.display_name });
  await expect(column.getByText("Room 7")).toBeVisible();
  await expect(column.getByText("Please come in")).toBeVisible();
  await expect(column.getByRole("listitem")).toHaveText(["Token 2"]);
  await expect(page.getByText(`Private${tag}`)).toHaveCount(0);
  await expect(page.getByText(`Hidden${tag}`)).toHaveCount(0);
  // No rail and no menus: this screen is for the room, not the desk.
  await expect(page.getByRole("link", { name: "Appointments" })).toHaveCount(0);
});
