import { addBooking, addPatient, bookableDoctor, expect, nextWeekday, test } from "./fixtures";
import { EMPTY_STATE } from "./state";

const THURSDAY = 3;

test("booking from a free slot on the day sheet fills in all but the patient", async ({
  page,
  tag,
}) => {
  const doctor = await bookableDoctor(page, { last_name: `Sheet${tag}` });
  const patient = await addPatient(page, { last_name: `Picked${tag}` });
  const day = nextWeekday(THURSDAY);

  await page.goto(`/appointments?date=${day}&doctor=${doctor.id}`);
  await page.getByRole("link", { name: "Book 9:30 am" }).click();

  await expect(page).toHaveURL(/\/appointments\/new\?/);
  await expect(page.getByRole("button", { name: "9:30 am" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await page.getByLabel("Find the patient").fill(`Picked${tag}`);
  await page.getByRole("button", { name: new RegExp(`Asha Picked${tag}`) }).click();
  await page.getByLabel("Reason for the visit").fill("Cough for a week");
  await page.getByRole("button", { name: "Book appointment" }).click();

  await expect(page).toHaveURL(/\/appointments\/[0-9a-f-]{36}$/);
  await expect(page.getByRole("heading", { name: `Asha Picked${tag}` })).toBeVisible();
  await expect(page.getByText("9:30 am", { exact: true })).toBeVisible();
  await expect(page.getByText("Cough for a week")).toBeVisible();
  // One line of history, with who did it.
  await expect(page.getByRole("listitem").filter({ hasText: "Booked" })).toHaveCount(1);
  expect(patient.id).toBeTruthy();
});

test("the form says what is missing rather than sending half a booking", async ({
  page,
  tag,
}) => {
  // Two doctors, so the form has nobody to pick on its own: with only one it
  // rightly chooses them, and whether the list had loaded before the click
  // would decide what this test saw.
  await bookableDoctor(page, { last_name: `Either${tag}` });
  const second = await bookableDoctor(page, { last_name: `Or${tag}` });

  await page.goto("/appointments/new");
  await expect(
    page.getByLabel("Doctor").locator(`option[value="${second.id}"]`),
  ).toBeAttached();
  await page.getByRole("button", { name: "Book appointment" }).click();

  await expect(page.getByText("Choose who the appointment is for.")).toBeVisible();
  await expect(page.getByText("Choose a doctor.")).toBeVisible();
  await expect(page.getByLabel("Find the patient")).toBeFocused();
});

test("a time somebody else has just taken is cleared and shown as taken", async ({
  page,
  tag,
}) => {
  const doctor = await bookableDoctor(page, { last_name: `Race${tag}` });
  const mine = await addPatient(page, { last_name: `Mine${tag}` });
  const theirs = await addPatient(page, { first_name: "Rahul", last_name: `Theirs${tag}` });
  const day = nextWeekday(THURSDAY);

  await page.goto(
    `/appointments/new?patient=${mine.id}&doctor=${doctor.id}&date=${day}&time=10:00`,
  );
  await expect(page.getByRole("button", { name: "10:00 am" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  // The other desk gets there first.
  await addBooking(page, {
    patient_id: theirs.id,
    doctor_id: doctor.id,
    date: day,
    start_time: "10:00",
  });
  await page.getByRole("button", { name: "Book appointment" }).click();

  await expect(
    page.getByText("That time has just been booked. Pick another one."),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "10:00 am" })).toBeDisabled();
  await expect(page).toHaveURL(/\/appointments\/new/);
});

test("confirming and then moving puts it back to booked and says where it was", async ({
  page,
  tag,
}) => {
  const doctor = await bookableDoctor(page, { last_name: `Move${tag}` });
  const patient = await addPatient(page, { last_name: `Mover${tag}` });
  const day = nextWeekday(THURSDAY);
  const made = await addBooking(page, {
    patient_id: patient.id,
    doctor_id: doctor.id,
    date: day,
    start_time: "09:00",
  });

  await page.goto(`/appointments/${made.id}`);
  await page.getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText("Confirmed", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Confirm" })).toBeHidden();

  await page.getByRole("button", { name: "Move" }).click();
  // Where it is now is shown, and cannot be picked as the new time.
  await expect(page.getByRole("button", { name: /9:00 am/ })).toBeDisabled();
  await page.getByRole("button", { name: "12:30 pm" }).click();
  await page.getByRole("button", { name: "Move appointment" }).click();

  await expect(page.getByText("12:30 pm", { exact: true })).toBeVisible();
  await expect(page.getByText(/Moved from .*, 9:00 am/)).toBeVisible();
  await expect(page.getByText("Booked", { exact: true }).first()).toBeVisible();

  await page.goto(`/appointments?date=${day}&doctor=${doctor.id}`);
  await expect(page.getByRole("link", { name: "Book 9:00 am" })).toBeVisible();
});

test("cancelling keeps the reason and gives the slot back", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { last_name: `Cancel${tag}` });
  const patient = await addPatient(page, { last_name: `Gone${tag}` });
  const day = nextWeekday(THURSDAY);
  const made = await addBooking(page, {
    patient_id: patient.id,
    doctor_id: doctor.id,
    date: day,
    start_time: "10:30",
  });

  await page.goto(`/appointments/${made.id}`);
  await page.getByRole("button", { name: "Cancel appointment" }).click();
  await page.getByRole("button", { name: "Booked by mistake" }).click();
  await page.getByRole("button", { name: "Cancel appointment" }).click();

  await expect(page.getByText("Cancelled", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("“Booked by mistake”").first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Book again" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Move" })).toBeHidden();

  await page.goto(`/appointments?date=${day}&doctor=${doctor.id}`);
  // The cancelled line stays, and the time it held is free again beside it.
  await expect(page.getByText(`Asha Gone${tag}`)).toBeVisible();
  await expect(page.getByRole("link", { name: "Book 10:30 am" })).toBeVisible();
});

test("changing the details is kept and recorded", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { last_name: `Edit${tag}` });
  const patient = await addPatient(page, { last_name: `Edited${tag}` });
  const made = await addBooking(page, {
    patient_id: patient.id,
    doctor_id: doctor.id,
    date: nextWeekday(THURSDAY),
    start_time: "12:00",
  });

  await page.goto(`/appointments/${made.id}`);
  await page.getByRole("button", { name: "Edit details" }).click();
  await page.getByLabel("Reason for the visit").fill("Knee pain on the stairs");
  await page.getByRole("radio", { name: "By phone" }).click();
  await page.getByRole("button", { name: "Save changes" }).click();

  await expect(page.getByText("Knee pain on the stairs")).toBeVisible();
  await expect(page.getByText("By phone")).toBeVisible();
  await expect(page.getByText("Details changed")).toBeVisible();
});

