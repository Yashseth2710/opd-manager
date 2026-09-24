import { addPatient, expect, test } from "./fixtures";
import { DOCTOR_STATE, EMPTY_STATE, SHARED_STATE } from "./state";
import { asTheDesk, inTheRoom, profile } from "./visits";

/** How the clinic has been doing, over whatever stretch of days is asked for. */
test.describe("for the desk", () => {
  test.use({ storageState: SHARED_STATE });

  test("a visit and a bill today show up in the day's figures", async ({ page, tag }) => {
    const doctor = profile();
    const patient = await addPatient(page, { last_name: `Report${tag}` });

    const placed = await page.request.post("/api/v1/queue/walk-in", {
      data: { patient_id: patient.id, doctor_id: doctor.id, reason: "Sore throat" },
    });
    expect(placed.ok(), await placed.text()).toBeTruthy();
    const entry = (await placed.json()).data;
    await page.request.post(`/api/v1/queue/${entry.id}/start`);
    await page.request.post(`/api/v1/queue/${entry.id}/complete`);

    const bill = await page.request.post("/api/v1/invoices", {
      data: {
        patient_id: patient.id,
        queue_entry_id: entry.id,
        items: [
          {
            item_type: "procedure",
            description: `Throat swab ${tag}`,
            unit_price: "450.00",
          },
        ],
        issue: true,
      },
    });
    expect(bill.ok(), await bill.text()).toBeTruthy();
    const raised = (await bill.json()).data;
    const took = await page.request.post(`/api/v1/invoices/${raised.id}/payments`, {
      data: { amount: "450.00", method: "upi" },
    });
    expect(took.ok(), await took.text()).toBeTruthy();

    await page.goto("/reports?range=today");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Reports");

    const headline = page.getByRole("definition").first();
    await expect(headline).not.toHaveText("0");

    const money = page.getByRole("region", { name: "How it was paid" });
    await expect(money).toContainText("UPI");
    await expect(money).toContainText("All of it");

    const doctors = page.getByRole("region", { name: "Each doctor" });
    await expect(doctors.getByRole("link", { name: doctor.display_name })).toBeVisible();

    const charges = page.getByRole("region", { name: "What the bills were for" });
    await expect(charges).toContainText(`Throat swab ${tag}`);

    // A single day has nothing to draw a day-by-day chart from.
    await expect(page.getByRole("region", { name: "Day by day" })).toHaveCount(0);
  });

  test("the chips change the stretch, and the address remembers it", async ({ page }) => {
    await page.goto("/reports");
    await expect(page.getByRole("button", { name: "Last 7 days" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    const chart = page.getByRole("region", { name: "Day by day" });
    await expect(chart.getByRole("listitem")).toHaveCount(14);

    await page.getByRole("button", { name: "Last 30 days" }).click();
    await expect(page).toHaveURL(/range=month/);
    await expect(chart.getByRole("listitem")).toHaveCount(60);

    // The columns read the day out when one is pointed at.
    await chart.getByRole("button").last().hover();
    await expect(chart.getByRole("figure")).toContainText(/seen|₹/);

    await page.getByRole("button", { name: "Money", exact: true }).click();
    await expect(chart).toContainText("Taken each day");

    await page.reload();
    await expect(page.getByRole("button", { name: "Last 30 days" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  test("dates of your own, and a last day that comes first", async ({ page }) => {
    await page.goto("/reports");
    await page.getByRole("button", { name: "Choose dates" }).click();

    const today = new Date();
    const iso = (day: Date) => day.toISOString().slice(0, 10);
    const week = new Date(today);
    week.setDate(week.getDate() - 6);

    const from = page.getByRole("textbox", { name: "From", exact: true });
    const to = page.getByRole("textbox", { name: "To", exact: true });
    await from.fill(iso(week));
    await to.fill(iso(today));
    await expect(page.getByRole("region", { name: "How it was paid" })).toBeVisible();

    // Backwards: refused without the server being asked.
    await from.fill(iso(today));
    await to.fill(iso(week));
    // The message is said twice, beside the boxes and in the panel below.
    // Next's own route announcer is an alert as well, hence the tag.
    await expect(page.locator('p[role="alert"]')).toHaveText(
      "The last day comes before the first one.",
    );
    await expect(page.getByRole("heading", { name: "Nothing to show yet" })).toBeVisible();
  });

  test("the day book downloads the payments behind the figures", async ({ page }) => {
    await page.goto("/reports?range=today");
    const download = page.waitForEvent("download");
    await page.getByRole("link", { name: "Day book" }).click();
    const file = await download;
    expect(file.suggestedFilename()).toMatch(/^day-book-\d{4}-\d{2}-\d{2}-to-/);
  });
});

test.describe("for a doctor", () => {
  test.use({ storageState: DOCTOR_STATE });

  test("a doctor's page is their own work, not the clinic's", async ({
    page,
    browser,
    playwright,
    baseURL,
    tag,
  }) => {
    // The desk sees a patient through to the door, so the doctor has a day
    // to report on whatever else has run before this.
    const deskContext = await browser.newContext({ storageState: SHARED_STATE });
    const desk = await asTheDesk(playwright, baseURL);
    const { entry, doctor } = await inTheRoom(
      desk,
      await deskContext.newPage(),
      "Cough",
      `Mine${tag}`,
    );
    await desk.post(`/api/v1/queue/${entry.id}/complete`);
    await deskContext.close();

    await page.goto("/reports?range=month");
    await expect(page.getByText("Your own patients and bills")).toBeVisible();
    const doctors = page.getByRole("region", { name: "Your line" });
    await expect(doctors.getByRole("link")).toHaveCount(1);
    await expect(doctors.getByRole("link", { name: doctor.display_name })).toBeVisible();
    await desk.dispose();
  });
});

test.describe("a clinic with nothing in it", () => {
  test.use({ storageState: EMPTY_STATE });

  test("says so rather than drawing empty charts", async ({ page }) => {
    await page.goto("/reports?range=week");
    await expect(page.getByRole("heading", { name: "Nothing in these days" })).toBeVisible();
  });

  test("the day's page still shows the money panel, at nil", async ({ page }) => {
    await page.goto("/dashboard");
    const money = page.getByRole("region", { name: "Money today" });
    await expect(money).toContainText("Nothing yet");
    await expect(money).toContainText("No bills handed over yet");
    await expect(money.getByRole("link", { name: "Reports" })).toBeVisible();
  });
});
