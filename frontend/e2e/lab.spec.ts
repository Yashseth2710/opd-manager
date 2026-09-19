import { expect, test } from "./fixtures";
import { DOCTOR_STATE, SHARED_STATE } from "./state";
import { asTheDesk, inTheRoom } from "./visits";

/**
 * Lab tests: ordered in the room, typed in by the desk when the report comes
 * back, and marked as seen by the doctor who asked for them.
 */
test.describe("from the room to the report", () => {
  test.use({ storageState: DOCTOR_STATE });

  test("the doctor orders, the desk types the report in, and the doctor marks it seen", async ({
    page,
    browser,
    playwright,
    baseURL,
    tag,
  }) => {
    const deskContext = await browser.newContext({ storageState: SHARED_STATE });
    const deskPage = await deskContext.newPage();
    const desk = await asTheDesk(playwright, baseURL);
    const { entry, patient } = await inTheRoom(
      desk,
      deskPage,
      "Tired all the time",
      `Lab${tag}`,
    );

    const opened = await page.request.post("/api/v1/consultations", {
      data: { queue_entry_id: entry.id },
    });
    const notes = (await opened.json()).data;
    await page.goto(`/consultations/${notes.id}`);

    const tests = page.getByRole("region", { name: "Tests" });
    const ordered = tests.getByRole("list", { name: "Tests on this visit" });
    await tests.getByRole("button", { name: "Order Complete blood count" }).click();
    await expect(ordered.getByRole("link", { name: "Complete blood count" })).toBeVisible();
    await expect(
      tests.getByRole("button", { name: "Complete blood count, ordered" }),
    ).toBeDisabled();

    const box = tests.getByRole("combobox", { name: "Order a test" });
    await box.fill("lipid");
    await expect(tests.getByRole("option", { name: /Lipid profile/ })).toBeVisible();
    await box.press("Enter");
    await expect(ordered).toContainText("Nothing to eat for 10 to 12 hours before.");

    // Anything the list does not carry is ordered as it was typed.
    await box.fill(`Serum amylase ${tag}`);
    await box.press("Enter");
    await expect(ordered.getByRole("link", { name: `Serum amylase ${tag}` })).toBeVisible();

    // The same test twice is refused, and says why.
    await box.fill("cbc");
    await box.press("Enter");
    await expect(tests.getByRole("alert")).toHaveText(
      "Complete blood count is already ordered on this visit.",
    );

    // Taken back while the patient is still in the room, it is gone.
    await tests.getByRole("button", { name: `Take back Serum amylase ${tag}` }).click();
    await expect(ordered.getByRole("link", { name: `Serum amylase ${tag}` })).toHaveCount(0);
    await expect(ordered.getByRole("listitem")).toHaveCount(2);

    // The desk finds it waiting, and types the report in.
    const listed = await (
      await desk.get(`/api/v1/lab-orders?consultation_id=${notes.id}`)
    ).json();
    const blood = listed.data.items.find(
      (item: { test_name: string }) => item.test_name === "Complete blood count",
    );
    await deskPage.goto(`/lab?q=Lab${tag}`);
    await expect(deskPage.getByRole("link", { name: /Complete blood count/ })).toBeVisible();
    await deskPage.getByRole("link", { name: /Complete blood count/ }).click();
    const form = deskPage.getByRole("form", { name: "The report" });
    await form.getByLabel("Haemoglobin", { exact: true }).fill("10.4");
    // Marked as it is typed, against the range filled in for her.
    await expect(form.getByText("Low", { exact: true })).toBeVisible();
    await form.getByLabel("Platelet count", { exact: true }).fill("250");
    await form.getByRole("button", { name: "Save the report" }).click();

    const report = deskPage.getByRole("table", { name: "Values on the report" });
    await expect(report.getByRole("row", { name: /Haemoglobin/ })).toContainText(/10\.4.*Low/);
    await expect(report.getByRole("row")).toHaveCount(3);
    await expect(deskPage.getByText("1 outside range")).toBeVisible();
    // Marking it seen is the doctor's, not the desk's.
    await expect(deskPage.getByRole("button", { name: "Mark as seen" })).toHaveCount(0);

    // Back for the doctor, on the first page.
    await page.goto("/dashboard");
    const back = page.getByRole("region", { name: /Reports back for you/ });
    await back.getByRole("link", { name: new RegExp(`Lab${tag}`) }).click();
    await expect(page).toHaveURL(new RegExp(`/lab/${blood.id}$`));
    await page.getByRole("button", { name: "Mark as seen" }).click();
    await expect(page.getByText("Seen by the doctor")).toBeVisible();
    await expect(page.getByRole("button", { name: "Put the report right" })).toHaveCount(0);

    // And on the patient's record, opening in place.
    await page.goto(`/patients/${patient.id}`);
    const labs = page.getByRole("region", { name: "Lab tests" });
    await labs.getByRole("button", { name: /Complete blood count/ }).click();
    await expect(labs.getByRole("table")).toContainText("10.4");

    await deskContext.close();
    await desk.dispose();
  });
});

