import { addPatient, expect, nextWeekday, test } from "./fixtures";
import { DOCTOR_STATE, SHARED_STATE } from "./state";
import { asTheDesk, profile } from "./visits";

type Desk = Awaited<ReturnType<typeof asTheDesk>>;

/** Has the desk book somebody in with the doctor, which tells the doctor. */
async function bookWithTheDoctor(desk: Desk, lastName: string, reason: string) {
  const made = await desk.post("/api/v1/patients", {
    data: {
      first_name: "Tara",
      last_name: lastName,
      phone: `9${Date.now()}`.slice(0, 10),
      gender: "female",
      date_of_birth: "1990-05-06",
      confirm_duplicate: true,
    },
  });
  expect(made.ok(), await made.text()).toBeTruthy();
  const patient = (await made.json()).data;

  // Other tests book the same doctor, so take whichever time is still free.
  const day = nextWeekday(4);
  const free = (
    await (await desk.get(`/api/v1/doctors/${profile().id}/availability?date=${day}`)).json()
  ).data.slots.find((slot: { state: string }) => slot.state === "free");
  const booked = await desk.post("/api/v1/appointments", {
    data: {
      patient_id: patient.id,
      doctor_id: profile().id,
      date: day,
      start_time: free.start_time.slice(0, 5),
      reason,
    },
  });
  expect(booked.ok(), await booked.text()).toBeTruthy();
  return (await booked.json()).data;
}

/** What reaches whom, seen from the bell and the page behind it. */
test.describe("the doctor hears", () => {
  test.use({ storageState: DOCTOR_STATE });

  test("about a booking the desk made, and opening it marks it read", async ({
    page,
    playwright,
    baseURL,
    tag,
  }) => {
    const desk = await asTheDesk(playwright, baseURL);
    const appointment = await bookWithTheDoctor(desk, `Bell${tag}`, `Knee pain ${tag}`);

    await page.goto("/dashboard");
    await page.getByRole("button", { name: /^Notifications, \d+ unread$/ }).click();
    const panel = page.getByRole("dialog", { name: "Notifications" });
    const notice = panel.getByRole("button", {
      name: new RegExp(`^Unread\\..*Tara Bell${tag} booked for`),
    });
    await expect(notice).toBeVisible();
    await expect(notice).toContainText(`Knee pain ${tag}`);

    await notice.click();
    await expect(page).toHaveURL(new RegExp(`/appointments/${appointment.id}$`));
    await expect(panel).toBeHidden();

    // Opened is read, wherever it is shown next.
    await page.goto("/notifications");
    const listed = page.getByRole("button", { name: new RegExp(`Tara Bell${tag} booked for`) });
    await expect(listed).toBeVisible();
    await expect(listed).not.toHaveAccessibleName(/^Unread/);
    await desk.dispose();
  });

  test("the panel closes on Escape and hands focus back to the bell", async ({ page }) => {
    await page.goto("/dashboard");
    const bell = page.getByRole("button", { name: /^Notifications/ });
    await bell.click();
    await expect(page.getByRole("dialog", { name: "Notifications" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("dialog", { name: "Notifications" })).toBeHidden();
    await expect(bell).toBeFocused();
  });

  test("the full list, all marked read, and the choices a doctor is offered", async ({
    page,
    playwright,
    baseURL,
    tag,
  }) => {
    const desk = await asTheDesk(playwright, baseURL);
    await bookWithTheDoctor(desk, `Read${tag}`, `Follow-up ${tag}`);
    await desk.dispose();

    await page.goto("/notifications");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Notifications");

    const email = page.getByRole("region", { name: "Also by email" });
    await expect(email.getByRole("switch", { name: "Email me: New bookings" })).toBeVisible();
    await expect(email.getByRole("switch", { name: "Email me: Lab results" })).toBeVisible();
    // Money that comes in online is for whoever reads bills, not a doctor.
    await expect(email.getByRole("switch", { name: /Online payments/ })).toHaveCount(0);

    // Opening unread while the change is still on its way reads the list from
    // before it. That answer arriving after the change has landed used to be
    // the one kept, so the page went on showing everything as unread.
    const wait = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
    await page.route("**/api/v1/notifications/read-all", async (route) => {
      await wait(1000);
      await route.continue();
    });
    let first = true;
    await page.route("**/api/v1/notifications?show=unread*", async (route) => {
      if (!first) return route.continue();
      first = false;
      const before = await route.fetch();
      await wait(4000);
      await route.fulfill({ response: before });
    });
    await page.getByRole("button", { name: "Mark all read" }).click();
    await page.getByRole("tab", { name: /Unread/ }).click();
    await expect(page.getByText("You are all caught up")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Notifications", exact: true }),
    ).toBeVisible();
  });

  test("the audit log is not a doctor's to read", async ({ page }) => {
    await expect(page.getByRole("link", { name: "Audit log" })).toHaveCount(0);
    await page.goto("/audit");
    await expect(
      page.getByRole("heading", { name: "Your role does not cover this" }),
    ).toBeVisible();
  });
});

test.describe("the audit log", () => {
  test.use({ storageState: SHARED_STATE });

  test("reads what was just done, narrows to it, and opens the record", async ({
    page,
    tag,
  }) => {
    const patient = await addPatient(page, { first_name: "Ishan", last_name: `Log${tag}` });
    const changed = await page.request.patch(`/api/v1/patients/${patient.id}`, {
      data: { phone: "9820077441" },
    });
    expect(changed.ok(), await changed.text()).toBeTruthy();

    await page.goto("/audit");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Audit log");
    await page.getByPlaceholder("A name, a bill number, a patient").fill(`Log${tag}`);
    await expect(page).toHaveURL(new RegExp(`q=Log${tag}`));

    const rows = page.locator("main li");
    await expect(rows).toHaveCount(2);
    await expect(rows.first()).toContainText("edited the details of");
    await expect(rows.last()).toContainText("registered");

    await rows.first().getByRole("button", { name: "Show details" }).click();
    await expect(rows.first()).toContainText("Phone");
    await expect(rows.first()).toContainText("9820077441");
    await expect(rows.first()).toContainText(/Chrome|Firefox|Safari|Another program/);

    await rows
      .first()
      .getByRole("link", { name: new RegExp(`Log${tag}`) })
      .click();
    await expect(page).toHaveURL(new RegExp(`/patients/${patient.id}$`));
  });

  test("the parts of the clinic and a backwards stretch of days", async ({ page }) => {
    await page.goto("/audit");
    await page.getByRole("tab", { name: "Billing" }).click();
    await expect(page).toHaveURL(/area=billing/);
    await expect(page.getByRole("tab", { name: "Billing" })).toHaveAttribute(
      "aria-selected",
      "true",
    );

    await page.goto("/audit?from=2026-09-20&to=2026-09-10");
    await expect(page.locator('p[role="alert"]')).toHaveText(
      "The last day comes before the first one.",
    );

    await page.goto("/audit?q=nothing-could-ever-match-this");
    await expect(page.getByText("Nothing matches")).toBeVisible();
    await page.getByRole("button", { name: "Clear" }).click();
    await expect(page).toHaveURL(/\/audit$/);
  });
});