test("a booked time is struck out on the form and cannot be picked", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { last_name: `Taken${tag}` });
  const patient = await addPatient(page, { last_name: `Holder${tag}` });
  const day = nextWeekday(THURSDAY);
  await addBooking(page, {
    patient_id: patient.id,
    doctor_id: doctor.id,
    date: day,
    start_time: "09:30",
  });

  await page.goto(`/appointments/new?doctor=${doctor.id}&date=${day}`);

  await expect(page.getByRole("button", { name: "9:30 am" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "10:00 am" })).toBeEnabled();
  await expect(
    page.getByText("6 of 7 appointments still free, 30 minutes each."),
  ).toBeVisible();
});

test("the day moves with the arrows and keeps the doctor", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { last_name: `Days${tag}` });
  const day = nextWeekday(THURSDAY);

  await page.goto(`/appointments?date=${day}&doctor=${doctor.id}`);
  await page.getByRole("button", { name: "Next day" }).click();

  await expect(page).toHaveURL(new RegExp(`doctor=${doctor.id}`));
  await expect(page).not.toHaveURL(new RegExp(`date=${day}`));
  await page.getByRole("button", { name: "Back to today" }).click();
  await expect(page).not.toHaveURL(/date=/);
  await expect(page).toHaveURL(new RegExp(`doctor=${doctor.id}`));
});

test("a patient's record shows what is coming up and books with them filled in", async ({
  page,
  tag,
}) => {
  const doctor = await bookableDoctor(page, { first_name: "Vikram", last_name: `Rec${tag}` });
  const patient = await addPatient(page, { last_name: `Record${tag}` });
  await addBooking(page, {
    patient_id: patient.id,
    doctor_id: doctor.id,
    date: nextWeekday(THURSDAY),
    start_time: "11:30",
  });

  await page.goto(`/patients/${patient.id}`);
  await expect(page.getByText(`Dr Vikram Rec${tag}`)).toBeVisible();
  await expect(page.getByText(/11:30 am/)).toBeVisible();

  await page.getByRole("link", { name: "Book", exact: true }).click();
  await expect(page.getByText(`Asha Record${tag}`)).toBeVisible();
  await expect(page.getByRole("button", { name: "Change" })).toBeVisible();
});

