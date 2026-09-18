import { expect, test } from "./fixtures";
import { DOCTOR_STATE, SHARED_STATE } from "./state";
import { asTheDesk, inTheRoom } from "./visits";

/**
 * Notes are written by a doctor, so these run signed in as the one global
 * setup joined to the shared clinic. The administrator's session does the
 * desk's part: registering the patient and putting them in the line.
 */
test.use({ storageState: DOCTOR_STATE });

test("a doctor writes up a visit, finishes it, and adds to it afterwards", async ({
  page,
  browser,
  playwright,
  baseURL,
  tag,
}) => {
  const deskContext = await browser.newContext({ storageState: SHARED_STATE });
  const deskPage = await deskContext.newPage();
  const desk = await asTheDesk(playwright, baseURL);
  const { patient, doctor } = await inTheRoom(
    desk,
    deskPage,
    "Fever since last night",
    `Notes${tag}`,
  );
  await desk.post(`/api/v1/patients/${patient.id}/allergies`, {
    data: { substance: "Penicillin", reaction: "Hives", severity: "severe" },
  });

  await page.goto(`/queue?doctor=${doctor.id}`);
  const lane = page.getByRole("region", { name: doctor.display_name });
  await lane.getByRole("button", { name: "Write notes" }).click();

  await expect(page).toHaveURL(/\/consultations\/[0-9a-f-]+$/);
  await expect(page.getByRole("heading", { name: `Asha Notes${tag}` })).toBeVisible();
  await expect(page.getByRole("note", { name: "Allergies" })).toContainText("Penicillin");
  // The desk's reason is where the complaint starts.
  await expect(page.getByLabel("Complaint")).toHaveValue("Fever since last night");

  await page.getByLabel("History").fill("Three days, worse at night. No rash.");
  await expect(page.getByRole("status")).toContainText("Saved at");

  // What was typed survives a reload, because it was saved as it went.
  await page.reload();
  await expect(page.getByLabel("History")).toHaveValue("Three days, worse at night. No rash.");

  const diagnosis = page.getByLabel("Diagnosis", { exact: true });
  await diagnosis.fill("Viral fever");
  await diagnosis.press("Enter");
  await diagnosis.fill("Dehydration");
  await page.getByRole("button", { name: "Add", exact: true }).click();
  await page.getByRole("button", { name: "Make Dehydration the main diagnosis" }).click();
  await expect(
    page.getByRole("button", { name: "Dehydration is the main diagnosis" }),
  ).toBeVisible();
  // Listing it twice is caught before it goes anywhere.
  await diagnosis.fill("viral fever");
  await diagnosis.press("Enter");
  await expect(page.getByText("Viral fever is already listed.")).toBeVisible();
  await diagnosis.fill("");

  await page.getByLabel("Advice and plan").fill("Fluids, paracetamol for the fever.");
  await page.getByRole("button", { name: "1 week" }).click();
  await expect(page.getByText(/Come back on .+, in 1 week\./)).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Saved at");

  await page.getByRole("button", { name: "Finish visit" }).click();
  await page.getByRole("button", { name: "Yes, finish" }).click();

  await expect(page.getByText(/Finished .+ Anything new goes underneath/)).toBeVisible();
  await expect(page.getByLabel("History")).toHaveCount(0);
  await expect(page.getByText("Three days, worse at night. No rash.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Book the follow-up" })).toBeVisible();

  await page.getByRole("button", { name: "Add an addendum" }).click();
  await page.getByLabel("Addendum", { exact: true }).fill("Blood count came back normal.");
  await page.getByRole("button", { name: "Add it" }).click();
  await expect(page.getByText("Blood count came back normal.")).toBeVisible();
  await expect(page.getByText(/Meera Iyer, /)).toBeVisible();

  // Finishing the notes saw the patient out of the room.
  await page.goto(`/queue?doctor=${doctor.id}`);
  await expect(lane.getByText("With the doctor", { exact: true })).toHaveCount(0);
  await lane.getByText(/^Done today/).click();
  await expect(lane.getByRole("link", { name: "Notes" }).first()).toBeVisible();

  await deskContext.close();
  await desk.dispose();
});

