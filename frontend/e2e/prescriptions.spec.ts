import { expect, test } from "./fixtures";
import { DOCTOR_STATE, SHARED_STATE } from "./state";
import { asTheDesk, inTheRoom } from "./visits";

/**
 * The doctor writes the prescription with the notes; the desk prints it.
 * Runs as the doctor global setup joined, with the administrator's session
 * standing in for the desk.
 */
test.use({ storageState: DOCTOR_STATE });

test("a prescription is picked from the list, issued with the visit, and printed at the desk", async ({
  page,
  browser,
  playwright,
  baseURL,
  tag,
}) => {
  const deskContext = await browser.newContext({ storageState: SHARED_STATE });
  const deskPage = await deskContext.newPage();
  const desk = await asTheDesk(playwright, baseURL);
  const { doctor } = await inTheRoom(desk, deskPage, "Fever", `Rx${tag}`);

  await page.goto(`/queue?doctor=${doctor.id}`);
  await page
    .getByRole("region", { name: doctor.display_name })
    .getByRole("button", { name: "Write notes" })
    .click();
  await expect(page).toHaveURL(/\/consultations\//);

  await page.getByRole("button", { name: "Add a medicine" }).click();
  const first = page.getByRole("combobox", { name: "Medicine 1" });
  await first.pressSequentially("parace", { delay: 40 });
  const options = page.getByRole("listbox").getByRole("option");
  await expect(options.first()).toContainText("Paracetamol");
  // Enter takes the top match, with the pointer wherever it happens to rest.
  await first.press("Enter");
  await expect(first).toHaveValue("Paracetamol");
  await expect(page.getByLabel("Form and strength").first()).toHaveValue(/^Tablet /);
  await page.getByRole("button", { name: "1-0-1" }).first().click();
  await page.getByLabel("When").first().selectOption("after_food");
  await page.getByLabel("For how many days").first().fill("3");

  // Something not on the list is typed as it is.
  await page.getByRole("button", { name: "Add another medicine" }).click();
  await page.getByRole("combobox", { name: "Medicine 2" }).fill(`Throat spray ${tag}`);
  await page
    .getByRole("list", { name: "Medicines" })
    .getByRole("textbox", { name: "Dose" })
    .nth(1)
    .fill("2 puffs");
  await page.getByLabel("Advice printed on the prescription").fill("Plenty of fluids.");
  await expect(page.getByRole("status")).toContainText("Saved at");

  await page.getByRole("button", { name: "Finish visit" }).click();
  await page.getByRole("button", { name: "Yes, finish" }).click();
  const heading = page.getByRole("heading", { name: /^Prescription RX-\d{6}$/ });
  await expect(heading).toBeVisible();
  const number = (await heading.innerText()).split(" ").pop()!;

  const print = page.getByRole("link", { name: `Print ${number}` });
  const pdf = await page.request.get((await print.getAttribute("href"))!);
  expect(pdf.headers()["content-type"]).toBe("application/pdf");
  expect((await pdf.body()).subarray(0, 4).toString()).toBe("%PDF");

  // The desk finds it where the patient left the queue.
  await deskPage.goto(`/queue?doctor=${doctor.id}`);
  const lane = deskPage.getByRole("region", { name: doctor.display_name });
  await lane.getByText(/^Done today/).click();
  await lane.getByRole("link", { name: "Prescription" }).first().click();
  const paper = deskPage.getByRole("article", { name: `Prescription ${number}` });
  await expect(paper).toContainText("Paracetamol");
  await expect(paper).toContainText(`Throat spray ${tag}`);
  await expect(paper).toContainText("Plenty of fluids.");
  await expect(deskPage.getByRole("link", { name: `Print ${number}` })).toBeVisible();

  await deskContext.close();
  await desk.dispose();
});

test("a medicine without a dose keeps the visit open and says which", async ({
  page,
  browser,
  playwright,
  baseURL,
  tag,
}) => {
  const deskContext = await browser.newContext({ storageState: SHARED_STATE });
  const desk = await asTheDesk(playwright, baseURL);
  const { entry } = await inTheRoom(desk, await deskContext.newPage(), "Cough", `NoDose${tag}`);
  const notes = (
    await (
      await page.request.post("/api/v1/consultations", { data: { queue_entry_id: entry.id } })
    ).json()
  ).data;

  await page.goto(`/consultations/${notes.id}`);
  await page.getByRole("button", { name: "Add a medicine" }).click();
  await page.getByRole("combobox", { name: "Medicine 1" }).fill("Cough syrup");
  await expect(page.getByRole("status")).toContainText("Saved at");
  await page.getByRole("button", { name: "Finish visit" }).click();
  await page.getByRole("button", { name: "Yes, finish" }).click();

  await expect(
    page
      .getByRole("alert")
      .filter({ hasText: "Medicine 1 on the prescription has no dose yet." }),
  ).toBeVisible();
  await expect(page.getByText("Say how much to take.")).toBeVisible();
  await expect(page.getByRole("button", { name: "Finish visit" })).toBeEnabled();

  await deskContext.close();
  await desk.dispose();
});

test("a correction replaces the prescription and the old copy says not to dispense", async ({
  page,
  browser,
  playwright,
  baseURL,
  tag,
}) => {
  const deskContext = await browser.newContext({ storageState: SHARED_STATE });
  const desk = await asTheDesk(playwright, baseURL);
  const { entry } = await inTheRoom(desk, await deskContext.newPage(), "Rash", `Fix${tag}`);
  const opened = await (
    await page.request.post("/api/v1/consultations", { data: { queue_entry_id: entry.id } })
  ).json();
  const written = await (
    await page.request.patch(`/api/v1/consultations/${opened.data.id}`, {
      data: {
        version: opened.data.version,
        medicines: [
          { medicine_name: "Cetirizine", presentation: "Tablet 10 mg", dose: "0-0-1" },
        ],
      },
    })
  ).json();
  const done = await (
    await page.request.post(`/api/v1/consultations/${opened.data.id}/complete`, {
      data: { version: written.data.version },
    })
  ).json();
  const original = done.data.prescriptions[0];

  await page.goto(`/consultations/${opened.data.id}`);
  await page.getByRole("button", { name: "Correct it" }).click();
  await page.getByRole("button", { name: "Issue the correction" }).click();
  await expect(page.getByText("Say what was wrong with the original.")).toBeVisible();
  await page
    .getByRole("list", { name: "Medicines" })
    .getByRole("textbox", { name: "Dose" })
    .first()
    .fill("1-0-1");
  await page.getByLabel("What was wrong with the original").fill("Dose written wrongly");
  await page.getByRole("button", { name: "Issue the correction" }).click();

  await expect(
    page.getByText(`in place of ${original.number}: Dose written wrongly`),
  ).toBeVisible();
  await page.getByRole("link", { name: original.number }).click();
  await expect(
    page.getByRole("alert").filter({ hasText: "Do not dispense from this copy." }),
  ).toBeVisible();

  await deskContext.close();
  await desk.dispose();
});
