import { addPatient, expect, test } from "./fixtures";
import { DOCTOR_STATE, SHARED_STATE } from "./state";
import { asTheDesk, inTheRoom, profile } from "./visits";

/** The first page after signing in, for the desk and for a doctor. */
test.describe("for the desk", () => {
  test.use({ storageState: SHARED_STATE });

  test("the clinic's day shows who is waiting, and whose vitals are still to take", async ({
    page,
    tag,
  }) => {
    const doctor = profile();
    const patient = await addPatient(page, { last_name: `Today${tag}` });
    const placed = await page.request.post("/api/v1/queue/walk-in", {
      // Urgent, so it heads the list however many earlier tests left waiting.
      data: {
        patient_id: patient.id,
        doctor_id: doctor.id,
        reason: "Earache",
        priority: "urgent",
      },
    });
    expect(placed.ok(), await placed.text()).toBeTruthy();
    const entry = (await placed.json()).data;

    await page.goto("/dashboard");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(
      /^Good (morning|afternoon|evening), /,
    );
    const doctors = page.getByRole("region", { name: "Doctors today" });
    await expect(doctors.getByRole("link", { name: doctor.display_name })).toBeVisible();

    const waiting = page.getByRole("region", { name: "In the waiting room" });
    const row = waiting.getByRole("listitem").filter({ hasText: `Today${tag}` });
    await expect(row).toContainText("Earache");
    await expect(row).toContainText("No vitals yet");

    const taken = await page.request.post("/api/v1/vitals", {
      data: { queue_entry_id: entry.id, systolic_mmhg: 152, diastolic_mmhg: 96 },
    });
    expect(taken.ok(), await taken.text()).toBeTruthy();
    await page.reload();
    await expect(row).toContainText(/BP\s*152\/96\s*High/);

    // The patient's name goes to their doctor's line in the queue.
    await row.getByRole("link", { name: patient.full_name }).click();
    await expect(page).toHaveURL(new RegExp(`/queue\\?doctor=${doctor.id}$`));

    await page.request.post(`/api/v1/queue/${entry.id}/no-show`);
  });
});

test.describe("for a doctor", () => {
  test.use({ storageState: DOCTOR_STATE });

  test("their own day shows who is with them, and opens the notes from there", async ({
    page,
    browser,
    playwright,
    baseURL,
    tag,
  }) => {
    const deskContext = await browser.newContext({ storageState: SHARED_STATE });
    const desk = await asTheDesk(playwright, baseURL);
    const { patient } = await inTheRoom(
      desk,
      await deskContext.newPage(),
      "Dizzy spells",
      `Mine${tag}`,
    );

    await page.goto("/dashboard");
    await expect(page.getByText(/^Your day for /)).toBeVisible();
    // Only their own line, never the clinic's.
    await expect(page.getByRole("region", { name: "Doctors today" })).toHaveCount(0);

    const inRoom = page.getByRole("region", { name: "With you now" });
    await expect(inRoom).toContainText(patient.full_name);
    await inRoom.getByRole("button", { name: /notes$/ }).click();
    await expect(page).toHaveURL(/\/consultations\/[0-9a-f-]+$/);
    await expect(page.getByRole("heading", { level: 1 })).toContainText(patient.full_name);

    await deskContext.close();
    await desk.dispose();
  });
});