test("a doctor's free times lead straight into booking", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { last_name: `Free${tag}` });
  const day = nextWeekday(THURSDAY);

  await page.goto(`/doctors/${doctor.id}`);
  await page.getByLabel("Show this day").fill(day);
  await page.getByRole("link", { name: "12:00 pm" }).click();

  await expect(page).toHaveURL(/\/appointments\/new\?/);
  await expect(page.getByRole("button", { name: "12:00 pm" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

test("leave taken after a booking is flagged on it", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { first_name: "Meera", last_name: `Away${tag}` });
  const patient = await addPatient(page, { last_name: `Flagged${tag}` });
  const day = nextWeekday(THURSDAY);
  await addBooking(page, {
    patient_id: patient.id,
    doctor_id: doctor.id,
    date: day,
    start_time: "09:00",
  });
  await page.request.post(`/api/v1/doctors/${doctor.id}/leaves`, {
    data: { starts_on: day, reason: "Conference" },
  });

  await page.goto(`/appointments?date=${day}&doctor=${doctor.id}`);

  await expect(page.getByText(`Dr Meera Away${tag} is on leave that day.`)).toBeVisible();
  await expect(page.getByText("On leave that day (Conference)")).toBeVisible();
});

test("a slow booking keeps saying so and books once however often it is pressed", async ({
  page,
  tag,
}) => {
  const doctor = await bookableDoctor(page, { last_name: `Slow${tag}` });
  const patient = await addPatient(page, { last_name: `Patient${tag}` });
  const day = nextWeekday(THURSDAY);

  await page.route("**/api/v1/appointments", async (route) => {
    if (route.request().method() === "POST") {
      await new Promise((settle) => setTimeout(settle, 2500));
    }
    await route.continue();
  });

  await page.goto(
    `/appointments/new?patient=${patient.id}&doctor=${doctor.id}&date=${day}&time=12:30`,
  );
  await expect(page.getByRole("button", { name: "Change" })).toBeVisible();
  const book = page.getByRole("button", { name: "Book appointment" });
  await book.evaluate((button: HTMLButtonElement) => {
    button.click();
    button.click();
    button.click();
  });

  await expect(page.getByRole("button", { name: "Booking" })).toBeVisible();
  await expect(page).toHaveURL(/\/appointments\/[0-9a-f-]{36}$/);

  const listed = await page.request.get(
    `/api/v1/appointments?date=${day}&doctor_id=${doctor.id}`,
  );
  expect((await listed.json()).data.items).toHaveLength(1);
});

test("a reason that is trying to be code is shown as text", async ({ page, tag }) => {
  const doctor = await bookableDoctor(page, { last_name: `Code${tag}` });
  const patient = await addPatient(page, { last_name: `Script${tag}` });
  const made = await addBooking(page, {
    patient_id: patient.id,
    doctor_id: doctor.id,
    date: nextWeekday(THURSDAY),
    start_time: "10:00",
    reason: "<img src=x onerror=alert(1)>",
  });

  let alerted = false;
  page.on("dialog", async (dialog) => {
    alerted = true;
    await dialog.dismiss();
  });
  await page.goto(`/appointments/${made.id}`);

  await expect(page.getByText("<img src=x onerror=alert(1)>")).toBeVisible();
  expect(alerted).toBe(false);
});

test("an appointment that is not here says so", async ({ page }) => {
  await page.goto("/appointments/01a0b31f-0000-7000-8000-000000000000");
  await expect(page.getByRole("heading", { name: "No such appointment" })).toBeVisible();
});

test.describe("a clinic that has not added anyone yet", () => {
  test.use({ storageState: EMPTY_STATE });

  test("is told to add a doctor before anything can be booked", async ({ page }) => {
    await page.goto("/appointments");
    await expect(page.getByRole("heading", { name: "No doctors yet" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Add a doctor" })).toBeVisible();
  });
});

test.describe("nobody signed in", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("is sent to sign in", async ({ page }) => {
    await page.goto("/appointments");
    await expect(page).toHaveURL(/\/login/);
  });
});
