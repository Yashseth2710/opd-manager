import { addPatient, expect, test } from "./fixtures";
import { DOCTOR_STATE, SHARED_STATE } from "./state";
import { asTheDesk, inTheRoom, profile } from "./visits";

/**
 * Vital signs: taken at the desk while the patient waits, read and put right
 * by the doctor in the room, and kept on the patient's record.
 */
test.describe("at the desk", () => {
  test.use({ storageState: SHARED_STATE });

  test("vitals are taken, checked for slips, shown on the line, and taken back", async ({
    page,
    tag,
  }) => {
    const doctor = profile();
    const patient = await addPatient(page, { last_name: `Vitals${tag}` });
    const placed = await page.request.post("/api/v1/queue/walk-in", {
      data: { patient_id: patient.id, doctor_id: doctor.id, reason: "Giddiness" },
    });
    expect(placed.ok(), await placed.text()).toBeTruthy();

    await page.goto(`/queue?doctor=${doctor.id}`);
    const lane = page.getByRole("region", { name: doctor.display_name });
    const row = lane.getByRole("listitem").filter({ hasText: `Vitals${tag}` });
    await row.getByRole("button", { name: /^Take vitals for / }).click();

    const form = row.getByRole("region", { name: /^Take vitals for / });
    await expect(form.getByLabel("Upper number (systolic)")).toBeFocused();

    // Nothing typed is refused before anything is sent.
    await form.getByRole("button", { name: "Save vitals" }).click();
    await expect(form.getByRole("alert")).toHaveText("Enter at least one reading.");

    await form.getByLabel("Upper number (systolic)").fill("150");
    await form.getByLabel("Temperature", { exact: true }).fill("37");
    await form.getByLabel("Blood sugar").fill("182");
    await form.getByRole("button", { name: "Save vitals" }).click();
    await expect(form.getByText("Enter the lower number as well.")).toBeVisible();
    await expect(form.getByText(/Temperature has to be between 86 and 113 °F/)).toBeVisible();
    await expect(form.getByText("Say when the sugar was taken.")).toBeVisible();

    await form.getByLabel("Lower number (diastolic)").fill("95");
    await form.getByLabel("Temperature", { exact: true }).fill("101");
    await form.getByLabel("Random").check();
    await form.getByRole("button", { name: "Save vitals" }).click();

    await expect(
      page.getByRole("status").filter({ hasText: "Vitals taken for" }),
    ).toBeVisible();
    await expect(form).toHaveCount(0);
    // Out of range is marked, in words for anyone not seeing the colour.
    await expect(row).toContainText(/BP\s*150\/95\s*High/);
    await expect(row).toContainText(/Temp\s*101\.0 °F\s*High/);

    // Opened again, it holds what was saved, and converts on switching unit.
    await row.getByRole("button", { name: /^Correct vitals for / }).click();
    const again = row.getByRole("region", { name: /^Correct vitals for / });
    await expect(again.getByLabel("Upper number (systolic)")).toHaveValue("150");
    await expect(again.getByLabel("Temperature", { exact: true })).toHaveValue("101");
    await again.getByRole("button", { name: "°C" }).click();
    await expect(again.getByLabel("Temperature", { exact: true })).toHaveValue("38.3");
    await again.getByRole("button", { name: "°F" }).click();
    await expect(again.getByLabel("Temperature", { exact: true })).toHaveValue("101");

    // Taken for the wrong person: they come off again.
    await again.getByRole("button", { name: "Remove these readings" }).click();
    await again.getByRole("button", { name: "Yes, remove them" }).click();
    await expect(page.getByRole("status").filter({ hasText: "removed" })).toBeVisible();
    await expect(row.getByRole("button", { name: /^Take vitals for / })).toBeVisible();
    await expect(row).not.toContainText(/BP\s*150\/95/);
  });
});

test.describe("in the room", () => {
  test.use({ storageState: DOCTOR_STATE });

  test("the doctor reads them with the notes, corrects them, and they stay once finished", async ({
    page,
    browser,
    playwright,
    baseURL,
    tag,
  }) => {
    const deskContext = await browser.newContext({ storageState: SHARED_STATE });
    const desk = await asTheDesk(playwright, baseURL);
    const { entry, patient } = await inTheRoom(
      desk,
      await deskContext.newPage(),
      "Breathless",
      `Room${tag}`,
    );
    const taken = await desk.post("/api/v1/vitals", {
      data: { queue_entry_id: entry.id, spo2_percent: 91, pulse_bpm: 88 },
    });
    expect(taken.ok(), await taken.text()).toBeTruthy();

    const opened = await page.request.post("/api/v1/consultations", {
      data: { queue_entry_id: entry.id },
    });
    const notes = (await opened.json()).data;
    await page.goto(`/consultations/${notes.id}`);

    const vitals = page.getByRole("region", { name: "Vitals" });
    await expect(vitals).toContainText(/SpO₂\s*91%\s*Low/);
    await expect(vitals).toContainText(/Pulse\s*88/);

    await vitals.getByRole("button", { name: "Correct" }).click();
    await vitals.getByLabel("Oxygen (SpO₂)").fill("94");
    await vitals.getByRole("button", { name: "Save the correction" }).click();
    await expect(vitals.getByRole("status")).toHaveText(/corrected\.$/);
    await expect(vitals).toContainText(/SpO₂\s*94%\s*Low/);
    await expect(vitals).toContainText("corrected by");

    await page.getByLabel("Complaint").fill("Breathless on stairs");
    await expect(page.getByRole("status").filter({ hasText: "Saved at" })).toBeVisible();
    await page.getByRole("button", { name: "Finish visit" }).click();
    await page.getByRole("button", { name: "Yes, finish" }).click();
    await expect(page.getByText("Finished", { exact: true })).toBeVisible();
    await expect(vitals).toContainText(/SpO₂\s*94%/);
    await expect(vitals.getByRole("button", { name: "Correct" })).toHaveCount(0);

    // And on the patient's record, as a row of the history.
    await page.goto(`/patients/${patient.id}`);
    const history = page.getByRole("table", { name: "Vital signs, newest first" });
    await expect(history.getByRole("row")).toHaveCount(2);
    await expect(history).toContainText("94");

    await deskContext.close();
    await desk.dispose();
  });
});