test("empty notes are not finished, and the patient stays in the room", async ({
  page,
  browser,
  playwright,
  baseURL,
  tag,
}) => {
  const deskContext = await browser.newContext({ storageState: SHARED_STATE });
  const desk = await asTheDesk(playwright, baseURL);
  const { entry, doctor } = await inTheRoom(
    desk,
    await deskContext.newPage(),
    "",
    `Empty${tag}`,
  );
  const opened = await page.request.post("/api/v1/consultations", {
    data: { queue_entry_id: entry.id },
  });
  const notes = (await opened.json()).data;

  await page.goto(`/consultations/${notes.id}`);
  await page.getByRole("button", { name: "Finish visit" }).click();
  await page.getByRole("button", { name: "Yes, finish" }).click();

  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Write the complaint or a diagnosis before finishing." }),
  ).toBeVisible();
  await expect(page.getByLabel("Complaint")).toBeEditable();
  await page.goto(`/queue?doctor=${doctor.id}`);
  await expect(
    page
      .getByRole("region", { name: doctor.display_name })
      .getByRole("button", { name: "Open notes" }),
  ).toBeVisible();

  await deskContext.close();
  await desk.dispose();
});

test("a tab that falls behind stops saving rather than overwriting the other", async ({
  page,
  context,
  browser,
  playwright,
  baseURL,
  tag,
}) => {
  const deskContext = await browser.newContext({ storageState: SHARED_STATE });
  const desk = await asTheDesk(playwright, baseURL);
  const { entry } = await inTheRoom(desk, await deskContext.newPage(), "Cough", `Tabs${tag}`);
  const notes = (
    await (
      await page.request.post("/api/v1/consultations", { data: { queue_entry_id: entry.id } })
    ).json()
  ).data;

  const other = await context.newPage();
  await page.goto(`/consultations/${notes.id}`);
  await other.goto(`/consultations/${notes.id}`);

  await page.getByLabel("Examination").fill("Chest clear, from the first tab.");
  await expect(page.getByRole("status")).toContainText("Saved at");

  await other.getByLabel("Examination").fill("Written in the second tab.");
  await expect(other.getByText(/changed in another window/)).toBeVisible();
  await expect(other.getByRole("button", { name: "Finish visit" })).toBeDisabled();

  await other.getByRole("button", { name: "Load the latest" }).click();
  await expect(other.getByLabel("Examination")).toHaveValue("Chest clear, from the first tab.");
  // And it saves again from there.
  await other.getByLabel("Advice and plan").fill("Steam inhalation.");
  await expect(other.getByRole("status")).toContainText("Saved at");

  await deskContext.close();
  await desk.dispose();
});

test.describe("as the clinic admin", () => {
  test.use({ storageState: SHARED_STATE });

  test("reads a doctor's notes but has no way to change them", async ({
    page,
    browser,
    tag,
  }) => {
    const doctorContext = await browser.newContext({ storageState: DOCTOR_STATE });
    const doctorApi = doctorContext.request;
    const { entry, doctor } = await inTheRoom(page.request, page, "Knee pain", `Admin${tag}`);
    const notes = (
      await (
        await doctorApi.post("/api/v1/consultations", { data: { queue_entry_id: entry.id } })
      ).json()
    ).data;
    const saved = await doctorApi.patch(`/api/v1/consultations/${notes.id}`, {
      data: { version: notes.version, diagnoses: [{ label: "Osteoarthritis" }] },
    });
    const finished = await doctorApi.post(`/api/v1/consultations/${notes.id}/complete`, {
      data: { version: (await saved.json()).data.version },
    });
    expect(finished.ok(), await finished.text()).toBeTruthy();

    await page.goto(`/consultations?doctor=${doctor.id}`);
    await page.getByRole("link", { name: new RegExp(`Asha Admin${tag}`) }).click();

    await expect(page.getByText("Osteoarthritis")).toBeVisible();
    await expect(page.getByRole("textbox")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Finish visit" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Add an addendum" })).toHaveCount(0);

    // The notes are on the patient's record too.
    await page.getByRole("link", { name: `Asha Admin${tag}` }).click();
    await expect(page.getByRole("region", { name: "Visit notes" })).toContainText(
      "Osteoarthritis",
    );

    await doctorContext.close();
  });
});