test.describe("at the desk", () => {
  test.use({ storageState: SHARED_STATE });

  test("a report is checked before it is saved, a test not done is cancelled, and a report typed against the wrong test comes off", async ({
    page,
    browser,
    tag,
  }) => {
    const doctorContext = await browser.newContext({ storageState: DOCTOR_STATE });
    const doctor = doctorContext.request;
    const { entry } = await inTheRoom(page.request, page, "Chest pain", `Desk${tag}`);
    const notes = (
      await (
        await doctor.post("/api/v1/consultations", { data: { queue_entry_id: entry.id } })
      ).json()
    ).data;
    const order = async (test_code: string) => {
      const made = await doctor.post("/api/v1/lab-orders", {
        data: { consultation_id: notes.id, test_code },
      });
      expect(made.ok(), await made.text()).toBeTruthy();
      return (await made.json()).data;
    };
    const ecg = await order("ecg");
    const echo = await order("echo");
    const saved = await doctor.patch(`/api/v1/consultations/${notes.id}`, {
      data: { version: notes.version, chief_complaint: "Chest pain on exertion" },
    });
    const finished = await doctor.post(`/api/v1/consultations/${notes.id}/complete`, {
      data: { version: (await saved.json()).data.version },
    });
    expect(finished.ok(), await finished.text()).toBeTruthy();

    // Nothing typed is refused before anything is sent.
    await page.goto(`/lab/${ecg.id}`);
    const form = page.getByRole("form", { name: "The report" });
    await form.getByRole("button", { name: "Save the report" }).click();
    await expect(form.getByRole("alert")).toHaveText("Type in what the report says.");

    await form.getByLabel("What the report says").fill("Sinus rhythm, rate 78. No ST changes.");
    await form.getByRole("button", { name: "Save the report" }).click();
    await expect(page.getByText("Sinus rhythm, rate 78. No ST changes.")).toBeVisible();

    // Typed against the wrong test: it comes off, and the order waits again.
    await page.getByRole("button", { name: "Typed against the wrong test?" }).click();
    await page.getByRole("button", { name: "Yes, take it off" }).click();
    await expect(page.getByRole("heading", { name: "Type in the report" })).toBeVisible();
    await expect(page.getByText("Waiting for the report")).toBeVisible();

    // Not being done: a reason is needed, and it stays on the record.
    await page.goto(`/lab/${echo.id}`);
    await page.getByRole("button", { name: "Not being done? Cancel the test" }).click();
    await page.getByRole("button", { name: "Cancel the test" }).click();
    await expect(page.getByText("Say why it is not being done.")).toBeVisible();
    await page.getByLabel("Why is it not being done?").fill("Done at the hospital last week");
    await page.getByRole("button", { name: "Cancel the test" }).click();
    await expect(page.getByRole("heading", { name: "Cancelled" })).toBeVisible();
    await expect(page.getByText("Done at the hospital last week")).toBeVisible();

    await page.goto(`/lab?show=cancelled&q=Desk${tag}`);
    await expect(page.getByRole("link", { name: /Echocardiogram/ })).toBeVisible();

    await doctorContext.close();
  });
});
